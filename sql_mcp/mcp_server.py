"""Main FastMCP server and tool registration for sql-mcp."""

import sys
from typing import Any

from agent_utilities.core.config import load_config
from agent_utilities.mcp.server_factory import create_mcp_server
from agent_utilities.mcp.verbose_tools import register_tool_surface
from fastmcp.utilities.logging import get_logger
from starlette.requests import Request
from starlette.responses import JSONResponse

from sql_mcp.api_client import Api
from sql_mcp.auth import get_api
from sql_mcp.mcp.mcp_sql import register_sql_tools

__version__ = "2.0.0"
logger = get_logger(name="sql_mcp")


def get_mcp_instance() -> tuple[Any, ...]:
    load_config()
    args, mcp, middlewares = create_mcp_server(
        name="SQL MCP",
        version=__version__,
        instructions=(
            "Generic SQL database MCP Server - read-only queries, gated "
            "DML/DDL, schema reflection, and connection admin over "
            "SQLAlchemy 2.x Core (SQLite, Postgres, MySQL/MariaDB, MSSQL, "
            "Oracle) with named multi-connection support."
        ),
    )

    @mcp.custom_route("/ready", methods=["GET"])
    async def readiness_check(request: Request) -> JSONResponse:
        try:
            get_api()
        except Exception:
            return JSONResponse({"status": "unavailable"}, status_code=503)
        return JSONResponse({"status": "ready"})

    register_tool_surface(
        mcp,
        client_cls=Api,
        get_client=get_api,
        service="sql-mcp",
        registrars=[register_sql_tools],
    )

    for mw in middlewares:
        mcp.add_middleware(mw)
    return mcp, args, middlewares


def mcp_server() -> None:
    mcp, args, middlewares = get_mcp_instance()
    print(f"SQL MCP v{__version__}", file=sys.stderr)
    if args.transport == "stdio":
        mcp.run(transport="stdio")
    elif args.transport == "streamable-http":
        mcp.run(transport="streamable-http", host=args.host, port=args.port)
    elif args.transport == "sse":
        mcp.run(transport="sse", host=args.host, port=args.port)
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    mcp_server()
