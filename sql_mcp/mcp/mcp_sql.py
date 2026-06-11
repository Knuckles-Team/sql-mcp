"""Action-dispatch MCP tools for sql-mcp (CONCEPT:SQL-1.0, CONCEPT:SQL-1.5).

Four consolidated tools — ``sql_query``, ``sql_execute``, ``sql_schema``, and
``sql_admin`` — each routing an ``action`` + ``params_json`` pair to the
:class:`~sql_mcp.api_client.Api` facade. The tools are thin shims: parameter
parsing only, no business logic. Every tool accepts an optional ``connection``
naming one of the configured connections (defaults to the sole/first one).
"""

import json
from typing import Any

from fastmcp import FastMCP
from pydantic import Field

from sql_mcp.auth import get_api


def register_sql_tools(mcp: FastMCP) -> None:
    """Register the query, execute, schema, and admin tools."""

    @mcp.tool(tags={"query"})
    async def sql_query(
        action: str = Field(
            description=(
                "Query action. One of: 'execute' (run a read-only SELECT/CTE "
                "with bound parameters), 'explain' (return the dialect's query "
                "plan for a read-only statement)."
            )
        ),
        params_json: str = Field(
            default="{}",
            description=(
                "JSON of arguments. execute: "
                '{"sql": "SELECT * FROM users WHERE id = :id", '
                '"params": {"id": 1}, "max_rows": 100, "timeout": 10}. '
                'explain: {"sql": "SELECT ...", "params": {...}}. '
                "Statements must be single, read-only (SELECT/WITH/EXPLAIN/"
                "SHOW/DESCRIBE/PRAGMA/VALUES), and use :name bound parameters "
                "— never inline values. max_rows is clamped to the server cap."
            ),
        ),
        connection: str = Field(
            default="",
            description=(
                "Named connection from the server config (see sql_admin "
                "'connections'). Empty = the default (sole/first) connection."
            ),
        ),
    ) -> Any:
        """Run read-only SQL with row cap, timeout, and column metadata."""
        api = get_api()
        p = json.loads(params_json) if params_json else {}
        if action == "execute":
            return api.query(
                p["sql"],
                params=p.get("params"),
                connection=connection or None,
                max_rows=p.get("max_rows"),
                timeout=p.get("timeout"),
            )
        if action == "explain":
            return api.explain(
                p["sql"],
                params=p.get("params"),
                connection=connection or None,
                timeout=p.get("timeout"),
            )
        raise ValueError(f"Unknown query action: {action!r}.")

    @mcp.tool(tags={"execute"})
    async def sql_execute(
        action: str = Field(
            description=(
                "Write action. One of: 'execute' (one DML/DDL statement in a "
                "transaction; params may be a dict or a list of dicts for "
                "executemany), 'script' (a list of statements in ONE "
                "all-or-nothing transaction). Requires the server to run with "
                "SQL_ALLOW_WRITES=True — the default is read-only."
            )
        ),
        params_json: str = Field(
            default="{}",
            description=(
                "JSON of arguments. execute: "
                '{"sql": "INSERT INTO t (a) VALUES (:a)", "params": {"a": 1}} '
                'or "params": [{"a": 1}, {"a": 2}] for executemany. '
                'script: {"statements": ["CREATE TABLE ...", "INSERT ..."]}. '
                "Optional 'timeout' (seconds) on both. Returns affected-row "
                "counts."
            ),
        ),
        connection: str = Field(
            default="",
            description=(
                "Named connection from the server config. Empty = the default "
                "(sole/first) connection."
            ),
        ),
    ) -> Any:
        """Run DML/DDL in transactions (gated by SQL_ALLOW_WRITES)."""
        api = get_api()
        p = json.loads(params_json) if params_json else {}
        if action == "execute":
            return api.execute(
                p["sql"],
                params=p.get("params"),
                connection=connection or None,
                timeout=p.get("timeout"),
            )
        if action == "script":
            return api.execute_script(
                p["statements"],
                connection=connection or None,
                timeout=p.get("timeout"),
            )
        raise ValueError(f"Unknown execute action: {action!r}.")

    @mcp.tool(tags={"schema"})
    async def sql_schema(
        action: str = Field(
            description=(
                "Schema action. One of: 'schemas' (list schema names), "
                "'tables', 'views' (list names, optional schema), 'columns', "
                "'indexes', 'foreign_keys' (describe a table), 'ddl' (reflect "
                "CREATE TABLE DDL), 'sample' (preview rows with a limit)."
            )
        ),
        params_json: str = Field(
            default="{}",
            description=(
                "JSON of arguments. schemas: {}. tables/views: "
                '{"schema": "public"} (optional). '
                'columns/indexes/foreign_keys/ddl: {"table": "users", '
                '"schema": "public"}. sample: {"table": "users", '
                '"limit": 10, "schema": "public"} (limit clamped to the '
                "server row cap)."
            ),
        ),
        connection: str = Field(
            default="",
            description=(
                "Named connection from the server config. Empty = the default "
                "(sole/first) connection."
            ),
        ),
    ) -> Any:
        """Inspect schemas, tables, views, columns, indexes, FKs, and DDL."""
        api = get_api()
        p = json.loads(params_json) if params_json else {}
        conn = connection or None
        schema = p.get("schema")
        if action == "schemas":
            return api.list_schemas(connection=conn)
        if action == "tables":
            return api.list_tables(schema=schema, connection=conn)
        if action == "views":
            return api.list_views(schema=schema, connection=conn)
        if action == "columns":
            return api.list_columns(p["table"], schema=schema, connection=conn)
        if action == "indexes":
            return api.list_indexes(p["table"], schema=schema, connection=conn)
        if action == "foreign_keys":
            return api.list_foreign_keys(p["table"], schema=schema, connection=conn)
        if action == "ddl":
            return api.table_ddl(p["table"], schema=schema, connection=conn)
        if action == "sample":
            return api.sample_rows(
                p["table"],
                schema=schema,
                limit=p.get("limit", 10),
                connection=conn,
            )
        raise ValueError(f"Unknown schema action: {action!r}.")

    @mcp.tool(tags={"admin"})
    async def sql_admin(
        action: str = Field(
            description=(
                "Admin action. One of: 'ping' (connection test + latency), "
                "'version' (server version), 'active_connections' (server "
                "sessions, where the dialect supports it), 'connections' "
                "(list configured connections, passwords redacted), "
                "'dialects' (supported dialects + driver availability)."
            )
        ),
        params_json: str = Field(
            default="{}",
            description="JSON of arguments. All admin actions take {}.",
        ),
        connection: str = Field(
            default="",
            description=(
                "Named connection from the server config. Empty = the default "
                "(sole/first) connection."
            ),
        ),
    ) -> Any:
        """Connection health, server version, sessions, and registry info."""
        api = get_api()
        if params_json:
            json.loads(params_json)  # validate early; admin actions take {}
        conn = connection or None
        if action == "ping":
            return api.ping(connection=conn)
        if action == "version":
            return api.server_version(connection=conn)
        if action == "active_connections":
            return api.active_connections(connection=conn)
        if action == "connections":
            return api.describe_connections()
        if action == "dialects":
            from sql_mcp.dialects import DIALECTS, driver_available

            return [
                {
                    "dialect": spec.name,
                    "scheme": spec.sqlalchemy_scheme,
                    "extra": spec.extra,
                    "driver_installed": driver_available(spec),
                }
                for spec in DIALECTS.values()
            ]
        raise ValueError(f"Unknown admin action: {action!r}.")
