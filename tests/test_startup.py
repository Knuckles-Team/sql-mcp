"""Server startup: get_mcp_instance builds, registers tools, honors SQLTOOL."""

import json

import pytest

pytest.importorskip("agent_utilities.mcp.action_dispatch")

from fastmcp import Client  # noqa: E402

from sql_mcp import auth  # noqa: E402
from sql_mcp.mcp_server import get_mcp_instance  # noqa: E402


async def list_tool_names(mcp) -> set[str]:
    async with Client(mcp) as client:
        return {tool.name for tool in await client.list_tools()}


async def test_get_mcp_instance_registers_sql_tools(monkeypatch):
    monkeypatch.setenv("SQL_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setattr("sys.argv", ["sql-mcp"])
    mcp, args, middlewares = get_mcp_instance()
    assert {"sql_query", "sql_execute", "sql_schema", "sql_admin"} <= (
        await list_tool_names(mcp)
    )


async def test_sqltool_flag_disables_registration(monkeypatch):
    monkeypatch.setenv("SQLTOOL", "False")
    monkeypatch.setattr("sys.argv", ["sql-mcp"])
    mcp, args, middlewares = get_mcp_instance()
    assert "sql_query" not in await list_tool_names(mcp)


async def test_operational_routes_expose_status_only(monkeypatch):
    monkeypatch.setenv("SQL_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setattr("sys.argv", ["sql-mcp"])
    auth.reset_api()
    mcp, _, _ = get_mcp_instance()
    routes = {
        route.path: route.endpoint
        for route in mcp._additional_http_routes
        if route.path in {"/health", "/ready"}
    }

    health = await routes["/health"](None)
    ready = await routes["/ready"](None)

    assert health.status_code == 200
    assert json.loads(health.body) == {"status": "ok"}
    assert ready.status_code == 200
    assert json.loads(ready.body) == {"status": "ready"}
    auth.reset_api()


async def test_readiness_fails_closed_without_details(monkeypatch):
    monkeypatch.setattr("sys.argv", ["sql-mcp"])
    monkeypatch.setattr(
        "sql_mcp.mcp_server.get_api",
        lambda: (_ for _ in ()).throw(RuntimeError("private failure detail")),
    )
    mcp, _, _ = get_mcp_instance()
    endpoint = next(
        route.endpoint for route in mcp._additional_http_routes if route.path == "/ready"
    )

    response = await endpoint(None)

    assert response.status_code == 503
    assert json.loads(response.body) == {"status": "unavailable"}
    assert b"private failure detail" not in response.body
