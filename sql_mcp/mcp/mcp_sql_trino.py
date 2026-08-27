"""Trino- and DuckDB-specific MCP tools for sql-mcp (CA-41, CONCEPT:SQ-OS.governance.sql-2).

The four action-dispatch tools in :mod:`sql_mcp.mcp.mcp_sql` (``sql_query``,
``sql_execute``, ``sql_schema``, ``sql_admin``) already work against a
``trino``/``duckdb`` named connection once :mod:`sql_mcp.dialects` registers
the dialect — no dispatcher change was needed for the generic surface. This
module adds the reads the generic dispatch tools don't cover:

- ``sql_trino_catalogs`` / ``sql_trino_schemas`` — catalog/namespace discovery.
- ``sql_trino_queries`` — a capped, dedicated read of
  ``system.runtime.queries`` (200-row hard cap, independent of the caller's
  requested ``max_rows``).
- ``sql_trino_explain`` — a Trino-scoped ``EXPLAIN`` wrapper that rejects any
  connection whose resolved dialect isn't ``trino``.
- ``sql_duckdb_attach_iceberg`` — runs DuckDB's Iceberg REST-catalog bootstrap
  (``INSTALL``/``LOAD`` the ``iceberg``/``httpfs`` extensions, then
  ``ATTACH … (TYPE ICEBERG, ...)``) against a Lakekeeper-shaped REST catalog.
  This one call is *not* routed through the generic read-only SQL gate
  (:mod:`sql_mcp.safety`) — ``INSTALL``/``LOAD``/``ATTACH`` are DuckDB
  extension/catalog-admin statements, not data-mutating SQL text, and take no
  caller-supplied SQL string at all (every value is a validated, narrowly
  charset-restricted field on :class:`~sql_mcp.sql_input_models.DuckDbAttachIcebergInput`).
  It carries the calling principal's own bearer token (never an ambient
  service credential, matching DEC-CA-04's one-principal rule) and never
  silently degrades to an unauthenticated read: every failure surfaces a
  typed error naming what failed.
"""

import asyncio
from functools import partial
from typing import Any

from fastmcp import FastMCP
from pydantic import Field

from sql_mcp.auth import get_api
from sql_mcp.mcp.mcp_sql import _invoke, _invoke_external, _validate_params
from sql_mcp.sql_input_models import (
    DuckDbAttachIcebergInput,
    TrinoExplainInput,
    TrinoQueriesInput,
    TrinoSchemasInput,
)

_TRINO_QUERIES_ROW_CAP = 200
_DUCKDB_BOOTSTRAP_TIMEOUT_SECONDS = 30.0


def _require_dialect(api: Any, connection: str | None, expected: str) -> str:
    """Resolve ``connection`` and assert it is registered as ``expected``.

    Raises ``ValueError`` naming the actual dialect so a caller pointing a
    Trino-only (or DuckDB-only) tool at the wrong connection gets a clear,
    typed rejection instead of a confusing driver-level error.
    """
    name = api.resolve_connection(connection)
    spec = api.dialect_spec(name)
    actual = spec.name if spec is not None else "unknown"
    if actual != expected:
        raise ValueError(
            f"Connection {name!r} is a {actual!r} dialect connection; this "
            f"tool requires a {expected!r} connection."
        )
    return name


def register_sql_trino_tools(mcp: FastMCP) -> None:
    """Register the Trino discovery/explain tools and the DuckDB attach tool."""

    @mcp.tool(tags={"trino"})
    async def sql_trino_catalogs(
        connection: str = Field(
            default="",
            max_length=128,
            description=(
                "Named Trino connection from the server config. Empty = the "
                "default (sole/first) connection; must resolve to a 'trino' "
                "dialect connection."
            ),
        ),
    ) -> Any:
        """List Trino catalogs visible to the connected principal (``SHOW CATALOGS``)."""
        api = get_api()
        name = _require_dialect(api, connection or None, "trino")
        return await _invoke(partial(api.query, "SHOW CATALOGS", connection=name))

    @mcp.tool(tags={"trino"})
    async def sql_trino_schemas(
        params_json: str = Field(
            description='JSON of arguments: {"catalog": "lakehouse"}.',
        ),
        connection: str = Field(
            default="",
            max_length=128,
            description=(
                "Named Trino connection from the server config. Empty = the "
                "default (sole/first) connection; must resolve to a 'trino' "
                "dialect connection."
            ),
        ),
    ) -> Any:
        """List schemas (namespaces) within one Trino catalog (``SHOW SCHEMAS FROM``)."""
        p = _validate_params(TrinoSchemasInput, params_json)
        api = get_api()
        name = _require_dialect(api, connection or None, "trino")
        # Trino identifiers cannot be bound parameters; ``catalog`` is
        # restricted to ``^[A-Za-z_][A-Za-z0-9_]*$`` by TrinoSchemasInput, so
        # this interpolation carries no injection surface.
        sql = f"SHOW SCHEMAS FROM {p['catalog']}"
        return await _invoke(partial(api.query, sql, connection=name))

    @mcp.tool(tags={"trino"})
    async def sql_trino_queries(
        params_json: str = Field(
            default="{}",
            description=(
                'JSON of arguments (all optional): {"state": "RUNNING"}. '
                f"Always capped at {_TRINO_QUERIES_ROW_CAP} rows regardless "
                "of the server's configured max_rows."
            ),
        ),
        connection: str = Field(
            default="",
            max_length=128,
            description=(
                "Named Trino connection from the server config. Empty = the "
                "default (sole/first) connection; must resolve to a 'trino' "
                "dialect connection."
            ),
        ),
    ) -> Any:
        """Read recent Trino queries from ``system.runtime.queries`` (200-row cap)."""
        p = _validate_params(TrinoQueriesInput, params_json)
        api = get_api()
        name = _require_dialect(api, connection or None, "trino")
        if p.get("state"):
            sql = (
                'SELECT query_id, "user", state, created, query '
                "FROM system.runtime.queries WHERE state = :state "
                "ORDER BY created DESC"
            )
            params = {"state": p["state"]}
        else:
            sql = (
                'SELECT query_id, "user", state, created, query '
                "FROM system.runtime.queries ORDER BY created DESC"
            )
            params = {}
        return await _invoke(
            partial(
                api.query,
                sql,
                params=params,
                connection=name,
                max_rows=_TRINO_QUERIES_ROW_CAP,
            )
        )

    @mcp.tool(tags={"trino"})
    async def sql_trino_explain(
        params_json: str = Field(
            description=(
                'JSON of arguments: {"sql": "SELECT ...", "params": {...}, '
                '"timeout": 10}. Statement must be single, read-only '
                "(SELECT/WITH/EXPLAIN/SHOW/DESCRIBE/VALUES) — rejected by "
                "the same gate as sql_query."
            ),
        ),
        connection: str = Field(
            default="",
            max_length=128,
            description=(
                "Named Trino connection from the server config. Empty = the "
                "default (sole/first) connection; must resolve to a 'trino' "
                "dialect connection."
            ),
        ),
    ) -> Any:
        """Return Trino's query plan for a read-only statement (``EXPLAIN``)."""
        p = _validate_params(TrinoExplainInput, params_json)
        api = get_api()
        name = _require_dialect(api, connection or None, "trino")
        return await _invoke(
            partial(
                api.explain,
                p["sql"],
                params=p.get("params"),
                connection=name,
                timeout=p.get("timeout"),
            )
        )


def register_duckdb_tools(mcp: FastMCP) -> None:
    """Register the DuckDB Iceberg REST-catalog attach tool.

    Split from :func:`register_sql_trino_tools` so ``register_tool_surface``'s
    function-name-derived toggle env var is domain-accurate: Trino's four
    tools gate on ``SQL_TRINOTOOL``, DuckDB's one tool gates on
    ``DUCKDBTOOL`` — independently switchable.
    """

    @mcp.tool(tags={"duckdb"})
    async def sql_duckdb_attach_iceberg(
        params_json: str = Field(
            description=(
                'JSON of arguments: {"alias": "lakehouse_cat", '
                '"rest_uri": "http://<lakekeeper>/catalog", '
                '"warehouse": "lakehouse", "token": "<bearer JWT>"}. Runs '
                "the INSTALL/LOAD iceberg+httpfs bootstrap then ATTACHes the "
                "REST catalog. The token must be the calling principal's own "
                "credential — never an ambient service bypass."
            ),
        ),
        connection: str = Field(
            default="",
            max_length=128,
            description=(
                "Named DuckDB connection from the server config, whose "
                "configured database path/':memory:' hosts the attach. "
                "Empty = a bare in-process ':memory:' DuckDB (no "
                "pre-registered SQL_CONNECTIONS entry required)."
            ),
        ),
    ) -> Any:
        """Attach a DuckDB session to a live Iceberg REST catalog (Lakekeeper-shaped).

        Fails explicitly (typed error naming the failing step) rather than
        silently falling back to an unauthenticated or stale read —
        CONCEPT:SQ-OS.safety.allow-deny-classification.
        """
        p = _validate_params(DuckDbAttachIcebergInput, params_json)
        api = get_api()
        database = ":memory:"
        if connection:
            name = _require_dialect(api, connection, "duckdb")
            database = api.engine(name).url.database or ":memory:"

        def run_attach() -> dict[str, Any]:
            try:
                import duckdb
            except ImportError as exc:
                raise ImportError(
                    "The 'duckdb' dialect needs the 'duckdb'/'duckdb-engine' "
                    "drivers. Install with: pip install sql-mcp[duckdb]"
                ) from exc

            con = duckdb.connect(database)
            try:
                try:
                    con.execute("INSTALL iceberg")
                    con.execute("LOAD iceberg")
                    con.execute("INSTALL httpfs")
                    con.execute("LOAD httpfs")
                except duckdb.Error as exc:
                    raise RuntimeError(
                        f"DuckDB Iceberg/httpfs extension bootstrap failed: {exc}"
                    ) from exc

                secret_name = f"sql_mcp_iceberg_{p['alias']}"
                try:
                    con.execute(
                        f"CREATE OR REPLACE SECRET {secret_name} "
                        f"(TYPE ICEBERG, TOKEN '{p['token']}')"
                    )
                except duckdb.Error as exc:
                    raise RuntimeError(
                        f"Failed to register the Iceberg REST catalog secret: {exc}"
                    ) from exc

                try:
                    con.execute(
                        f"ATTACH '{p['warehouse']}' AS {p['alias']} "
                        f"(TYPE ICEBERG, ENDPOINT '{p['rest_uri']}', "
                        f"SECRET {secret_name})"
                    )
                except duckdb.Error as exc:
                    raise RuntimeError(
                        f"ATTACH against Iceberg REST catalog {p['rest_uri']!r} "
                        f"(warehouse {p['warehouse']!r}) failed: {exc}"
                    ) from exc

                try:
                    rows = con.execute(
                        "SELECT database_name, schema_name, table_name "
                        "FROM duckdb_tables() WHERE database_name = ?",
                        [p["alias"]],
                    ).fetchall()
                except duckdb.Error as exc:
                    raise RuntimeError(
                        f"ATTACH succeeded but listing tables in {p['alias']!r} "
                        f"failed: {exc}"
                    ) from exc

                return {
                    "attached": True,
                    "alias": p["alias"],
                    "warehouse": p["warehouse"],
                    "rest_uri": p["rest_uri"],
                    "tables": [
                        {"schema": schema, "table": table}
                        for _db, schema, table in rows
                    ],
                }
            finally:
                con.close()

        try:
            return await asyncio.wait_for(
                _invoke_external(run_attach),
                timeout=_DUCKDB_BOOTSTRAP_TIMEOUT_SECONDS,
            )
        except TimeoutError as exc:
            raise TimeoutError(
                "DuckDB Iceberg attach exceeded the "
                f"{_DUCKDB_BOOTSTRAP_TIMEOUT_SECONDS:g}s bootstrap timeout."
            ) from exc
