"""Action-dispatch MCP tools for sql-mcp (CONCEPT:SQ-OS.governance.sql-2, CONCEPT:SQ-OS.governance.action-routing-through-fastmcp).

Four action-dispatch tools — ``sql_query``, ``sql_execute``, ``sql_schema``, and
``sql_admin`` — route an ``action`` + ``params_json`` pair to the
:class:`~sql_mcp.api_client.Api` facade; ``sql_ingest_schema`` provides the fifth,
dedicated ingestion surface. The tools are thin shims: parameter parsing and
thread offloading only, no business logic. Every tool accepts an optional
``connection`` naming one of the configured connections (defaults to the
sole/first one).
"""

import asyncio
import concurrent.futures
import inspect
import json
import threading
from collections.abc import Callable
from functools import partial
from typing import Any, Literal

from fastmcp import FastMCP
from pydantic import Field, ValidationError

from sql_mcp.api.api_client_sql import asynchronous_sql_execution
from sql_mcp.auth import allow_kg_ingest, get_api
from sql_mcp.sql_input_models import (
    AdminInput,
    ExecuteInput,
    IngestInput,
    QueryInput,
    SchemaInput,
    ScriptInput,
    StrictInput,
)

_MAX_PARAMS_JSON_BYTES = 1_000_000
_MAX_JSON_DEPTH = 20
_MAX_JSON_ITEMS = 10_000
_MAX_VALIDATION_ERRORS = 20
_EXTERNAL_EXECUTOR = concurrent.futures.ThreadPoolExecutor(
    max_workers=4,
    thread_name_prefix="sql-mcp-external",
)
_EXTERNAL_SLOTS = threading.BoundedSemaphore(8)


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"Non-finite JSON number {value!r} is not allowed.")


def _parse_params_json(params_json: str) -> dict[str, Any]:
    """Decode a tool payload and require a JSON object."""
    if len(params_json.encode("utf-8")) > _MAX_PARAMS_JSON_BYTES:
        raise ValueError("'params_json' exceeds the 1000000-byte limit.")
    value = (
        json.loads(params_json, parse_constant=_reject_json_constant)
        if params_json
        else {}
    )
    if not isinstance(value, dict):
        raise ValueError("'params_json' must decode to a JSON object.")

    item_count = 0

    def inspect_value(item: Any, depth: int) -> None:
        nonlocal item_count
        if depth > _MAX_JSON_DEPTH:
            raise ValueError("'params_json' exceeds the maximum nesting depth.")
        if isinstance(item, dict):
            item_count += len(item)
            for nested in item.values():
                inspect_value(nested, depth + 1)
        elif isinstance(item, list):
            item_count += len(item)
            for nested in item:
                inspect_value(nested, depth + 1)
        if item_count > _MAX_JSON_ITEMS:
            raise ValueError("'params_json' contains too many values.")

    inspect_value(value, 0)
    return value


def _validate_params(model: type[StrictInput], params_json: str) -> dict[str, Any]:
    try:
        value = model.model_validate(_parse_params_json(params_json))
    except ValidationError as exc:
        details = exc.errors(include_url=False, include_context=False)
        errors = ", ".join(
            f"{'.'.join(str(part) for part in error['loc']) or '<root>'}:"
            f"{error['type']}"
            for error in details[:_MAX_VALIDATION_ERRORS]
        )
        if len(details) > _MAX_VALIDATION_ERRORS:
            errors += f", +{len(details) - _MAX_VALIDATION_ERRORS} more"
        raise ValueError(f"Invalid SQL tool parameters ({errors}).") from None
    return value.model_dump(by_alias=True, exclude_none=True)


async def _invoke(call: Callable[[], Any]) -> Any:
    """Submit SQL work once and await it without blocking the event loop."""
    with asynchronous_sql_execution():
        result = call()
    if inspect.isawaitable(result):
        return await result
    return result


async def _invoke_external(call: Callable[[], Any]) -> Any:
    """Await bounded non-SQL work without propagating transport context."""
    if not _EXTERNAL_SLOTS.acquire(blocking=False):
        raise RuntimeError("External dispatch capacity is exhausted; retry later.")
    try:
        future = _EXTERNAL_EXECUTOR.submit(call)
    except BaseException:
        _EXTERNAL_SLOTS.release()
        raise

    async def release_when_done() -> None:
        while not future.done():
            await asyncio.sleep(0.05)
        _EXTERNAL_SLOTS.release()

    try:
        while not future.done():
            await asyncio.sleep(0.01)
        return future.result()
    finally:
        if future.done():
            _EXTERNAL_SLOTS.release()
        else:
            asyncio.create_task(release_when_done())


def register_sql_tools(mcp: FastMCP) -> None:
    """Register the query, execute, schema, admin, and ingestion tools."""

    @mcp.tool(tags={"query"})
    async def sql_query(
        action: Literal["execute", "explain"] = Field(
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
            max_length=128,
            description=(
                "Named connection from the server config (see sql_admin "
                "'connections'). Empty = the default (sole/first) connection."
            ),
        ),
    ) -> Any:
        """Run read-only SQL with row cap, timeout, and column metadata."""
        p = _validate_params(QueryInput, params_json)
        api = get_api()
        if action == "execute":
            return await _invoke(
                partial(
                    api.query,
                    p["sql"],
                    params=p.get("params"),
                    connection=connection or None,
                    max_rows=p.get("max_rows"),
                    timeout=p.get("timeout"),
                )
            )
        if action == "explain":
            return await _invoke(
                partial(
                    api.explain,
                    p["sql"],
                    params=p.get("params"),
                    connection=connection or None,
                    timeout=p.get("timeout"),
                )
            )
        raise ValueError(f"Unknown query action: {action!r}.")

    @mcp.tool(tags={"execute"})
    async def sql_execute(
        action: Literal["execute", "script"] = Field(
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
            max_length=128,
            description=(
                "Named connection from the server config. Empty = the default "
                "(sole/first) connection."
            ),
        ),
    ) -> Any:
        """Run DML/DDL in transactions (gated by SQL_ALLOW_WRITES)."""
        api = get_api()
        if action == "execute":
            p = _validate_params(ExecuteInput, params_json)
            return await _invoke(
                partial(
                    api.execute,
                    p["sql"],
                    params=p.get("params"),
                    connection=connection or None,
                    timeout=p.get("timeout"),
                    max_rows=p.get("max_rows"),
                )
            )
        if action == "script":
            p = _validate_params(ScriptInput, params_json)
            return await _invoke(
                partial(
                    api.execute_script,
                    p["statements"],
                    connection=connection or None,
                    timeout=p.get("timeout"),
                )
            )
        raise ValueError(f"Unknown execute action: {action!r}.")

    @mcp.tool(tags={"schema"})
    async def sql_schema(
        action: Literal[
            "schemas",
            "tables",
            "views",
            "columns",
            "indexes",
            "foreign_keys",
            "constraints",
            "ddl",
            "sample",
            "materialized_views",
            "sequences",
            "view_definition",
            "table_comment",
            "catalog",
        ] = Field(
            description=(
                "Schema action. One of: 'schemas' (list schema names), "
                "'tables', 'views' (list names, optional schema), 'columns', "
                "'indexes', 'foreign_keys', 'constraints' (describe a table), "
                "'ddl' (reflect CREATE TABLE DDL), 'sample' (preview rows), "
                "'materialized_views', 'sequences', 'view_definition', "
                "'table_comment', and bounded 'catalog'."
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
            max_length=128,
            description=(
                "Named connection from the server config. Empty = the default "
                "(sole/first) connection."
            ),
        ),
    ) -> Any:
        """Inspect schemas, tables, views, columns, indexes, FKs, and DDL."""
        p = _validate_params(SchemaInput, params_json)
        api = get_api()
        conn = connection or None
        schema = p.get("schema")
        table_actions = {
            "columns",
            "indexes",
            "foreign_keys",
            "constraints",
            "ddl",
            "sample",
            "table_comment",
        }
        if action in table_actions and "table" not in p:
            raise ValueError(f"Schema action {action!r} requires 'table'.")
        if action == "view_definition" and "view" not in p:
            raise ValueError("Schema action 'view_definition' requires 'view'.")
        if action == "schemas":
            return await _invoke(
                partial(
                    api.list_schemas,
                    connection=conn,
                    limit=p.get("limit"),
                    offset=p.get("offset", 0),
                )
            )
        if action == "tables":
            return await _invoke(
                partial(
                    api.list_tables,
                    schema=schema,
                    connection=conn,
                    limit=p.get("limit"),
                    offset=p.get("offset", 0),
                )
            )
        if action == "views":
            return await _invoke(
                partial(
                    api.list_views,
                    schema=schema,
                    connection=conn,
                    limit=p.get("limit"),
                    offset=p.get("offset", 0),
                )
            )
        if action == "materialized_views":
            return await _invoke(
                partial(
                    api.list_materialized_views,
                    schema=schema,
                    connection=conn,
                    limit=p.get("limit"),
                    offset=p.get("offset", 0),
                )
            )
        if action == "sequences":
            return await _invoke(
                partial(
                    api.list_sequences,
                    schema=schema,
                    connection=conn,
                    limit=p.get("limit"),
                    offset=p.get("offset", 0),
                )
            )
        if action == "columns":
            return await _invoke(
                partial(api.list_columns, p["table"], schema=schema, connection=conn)
            )
        if action == "indexes":
            return await _invoke(
                partial(api.list_indexes, p["table"], schema=schema, connection=conn)
            )
        if action == "foreign_keys":
            return await _invoke(
                partial(
                    api.list_foreign_keys,
                    p["table"],
                    schema=schema,
                    connection=conn,
                )
            )
        if action == "constraints":
            return await _invoke(
                partial(
                    api.list_constraints,
                    p["table"],
                    schema=schema,
                    connection=conn,
                )
            )
        if action == "ddl":
            return await _invoke(
                partial(api.table_ddl, p["table"], schema=schema, connection=conn)
            )
        if action == "sample":
            return await _invoke(
                partial(
                    api.sample_rows,
                    p["table"],
                    schema=schema,
                    limit=p.get("limit", 10),
                    connection=conn,
                )
            )
        if action == "view_definition":
            return await _invoke(
                partial(
                    api.view_definition,
                    p["view"],
                    schema=schema,
                    connection=conn,
                )
            )
        if action == "table_comment":
            return await _invoke(
                partial(
                    api.table_comment,
                    p["table"],
                    schema=schema,
                    connection=conn,
                )
            )
        if action == "catalog":
            return await _invoke(
                partial(
                    api.schema_catalog,
                    schema=schema,
                    connection=conn,
                    max_objects=p.get("max_objects"),
                    include_views=p.get("include_views", True),
                    timeout=p.get("timeout"),
                )
            )
        raise ValueError(f"Unknown schema action: {action!r}.")

    @mcp.tool(tags={"admin"})
    async def sql_admin(
        action: Literal[
            "ping",
            "ping_all",
            "version",
            "active_connections",
            "connections",
            "dialects",
            "pool_status",
            "capabilities",
        ] = Field(
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
            max_length=128,
            description=(
                "Named connection from the server config. Empty = the default "
                "(sole/first) connection."
            ),
        ),
    ) -> Any:
        """Connection health, server version, sessions, and registry info."""
        _validate_params(AdminInput, params_json)
        conn = connection or None
        api = get_api()
        if action == "ping":
            return await _invoke(partial(api.ping, connection=conn))
        if action == "ping_all":
            results: list[dict[str, Any]] = []
            for name in api.connection_names():
                try:
                    results.append(await _invoke(partial(api.ping, connection=name)))
                except Exception as exc:
                    results.append(
                        {
                            "connection": name,
                            "ok": False,
                            "error": type(exc).__name__,
                        }
                    )
            return results
        if action == "version":
            return await _invoke(
                partial(api.server_version, connection=conn)
            )
        if action == "active_connections":
            return await _invoke(
                partial(api.active_connections, connection=conn)
            )
        if action == "connections":
            return await _invoke(api.describe_connections)
        if action == "pool_status":
            return await _invoke(partial(api.pool_status, connection=conn))
        if action == "capabilities":
            return await _invoke(partial(api.capabilities, connection=conn))
        if action == "dialects":
            from sql_mcp.dialects import DIALECTS, driver_available

            def describe_dialects() -> list[dict[str, Any]]:
                return [
                    {
                        "dialect": spec.name,
                        "scheme": spec.sqlalchemy_scheme,
                        "extra": spec.extra,
                        "driver_installed": driver_available(spec),
                    }
                    for spec in DIALECTS.values()
                ]

            return await _invoke(describe_dialects)
        raise ValueError(f"Unknown admin action: {action!r}.")

    @mcp.tool(tags={"ingest"})
    async def sql_ingest_schema(
        params_json: str = Field(
            default="{}",
            description=(
                "JSON of arguments. All optional: "
                '{"schema": "public", "include_views": true, '
                '"include_indexes": true}. Omit "schema" to reflect the '
                "connection's default schema."
            ),
        ),
        connection: str = Field(
            default="",
            max_length=128,
            description=(
                "Named connection from the server config. Empty = the default "
                "(sole/first) connection."
            ),
        ),
    ) -> Any:
        """Reflect a connection's schema and ingest it into the knowledge graph.

        Walks tables, columns, foreign keys, indexes, and views via the SQL
        client and pushes them into epistemic-graph as typed :DatabaseSchema /
        :DatabaseTable / :DatabaseColumn / :DatabaseView / :DatabaseIndex nodes
        (with :hasTable / :hasColumn / :hasView / :hasIndex / :referencesTable
        links). Native ingestion is atomic and fails closed when the graph engine
        is unavailable. CONCEPT:AU-KG.ingest.enterprise-source-extractor.
        """
        from sql_mcp.kg_ingest import catalog_to_entities, ingest_entities

        p = _validate_params(IngestInput, params_json)
        if not allow_kg_ingest():
            raise PermissionError(
                "Epistemic Graph ingestion is disabled. Start the server with "
                "SQL_ALLOW_KG_INGEST=True to enable this external write path."
            )
        api = get_api()
        conn = connection or None
        catalog = await _invoke(
            partial(
                api.schema_catalog,
                connection=conn,
                schema=p.get("schema"),
                include_views=p.get("include_views", True),
                max_objects=min(p.get("max_objects", 5_000), api.max_rows),
            )
        )
        entities, relationships = catalog_to_entities(
            catalog,
            include_indexes=p.get("include_indexes", True),
            max_objects=p.get("max_objects", 5_000),
        )
        result = await _invoke_external(
            partial(ingest_entities, entities, relationships)
        )
        return {
            "connection": catalog["connection"],
            "ingested": result,
            "source_truncated": bool(catalog.get("truncated")),
        }
