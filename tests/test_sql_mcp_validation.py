"""MCP tool layer: one typed tool per operation, served through a FastMCP client."""

import json
import threading

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError
from mcp.shared.exceptions import MCPError
from scion_sdk.connector import build_server
from sqlalchemy import text

from sql_mcp import auth
from tests.conftest import SEED_STATEMENTS


@pytest.fixture
def mcp(monkeypatch):
    """The served MCP server wired to a seeded in-memory SQLite default connection."""
    monkeypatch.setenv(
        "SQL_CONNECTIONS",
        json.dumps(
            {
                "primary": "sqlite+pysqlite:///:memory:",
                "analytics": "sqlite+pysqlite:///:memory:",
            }
        ),
    )
    monkeypatch.delenv("SQL_ALLOW_WRITES", raising=False)
    monkeypatch.delenv("SQL_URL", raising=False)
    auth.reset_api()
    api = auth.get_api()
    with api.engine("primary").begin() as conn:
        for stmt in SEED_STATEMENTS:
            conn.execute(text(stmt))
    _, server = build_server(
        "sql_mcp", command_args=["--transport", "stdio", "--auth-type", "none"]
    )
    yield server
    auth.reset_api()


def tool_payload(result):
    """Decode a CallToolResult into plain data."""
    data = result.data
    if data is None:
        if not result.content:
            return []
        try:
            return json.loads(result.content[0].text)
        except json.JSONDecodeError:
            return result.content[0].text
    if isinstance(data, dict) and set(data) == {"result"}:
        return data["result"]
    return data


async def call(mcp, tool, **arguments):
    async with Client(mcp) as client:
        return await client.call_tool(tool, arguments)


async def test_operation_tools_are_served_and_plumbing_is_not(mcp):
    async with Client(mcp) as client:
        names = {tool.name for tool in await client.list_tools()}
    assert {
        "sql_query",
        "sql_explain",
        "sql_execute",
        "sql_execute_script",
        "sql_list_tables",
        "sql_ping",
        "sql_list_dialects",
        "sql_ingest_schema",
    } <= names
    assert not {"sql_engine", "sql_dispose", "sql_dialect_spec"} & names
    assert not {"sql_schema", "sql_admin"} & names


async def test_no_served_tool_takes_an_action_argument(mcp):
    async with Client(mcp) as client:
        for tool in await client.list_tools():
            assert "action" not in tool.input_schema.get("properties", {}), tool.name
            assert "params_json" not in tool.input_schema.get("properties", {}), (
                tool.name
            )


async def test_query_execute_returns_envelope(mcp):
    result = await call(
        mcp,
        "sql_query",
        sql="SELECT id, name FROM users WHERE id = :id",
        params={"id": 1},
    )
    payload = tool_payload(result)
    assert payload["rows"] == [{"id": 1, "name": "ada"}]
    assert payload["truncated"] is False
    assert [c["name"] for c in payload["columns"]] == ["id", "name"]


async def test_query_explain(mcp):
    result = await call(mcp, "sql_explain", sql="SELECT * FROM users WHERE id = 1")
    assert tool_payload(result)["row_count"] >= 1


async def test_query_rejects_write_statements(mcp):
    with pytest.raises((ToolError, MCPError), match="read-only"):
        await call(mcp, "sql_query", sql="DELETE FROM users")


async def test_sql_reflection_runs_off_loop_kg_ingest_runs_on_loop(mcp, monkeypatch):
    """Reflection offloads to a worker thread; KG ingest awaits on the event loop."""
    monkeypatch.setenv("SQL_ALLOW_KG_INGEST", "True")
    event_loop_thread = threading.get_ident()
    reflection_threads = []
    ingest_threads = []
    api = auth.get_api()
    reflection = api._reflection

    def recording_reflection(connection, operation, timeout=None):
        def recorded_operation(inspector):
            reflection_threads.append(threading.get_ident())
            return operation(inspector)

        return reflection(connection, recorded_operation, timeout)

    async def recording_ingest_entities(*args, **kwargs):
        ingest_threads.append(threading.get_ident())
        return {"nodes": 0, "edges": 0}

    monkeypatch.setattr(api, "_reflection", recording_reflection)
    monkeypatch.setattr("sql_mcp.kg_ingest.ingest_entities", recording_ingest_entities)

    await call(mcp, "sql_list_tables")
    await call(mcp, "sql_ingest_schema", connection="primary")

    assert len(reflection_threads) == 1
    assert reflection_threads[0] != event_loop_thread
    assert ingest_threads == [event_loop_thread]


async def test_kg_ingest_is_disabled_by_default(mcp):
    with pytest.raises((ToolError, MCPError), match="SQL_ALLOW_KG_INGEST"):
        await call(mcp, "sql_ingest_schema", connection="primary")


async def test_execute_blocked_by_default(mcp):
    with pytest.raises((ToolError, MCPError), match="SQL_ALLOW_WRITES"):
        await call(
            mcp,
            "sql_execute",
            sql="INSERT INTO users (id, name) VALUES (9, 'eve')",
        )


async def test_execute_allowed_when_writes_enabled(mcp, monkeypatch):
    api = auth.get_api()
    monkeypatch.setattr(api, "allow_writes", True)
    monkeypatch.setattr(api, "_writable_connections", frozenset({"primary"}))
    result = await call(
        mcp,
        "sql_execute",
        sql="INSERT INTO users (id, name) VALUES (:id, :name)",
        params={"id": 9, "name": "eve"},
    )
    assert tool_payload(result)["rowcount"] == 1


async def test_execute_script(mcp, monkeypatch):
    api = auth.get_api()
    monkeypatch.setattr(api, "allow_writes", True)
    monkeypatch.setattr(api, "_writable_connections", frozenset({"primary"}))
    result = await call(
        mcp,
        "sql_execute_script",
        statements=[
            "CREATE TABLE notes (id INTEGER PRIMARY KEY, body TEXT)",
            "INSERT INTO notes (id, body) VALUES (1, 'hi')",
        ],
    )
    assert tool_payload(result)["statements"] == 2


async def test_execute_script_binds_values(mcp, monkeypatch):
    api = auth.get_api()
    monkeypatch.setattr(api, "allow_writes", True)
    monkeypatch.setattr(api, "_writable_connections", frozenset({"primary"}))
    await call(
        mcp,
        "sql_execute_script",
        statements=[
            {
                "sql": "INSERT INTO users (id, name) VALUES (:id, :name)",
                "params": {"id": 12, "name": "mary"},
            }
        ],
    )
    result = await call(
        mcp,
        "sql_query",
        sql="SELECT name FROM users WHERE id = :id",
        params={"id": 12},
    )
    assert tool_payload(result)["rows"] == [{"name": "mary"}]


async def test_schema_tools(mcp):
    assert sorted(tool_payload(await call(mcp, "sql_list_tables"))) == [
        "orders",
        "users",
    ]
    assert tool_payload(await call(mcp, "sql_list_views")) == ["user_emails"]
    columns = tool_payload(await call(mcp, "sql_list_columns", table="users"))
    assert {c["name"] for c in columns} == {"id", "name", "email"}
    fks = tool_payload(await call(mcp, "sql_list_foreign_keys", table="orders"))
    assert fks[0]["referred_table"] == "users"
    sample = tool_payload(await call(mcp, "sql_sample_rows", table="users", limit=2))
    assert sample["row_count"] == 2
    ddl = tool_payload(await call(mcp, "sql_table_ddl", table="users"))
    assert "CREATE TABLE" in ddl.upper()
    constraints = tool_payload(await call(mcp, "sql_list_constraints", table="users"))
    assert constraints["primary_key"]["columns"] == ["id"]
    definition = tool_payload(
        await call(mcp, "sql_view_definition", view="user_emails")
    )
    assert "SELECT" in definition.upper()
    catalog = tool_payload(await call(mcp, "sql_schema_catalog", max_objects=1))
    assert catalog["object_count"] == 1
    indexes = tool_payload(await call(mcp, "sql_list_indexes", table="users"))
    assert any(i["name"] == "ix_users_name" for i in indexes)
    assert tool_payload(await call(mcp, "sql_list_materialized_views")) == []
    assert tool_payload(await call(mcp, "sql_list_sequences")) == []
    comment = tool_payload(await call(mcp, "sql_table_comment", table="users"))
    assert "text" in comment
    assert isinstance(tool_payload(await call(mcp, "sql_list_schemas")), list)


async def test_connection_param_routes_to_named_connection(mcp):
    assert (
        tool_payload(await call(mcp, "sql_list_tables", connection="analytics")) == []
    )
    with pytest.raises((ToolError, MCPError), match="Unknown SQL connection"):
        await call(mcp, "sql_query", sql="SELECT 1", connection="bogus")


async def test_admin_tools(mcp):
    ping = tool_payload(await call(mcp, "sql_ping"))
    assert ping["ok"] is True and ping["connection"] == "primary"
    version = tool_payload(await call(mcp, "sql_server_version"))
    assert version["dialect"] == "sqlite"
    connections = tool_payload(await call(mcp, "sql_describe_connections"))
    assert [c["name"] for c in connections] == ["primary", "analytics"]
    dialects = tool_payload(await call(mcp, "sql_list_dialects"))
    assert {d["dialect"] for d in dialects} == {
        "sqlite",
        "postgres",
        "mysql",
        "mssql",
        "oracle",
    }
    sqlite_entry = next(d for d in dialects if d["dialect"] == "sqlite")
    assert sqlite_entry["driver_installed"] is True
    capabilities = tool_payload(await call(mcp, "sql_capabilities"))
    assert capabilities["dialect"] == "sqlite"
    pool = tool_payload(await call(mcp, "sql_pool_status"))
    assert pool["pool"] == "StaticPool"


async def test_ping_all_reports_every_connection(mcp):
    results = tool_payload(await call(mcp, "sql_ping_all"))
    assert {r["connection"] for r in results} == {"primary", "analytics"}
    assert all(r["ok"] is True for r in results)


async def test_active_connections_reports_unsupported_on_sqlite(mcp):
    result = tool_payload(await call(mcp, "sql_active_connections"))
    assert result["supported"] is False
