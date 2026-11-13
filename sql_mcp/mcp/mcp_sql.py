"""Non-client MCP tools for sql-mcp.

Every database operation (query, execute, schema reflection, connection admin) is
served as its own typed tool derived from the ``OperationApi`` facade. This module
holds the two tools that are not client methods: the dialect catalogue and the
knowledge-graph schema ingest. Both accept an optional ``connection`` naming one
of the configured connections (default: the sole/first one).
"""

import inspect
from collections.abc import Callable
from functools import partial
from typing import Any

from fastmcp import FastMCP
from pydantic import Field

from sql_mcp.api.api_client_sql import asynchronous_sql_execution
from sql_mcp.auth import allow_kg_ingest, get_api


async def _invoke(call: Callable[[], Any]) -> Any:
    """Submit SQL work once and await it without blocking the event loop."""
    with asynchronous_sql_execution():
        result = call()
    if inspect.isawaitable(result):
        return await result
    return result


def _describe_dialects() -> list[dict[str, Any]]:
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


def register_sql_tools(mcp: FastMCP) -> None:
    """Register the dialect catalogue and the schema ingest tool."""

    @mcp.tool(tags={"admin"})
    async def sql_list_dialects() -> list[dict[str, Any]]:
        """List the supported SQL dialects and whether each driver is installed."""
        return _describe_dialects()

    @mcp.tool(tags={"ingest"})
    async def sql_ingest_schema(
        schema: str | None = Field(
            default=None,
            max_length=512,
            description="Schema to reflect; omit for the connection's default.",
        ),
        include_views: bool = Field(default=True, description="Include views."),
        include_indexes: bool = Field(default=True, description="Include indexes."),
        max_objects: int = Field(
            default=5_000, ge=1, le=5_000, description="Cap on reflected objects."
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
        client and pushes them into medulla as typed :DatabaseSchema /
        :DatabaseTable / :DatabaseColumn / :DatabaseView / :DatabaseIndex nodes
        (with :hasTable / :hasColumn / :hasView / :hasIndex / :referencesTable
        links). Native ingestion is atomic and fails closed when the graph engine
        is unavailable.
        """
        from sql_mcp.kg_ingest import catalog_to_entities, ingest_entities

        if not allow_kg_ingest():
            raise PermissionError(
                "Medulla ingestion is disabled. Start the server with "
                "SQL_ALLOW_KG_INGEST=True to enable this external write path."
            )
        api = get_api()
        catalog = await _invoke(
            partial(
                api.schema_catalog,
                connection=connection or None,
                schema=schema,
                include_views=include_views,
                max_objects=min(max_objects, api.max_rows),
            )
        )
        entities, relationships = catalog_to_entities(
            catalog,
            include_indexes=include_indexes,
            max_objects=max_objects,
        )
        # ingest_entities is async (scion_sdk.ingest does its own non-blocking
        # I/O), so it runs directly on the event loop.
        result = await ingest_entities(entities, relationships)
        return {
            "connection": catalog["connection"],
            "ingested": result,
            "source_truncated": bool(catalog.get("truncated")),
        }
