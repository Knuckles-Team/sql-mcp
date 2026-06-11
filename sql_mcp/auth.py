"""Connection and server-policy configuration for sql-mcp (CONCEPT:SQL-1.2).

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
import os

from agent_utilities.base_utilities import get_logger, to_boolean
from sqlalchemy.engine import URL, make_url

from sql_mcp.dialects import build_url

logger = get_logger(__name__)

DEFAULT_MAX_ROWS = 500
DEFAULT_TIMEOUT_SECONDS = 30.0


def _connection_from_spec(name: str, spec: object) -> URL:
    """Build a SQLAlchemy URL from one ``SQL_CONNECTIONS`` entry."""
    if isinstance(spec, str):
        return make_url(spec)
    if isinstance(spec, dict):
        if "url" in spec:
            return make_url(spec["url"])
        if "dialect" in spec:
            return build_url(
                spec["dialect"],
                host=spec.get("host"),
                port=spec.get("port"),
                username=spec.get("username"),
                password=spec.get("password"),
                database=spec.get("database"),
                options=spec.get("options"),
            )
    raise ValueError(
        f"Connection {name!r} in SQL_CONNECTIONS must be a DSN string or an "
        "object with 'url' or 'dialect' fields."
    )


def load_connections() -> dict[str, URL]:
    """Load the named-connection registry from the environment."""
    raw = os.getenv("SQL_CONNECTIONS", "")
    if raw.strip():
        try:
            mapping = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"SQL_CONNECTIONS is not valid JSON: {exc}") from exc
        if not isinstance(mapping, dict) or not mapping:
            raise ValueError(
                "SQL_CONNECTIONS must be a non-empty JSON object mapping "
                "connection names to DSNs or connection objects."
            )
        return {
            name: _connection_from_spec(name, spec) for name, spec in mapping.items()
        }

    url = os.getenv("SQL_URL", "")
    if url.strip():
        return {"default": make_url(url)}

    if os.getenv("SQL_DIALECT") or os.getenv("SQL_HOST"):
        options_raw = os.getenv("SQL_OPTIONS", "")
        options = json.loads(options_raw) if options_raw.strip() else None
        port_raw = os.getenv("SQL_PORT", "")
        return {
            "default": build_url(
                os.getenv("SQL_DIALECT", "postgres"),
                host=os.getenv("SQL_HOST"),
                port=int(port_raw) if port_raw.strip() else None,
                username=os.getenv("SQL_USERNAME"),
                password=os.getenv("SQL_PASSWORD"),
                database=os.getenv("SQL_DATABASE"),
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
    return to_boolean(os.getenv("SQL_ALLOW_WRITES", "False"))


def default_max_rows() -> int:
    """Per-call row cap (``SQL_MAX_ROWS``, default 500); requests are clamped."""
    return int(os.getenv("SQL_MAX_ROWS", str(DEFAULT_MAX_ROWS)))


def default_timeout() -> float:
    """Per-call statement timeout in seconds (``SQL_TIMEOUT_SECONDS``)."""
    return float(os.getenv("SQL_TIMEOUT_SECONDS", str(DEFAULT_TIMEOUT_SECONDS)))


_api = None


def get_api():
    """Return the process-wide :class:`~sql_mcp.api_client.Api` instance.

    Built lazily from the environment; ``reset_api()`` clears the cache (used
    by tests and after configuration changes).
    """
    global _api
    if _api is None:
        from sql_mcp.api_client import Api

        _api = Api(
            connections=load_connections(),
            allow_writes=allow_writes(),
            max_rows=default_max_rows(),
            timeout=default_timeout(),
        )
    return _api


def reset_api() -> None:
    """Dispose the cached client so the next ``get_api()`` re-reads the env."""
    global _api
    if _api is not None:
        _api.dispose()
    _api = None
