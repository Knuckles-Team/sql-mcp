"""Server startup: get_mcp_instance builds, registers tools, honors SQLTOOL."""

import json

import pytest

pytest.importorskip("agent_connector_sdk.mcp.action_dispatch")

from fastmcp import Client  # noqa: E402

from sql_mcp import auth  # noqa: E402
from agent_connector_sdk.connector import build_server  # noqa: E402


async def list_tool_names(mcp) -> set[str]:
    async with Client(mcp) as client:
        return {tool.name for tool in await client.list_tools()}


async def test_get_mcp_instance_registers_sql_tools(monkeypatch):
    monkeypatch.setenv("SQL_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setattr("sys.argv", ["sql-mcp"])
    _, mcp = build_server("sql_mcp", command_args=[])
    names = await list_tool_names(mcp)
    assert {"sql_query", "sql_execute", "sql_ingest_schema"} <= names
    assert not {"sql_schema", "sql_admin"} & names


async def test_sqltool_flag_disables_registration(monkeypatch):
    monkeypatch.setenv("SQLTOOL", "False")
    monkeypatch.setattr("sys.argv", ["sql-mcp"])
    _, mcp = build_server("sql_mcp", command_args=[])
    assert "sql_ingest_schema" not in await list_tool_names(mcp)


async def test_operational_routes_expose_status_only(monkeypatch):
    monkeypatch.setenv("SQL_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setattr("sys.argv", ["sql-mcp"])
    auth.reset_api()
    _, mcp = build_server("sql_mcp", command_args=[])
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
