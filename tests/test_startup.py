"""Server startup: get_mcp_instance builds, registers tools, honors SQLTOOL."""

import pytest

pytest.importorskip("agent_utilities.mcp_utilities")

from fastmcp import Client  # noqa: E402

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
