"""MCP tool layer (CONCEPT:SQ-OS.governance.action-routing-through-fastmcp): action routing through a FastMCP client."""

import json
import threading

import pytest
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError
from sqlalchemy import text

from sql_mcp import auth
from sql_mcp.mcp.mcp_sql import register_sql_tools
from tests.conftest import SEED_STATEMENTS


@pytest.fixture
def mcp(monkeypatch):
    """A FastMCP server wired to a seeded in-memory SQLite default connection."""
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
    auth.reset_api()
    api = auth.get_api()
    with api.engine("primary").begin() as conn:
        for stmt in SEED_STATEMENTS:
            conn.execute(text(stmt))
    server = FastMCP("sql-mcp-test")
    register_sql_tools(server)
    yield server
    auth.reset_api()


def tool_payload(result):
    """Decode a CallToolResult: `-> Any` tools emit unstructured text content."""
    if result.data is not None:
        return result.data
    if not result.content:
        return []
    text_block = result.content[0].text
    try:
        return json.loads(text_block)
    except json.JSONDecodeError:
        return text_block


async def call(mcp, tool, action, params=None, connection=""):
    async with Client(mcp) as client:
        return await client.call_tool(
            tool,
            {
                "action": action,
                "params_json": json.dumps(params or {}),
                "connection": connection,
            },
        )


async def test_all_five_tools_registered(mcp):
    async with Client(mcp) as client:
        names = {tool.name for tool in await client.list_tools()}
    assert names == {
        "sql_query",
        "sql_execute",
        "sql_schema",
        "sql_admin",
        "sql_ingest_schema",
    }


async def test_query_execute_returns_envelope(mcp):
    result = await call(
        mcp,
        "sql_query",
        "execute",
        {"sql": "SELECT id, name FROM users WHERE id = :id", "params": {"id": 1}},
    )
    payload = tool_payload(result)
    assert payload["rows"] == [{"id": 1, "name": "ada"}]
    assert payload["truncated"] is False
    assert [c["name"] for c in payload["columns"]] == ["id", "name"]


async def test_query_explain_action(mcp):
    result = await call(
        mcp, "sql_query", "explain", {"sql": "SELECT * FROM users WHERE id = 1"}
    )
    assert tool_payload(result)["row_count"] >= 1


async def test_query_rejects_write_statements(mcp):
    with pytest.raises(ToolError, match="read-only"):
        await call(mcp, "sql_query", "execute", {"sql": "DELETE FROM users"})


async def test_query_unknown_action_rejected(mcp):
    with pytest.raises(ToolError, match="execute.*explain"):
        await call(mcp, "sql_query", "drop_everything", {"sql": "SELECT 1"})


@pytest.mark.parametrize(
    ("tool", "arguments"),
    [
        ("sql_query", {"action": "execute"}),
        ("sql_execute", {"action": "execute"}),
        ("sql_schema", {"action": "schemas"}),
        ("sql_admin", {"action": "ping"}),
        ("sql_ingest_schema", {}),
    ],
)
async def test_params_json_must_decode_to_an_object(mcp, tool, arguments):
    async with Client(mcp) as client:
        with pytest.raises(ToolError, match="JSON object"):
            await client.call_tool(
                tool,
                {**arguments, "params_json": "[]", "connection": ""},
            )


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ('{"timeout": NaN}', "Non-finite"),
        ('{"x":' + "[" * 21 + "0" + "]" * 21 + "}", "nesting depth"),
    ],
)
async def test_params_json_rejects_unsafe_shapes(mcp, payload, message):
    async with Client(mcp) as client:
        with pytest.raises(ToolError, match=message):
            await client.call_tool(
                "sql_admin",
                {"action": "ping", "params_json": payload, "connection": ""},
            )


async def test_action_models_reject_unknown_arguments(mcp):
    async with Client(mcp) as client:
        with pytest.raises(ToolError, match="extra_forbidden"):
            await client.call_tool(
                "sql_admin",
                {
                    "action": "ping",
                    "params_json": '{"unexpected": true}',
                    "connection": "",
                },
            )


async def test_sql_and_kg_work_run_off_the_event_loop(mcp, monkeypatch):
    monkeypatch.setenv("SQL_ALLOW_KG_INGEST", "True")
    event_loop_thread = threading.get_ident()
    worker_threads = []
    api = auth.get_api()
    reflection = api._reflection

    def recording_reflection(connection, operation, timeout=None):
        def recorded_operation(inspector):
            worker_threads.append(threading.get_ident())
            return operation(inspector)

        return reflection(connection, recorded_operation, timeout)

    def recording_ingest_entities(*args, **kwargs):
        worker_threads.append(threading.get_ident())
        return {"nodes_created": 0, "edges_created": 0}

    monkeypatch.setattr(api, "_reflection", recording_reflection)
    monkeypatch.setattr(
        "sql_mcp.kg_ingest.ingest_entities",
        recording_ingest_entities,
    )

    await call(mcp, "sql_schema", "tables")
    async with Client(mcp) as client:
        await client.call_tool(
            "sql_ingest_schema",
            {"params_json": "{}", "connection": "primary"},
        )

    assert len(worker_threads) == 2
    assert all(thread_id != event_loop_thread for thread_id in worker_threads)


async def test_kg_ingest_is_disabled_by_default(mcp):
    async with Client(mcp) as client:
        with pytest.raises(ToolError, match="SQL_ALLOW_KG_INGEST"):
            await client.call_tool(
                "sql_ingest_schema",
                {"params_json": "{}", "connection": "primary"},
            )


async def test_execute_blocked_by_default(mcp):
    with pytest.raises(ToolError, match="SQL_ALLOW_WRITES"):
        await call(
            mcp,
            "sql_execute",
            "execute",
            {"sql": "INSERT INTO users (id, name) VALUES (9, 'eve')"},
        )


async def test_execute_allowed_when_writes_enabled(mcp, monkeypatch):
    api = auth.get_api()
    monkeypatch.setattr(api, "allow_writes", True)
    monkeypatch.setattr(api, "_writable_connections", frozenset({"primary"}))
    result = await call(
        mcp,
        "sql_execute",
        "execute",
        {
            "sql": "INSERT INTO users (id, name) VALUES (:id, :name)",
            "params": {"id": 9, "name": "eve"},
        },
    )
    assert tool_payload(result)["rowcount"] == 1


async def test_execute_script_action(mcp, monkeypatch):
    api = auth.get_api()
    monkeypatch.setattr(api, "allow_writes", True)
    monkeypatch.setattr(api, "_writable_connections", frozenset({"primary"}))
    result = await call(
        mcp,
        "sql_execute",
        "script",
        {
            "statements": [
                "CREATE TABLE notes (id INTEGER PRIMARY KEY, body TEXT)",
                "INSERT INTO notes (id, body) VALUES (1, 'hi')",
            ]
        },
    )
    assert tool_payload(result)["statements"] == 2


async def test_execute_script_action_binds_values(mcp, monkeypatch):
    api = auth.get_api()
    monkeypatch.setattr(api, "allow_writes", True)
    monkeypatch.setattr(api, "_writable_connections", frozenset({"primary"}))
    await call(
        mcp,
        "sql_execute",
        "script",
        {
            "statements": [
                {
                    "sql": "INSERT INTO users (id, name) VALUES (:id, :name)",
                    "params": {"id": 12, "name": "mary"},
                }
            ]
        },
    )
    result = await call(
        mcp,
        "sql_query",
        "execute",
        {"sql": "SELECT name FROM users WHERE id = :id", "params": {"id": 12}},
    )
    assert tool_payload(result)["rows"] == [{"name": "mary"}]


async def test_schema_actions(mcp):
    tables = tool_payload(await call(mcp, "sql_schema", "tables"))
    assert sorted(tables) == ["orders", "users"]
    views = tool_payload(await call(mcp, "sql_schema", "views"))
    assert views == ["user_emails"]
    columns = tool_payload(await call(mcp, "sql_schema", "columns", {"table": "users"}))
    assert {c["name"] for c in columns} == {"id", "name", "email"}
    fks = tool_payload(
        await call(mcp, "sql_schema", "foreign_keys", {"table": "orders"})
    )
    assert fks[0]["referred_table"] == "users"
    sample = tool_payload(
        await call(mcp, "sql_schema", "sample", {"table": "users", "limit": 2})
    )
    assert sample["row_count"] == 2
    ddl = tool_payload(await call(mcp, "sql_schema", "ddl", {"table": "users"}))
    assert "CREATE TABLE" in ddl.upper()
    constraints = tool_payload(
        await call(mcp, "sql_schema", "constraints", {"table": "users"})
    )
    assert constraints["primary_key"]["columns"] == ["id"]
    definition = tool_payload(
        await call(
            mcp,
            "sql_schema",
            "view_definition",
            {"view": "user_emails"},
        )
    )
    assert "SELECT" in definition.upper()
    catalog = tool_payload(await call(mcp, "sql_schema", "catalog", {"max_objects": 1}))
    assert catalog["object_count"] == 1


async def test_connection_param_routes_to_named_connection(mcp):
    analytics_tables = tool_payload(
        await call(mcp, "sql_schema", "tables", connection="analytics")
    )
    assert analytics_tables == []
    with pytest.raises(ToolError, match="Unknown SQL connection"):
        await call(mcp, "sql_query", "execute", {"sql": "SELECT 1"}, connection="bogus")


async def test_connection_param_is_length_bounded(mcp):
    with pytest.raises(ToolError, match="128"):
        await call(
            mcp,
            "sql_query",
            "execute",
            {"sql": "SELECT 1"},
            connection="x" * 129,
        )


async def test_admin_actions(mcp):
    ping = tool_payload(await call(mcp, "sql_admin", "ping"))
    assert ping["ok"] is True and ping["connection"] == "primary"
    version = tool_payload(await call(mcp, "sql_admin", "version"))
    assert version["dialect"] == "sqlite"
    connections = tool_payload(await call(mcp, "sql_admin", "connections"))
    assert [c["name"] for c in connections] == ["primary", "analytics"]
    dialects = tool_payload(await call(mcp, "sql_admin", "dialects"))
    assert {d["dialect"] for d in dialects} == {
        "sqlite",
        "postgres",
        "mysql",
        "mssql",
        "oracle",
    }
    sqlite_entry = next(d for d in dialects if d["dialect"] == "sqlite")
    assert sqlite_entry["driver_installed"] is True
    capabilities = tool_payload(await call(mcp, "sql_admin", "capabilities"))
    assert capabilities["dialect"] == "sqlite"
    pool = tool_payload(await call(mcp, "sql_admin", "pool_status"))
    assert pool["pool"] == "StaticPool"
    with pytest.raises(ToolError, match="ping.*version"):
        await call(mcp, "sql_admin", "shutdown")
