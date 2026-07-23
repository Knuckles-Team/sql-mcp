"""Connection and server-policy configuration for sql-mcp (CONCEPT:SQ-OS.identity.env-parsing-secret-redaction).

Named connections come from the environment, in priority order:

1. ``SQL_CONNECTIONS`` — JSON mapping name -> DSN string or
   ``{"url": ...}`` / ``{"dialect": ..., "host": ..., "port": ...,
   "username": ..., "password": ..., "database": ..., "options": {...}}``.
2. ``SQL_URL`` — a single DSN registered as connection ``"default"``.
3. Discrete fields — ``SQL_DIALECT`` + ``SQL_HOST`` / ``SQL_PORT`` /
   ``SQL_USERNAME`` / ``SQL_PASSWORD`` / ``SQL_DATABASE`` / ``SQL_OPTIONS``
   (JSON), registered as ``"default"``.
4. Nothing configured — a zero-infra in-memory SQLite connection named
   ``"memory"`` so the server works out of the box.

Secrets are never logged: URLs are parsed into ``sqlalchemy.engine.URL``
objects and only ever rendered with ``hide_password=True``.
"""

import json
import logging
import math
import threading
from typing import Any

from agent_utilities.core.config import setting
from sqlalchemy.engine import URL, make_url

from sql_mcp.dialects import build_url

logger = logging.getLogger(__name__)

DEFAULT_MAX_ROWS = 500
DEFAULT_TIMEOUT_SECONDS = 30.0
MAX_CONNECTIONS = 64
MAX_CONNECTION_CONFIG_BYTES = 1_000_000
MAX_CONNECTION_NAME_LENGTH = 128


def _valid_connection_name(name: object) -> bool:
    return (
        isinstance(name, str)
        and bool(name.strip())
        and len(name) <= MAX_CONNECTION_NAME_LENGTH
        and "\x00" not in name
    )


def _connection_from_spec(name: str, spec: object) -> URL:
    """Build a SQLAlchemy URL from one ``SQL_CONNECTIONS`` entry."""
    if isinstance(spec, str):
        try:
            return make_url(spec)
        except Exception:
            raise ValueError(f"Connection {name!r} has an invalid SQL URL.") from None
    if isinstance(spec, dict):
        if "url" in spec:
            if not isinstance(spec["url"], str):
                raise ValueError(f"Connection {name!r} has an invalid SQL URL.")
            try:
                return make_url(spec["url"])
            except Exception:
                raise ValueError(
                    f"Connection {name!r} has an invalid SQL URL."
                ) from None
        if "dialect" in spec:
            if not isinstance(spec["dialect"], str):
                raise ValueError(f"Connection {name!r} has an invalid SQL dialect.")
            options = spec.get("options")
            if options is not None and not isinstance(options, dict):
                raise ValueError(
                    f"Connection {name!r} options must be a JSON object."
                )
            return build_url(
                spec["dialect"],
                host=spec.get("host"),
                port=spec.get("port"),
                username=spec.get("username"),
                password=spec.get("password"),
                database=spec.get("database"),
                options=options,
            )
    raise ValueError(
        f"Connection {name!r} in SQL_CONNECTIONS must be a DSN string or an "
        "object with 'url' or 'dialect' fields."
    )


def load_connections() -> dict[str, URL]:
    """Load the named-connection registry from the environment."""
    raw = setting("SQL_CONNECTIONS", "")
    if raw.strip():
        if len(raw.encode("utf-8")) > MAX_CONNECTION_CONFIG_BYTES:
            raise ValueError("SQL_CONNECTIONS exceeds the configuration size limit.")
        try:
            mapping = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"SQL_CONNECTIONS is not valid JSON: {type(exc).__name__}"
            ) from exc
        if not isinstance(mapping, dict) or not mapping:
            raise ValueError(
                "SQL_CONNECTIONS must be a non-empty JSON object mapping "
                "connection names to DSNs or connection objects."
            )
        if len(mapping) > MAX_CONNECTIONS:
            raise ValueError(
                f"SQL_CONNECTIONS exceeds the {MAX_CONNECTIONS}-connection limit."
            )
        connections: dict[str, URL] = {}
        for name, spec in mapping.items():
            if not _valid_connection_name(name):
                raise ValueError(
                    "SQL_CONNECTIONS names must be non-empty bounded strings."
                )
            connections[name] = _connection_from_spec(name, spec)
        return connections

    url = setting("SQL_URL", "")
    if url.strip():
        try:
            return {"default": make_url(url)}
        except Exception:
            raise ValueError("SQL_URL is not a valid SQLAlchemy URL.") from None

    if setting("SQL_DIALECT", "") or setting("SQL_HOST", ""):
        options_raw = setting("SQL_OPTIONS", "")
        try:
            options = json.loads(options_raw) if options_raw.strip() else None
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"SQL_OPTIONS is not valid JSON: {type(exc).__name__}"
            ) from exc
        if options is not None and not isinstance(options, dict):
            raise ValueError("SQL_OPTIONS must be a JSON object.")
        port_raw = setting("SQL_PORT", "")
        try:
            port = int(port_raw) if port_raw.strip() else None
        except (TypeError, ValueError, OverflowError):
            raise ValueError("SQL_PORT must be an integer between 1 and 65535.") from None
        if port is not None and not 1 <= port <= 65_535:
            raise ValueError("SQL_PORT must be an integer between 1 and 65535.")
        return {
            "default": build_url(
                setting("SQL_DIALECT", "postgres"),
                host=setting("SQL_HOST", "") or None,
                port=port,
                username=setting("SQL_USERNAME", "") or None,
                password=setting("SQL_PASSWORD", "") or None,
                database=setting("SQL_DATABASE", "") or None,
                options=options,
            )
        }

    logger.info(
        "No SQL connection configured (SQL_CONNECTIONS/SQL_URL/SQL_HOST); "
        "registering a zero-infra in-memory SQLite connection named 'memory'."
    )
    return {"memory": make_url("sqlite+pysqlite:///:memory:")}


def allow_writes() -> bool:
    """Whether DML/DDL via ``sql_execute`` is enabled (default: read-only)."""
    return bool(setting("SQL_ALLOW_WRITES", False))


def allow_kg_ingest() -> bool:
    """Whether SQL schema writes into Epistemic Graph are enabled."""
    return bool(setting("SQL_ALLOW_KG_INGEST", False))


def default_max_rows() -> int:
    """Per-call row cap (``SQL_MAX_ROWS``, default 500); requests are clamped."""
    try:
        value = int(setting("SQL_MAX_ROWS", DEFAULT_MAX_ROWS))
    except (TypeError, ValueError, OverflowError):
        raise ValueError("SQL_MAX_ROWS must be a positive integer.") from None
    if value <= 0:
        raise ValueError("SQL_MAX_ROWS must be a positive integer.")
    return value


def default_timeout() -> float:
    """Per-call statement timeout in seconds (``SQL_TIMEOUT_SECONDS``)."""
    try:
        value = float(setting("SQL_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS))
    except (TypeError, ValueError, OverflowError):
        raise ValueError(
            "SQL_TIMEOUT_SECONDS must be a finite, positive number."
        ) from None
    if not math.isfinite(value) or value <= 0:
        raise ValueError("SQL_TIMEOUT_SECONDS must be a finite, positive number.")
    return value


def writable_connections() -> set[str]:
    """Return the explicit server-side connection allowlist for writes.

    Writes require both ``SQL_ALLOW_WRITES=True`` and a connection name in
    ``SQL_WRITE_CONNECTIONS``. An omitted allowlist therefore remains fail closed.
    The value accepts either a JSON string list or comma-separated names.
    """
    raw = str(setting("SQL_WRITE_CONNECTIONS", "")).strip()
    if not raw:
        return set()
    if raw.startswith("["):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            raise ValueError(
                "SQL_WRITE_CONNECTIONS must be a JSON list or comma-separated names."
            ) from None
        if not isinstance(parsed, list) or not all(
            _valid_connection_name(name) for name in parsed
        ):
            raise ValueError("SQL_WRITE_CONNECTIONS JSON value must be a string list.")
        names = {name.strip() for name in parsed}
    else:
        names = {name.strip() for name in raw.split(",") if name.strip()}
    if not names or not all(_valid_connection_name(name) for name in names):
        raise ValueError("SQL_WRITE_CONNECTIONS must name at least one connection.")
    if len(names) > MAX_CONNECTIONS:
        raise ValueError(
            f"SQL_WRITE_CONNECTIONS exceeds the {MAX_CONNECTIONS}-connection limit."
        )
    return names


def default_connection_name() -> str | None:
    """Explicit default named connection, or ``None`` for first configured."""
    value = str(setting("SQL_DEFAULT_CONNECTION", "")).strip()
    if value and not _valid_connection_name(value):
        raise ValueError("SQL_DEFAULT_CONNECTION must be a bounded connection name.")
    return value or None


_api: Any | None = None
_api_lock = threading.RLock()


def get_api():
    """Return the process-wide :class:`~sql_mcp.api_client.Api` instance.

    Built lazily from the environment; ``reset_api()`` clears the cache (used
    by tests and after configuration changes).
    """
    global _api
    with _api_lock:
        if _api is None:
            from sql_mcp.api_client import Api

            _api = Api(
                connections=load_connections(),
                allow_writes=allow_writes(),
                max_rows=default_max_rows(),
                timeout=default_timeout(),
                writable_connections=writable_connections(),
                default_connection=default_connection_name(),
            )
        return _api


def reset_api() -> None:
    """Dispose the cached client so the next ``get_api()`` re-reads the env."""
    global _api
    with _api_lock:
        if _api is not None:
            _api.dispose()
        _api = None
