"""Trino/DuckDB MCP tool layer (CA-41): action routing, dialect gating, safety gate."""

import json
from unittest import mock

import pytest
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError

from sql_mcp.mcp.mcp_sql_trino import register_duckdb_tools, register_sql_trino_tools


def _register_all(server: FastMCP) -> None:
    register_sql_trino_tools(server)
    register_duckdb_tools(server)


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


@pytest.fixture
def mcp():
    """A FastMCP server wired only to the Trino/DuckDB tool group."""
    server = FastMCP("sql-mcp-trino-test")
    _register_all(server)
    yield server


# --------------------------------------------------------------------- #
# Negative safety gate — no network needed. SqlApi.explain() runs
# assert_read_only() before it ever resolves/opens the connection, so a
# rejected write statement never touches the (unreachable) Trino host.
# --------------------------------------------------------------------- #


@pytest.fixture
def unreachable_trino_mcp(monkeypatch):
    monkeypatch.setenv(
        "SQL_CONNECTIONS",
        json.dumps({"trino1": "trino://svc@trino.invalid:8080/system"}),
    )
    monkeypatch.delenv("SQL_ALLOW_WRITES", raising=False)
    from sql_mcp import auth

    auth.reset_api()
    server = FastMCP("sql-mcp-trino-negative-test")
    _register_all(server)
    yield server
    auth.reset_api()


async def test_sql_trino_explain_rejects_drop_table(unreachable_trino_mcp):
    """A DROP TABLE through sql_trino_explain is rejected by the read-only gate.

    Known-bad demonstration for CA-41's acceptance gate 5: the statement is
    rejected before any connection attempt (the connection host doesn't
    resolve), proving the gate — not a network failure — is what stops it.
    """
    async with Client(unreachable_trino_mcp) as client:
        with pytest.raises(ToolError, match="not allowed"):
            await client.call_tool(
                "sql_trino_explain",
                {
                    "params_json": json.dumps({"sql": "DROP TABLE users"}),
                    "connection": "trino1",
                },
            )


async def test_sql_trino_explain_rejects_multi_statement_injection(
    unreachable_trino_mcp,
):
    async with Client(unreachable_trino_mcp) as client:
        with pytest.raises(ToolError, match="not allowed"):
            await client.call_tool(
                "sql_trino_explain",
                {
                    "params_json": json.dumps({"sql": "SELECT 1; DROP TABLE users"}),
                    "connection": "trino1",
                },
            )


# --------------------------------------------------------------------- #
# Dialect gating — a non-Trino connection is rejected before any SQL runs.
# --------------------------------------------------------------------- #


@pytest.fixture
def mixed_dialect_mcp(monkeypatch):
    monkeypatch.setenv(
        "SQL_CONNECTIONS",
        json.dumps(
            {
                "sqlite1": "sqlite+pysqlite:///:memory:",
                "trino1": "trino://svc@trino.invalid:8080/system",
                "duckdb1": "duckdb:///:memory:",
            }
        ),
    )
    monkeypatch.delenv("SQL_ALLOW_WRITES", raising=False)
    from sql_mcp import auth

    auth.reset_api()
    server = FastMCP("sql-mcp-trino-dialect-test")
    _register_all(server)
    yield server
    auth.reset_api()


async def test_sql_trino_catalogs_rejects_non_trino_connection(mixed_dialect_mcp):
    async with Client(mixed_dialect_mcp) as client:
        with pytest.raises(ToolError, match="'sqlite' dialect"):
            await client.call_tool("sql_trino_catalogs", {"connection": "sqlite1"})


async def test_sql_trino_schemas_rejects_non_trino_connection(mixed_dialect_mcp):
    async with Client(mixed_dialect_mcp) as client:
        with pytest.raises(ToolError, match="'duckdb' dialect"):
            await client.call_tool(
                "sql_trino_schemas",
                {
                    "params_json": json.dumps({"catalog": "system"}),
                    "connection": "duckdb1",
                },
            )


async def test_sql_trino_schemas_rejects_non_identifier_catalog(mixed_dialect_mcp):
    async with Client(mixed_dialect_mcp) as client:
        with pytest.raises(ToolError):
            await client.call_tool(
                "sql_trino_schemas",
                {
                    "params_json": json.dumps({"catalog": "system; DROP TABLE x"}),
                    "connection": "trino1",
                },
            )


# --------------------------------------------------------------------- #
# Positive dispatch path, mocked at the SqlApi.query()/explain() layer
# (no live Trino) — proves the tool wires action -> SQL -> envelope
# correctly. Live proof against the real deployed Trino is CA-41-W03's
# acceptance-gate evidence, recorded separately (not run in CI).
# --------------------------------------------------------------------- #


def fake_result(columns, rows):
    result = mock.MagicMock()
    result.keys.return_value = columns
    result.fetchmany.return_value = rows
    result.returns_rows = True
    return result


def fake_engine(result):
    engine = mock.MagicMock()
    conn = mock.MagicMock()
    conn.execute.return_value = result
    # ``SqlApi.query()`` (unlike ``explain()``) executes through
    # ``conn.execution_options(...).execute(...)``; route that chain back
    # through the same configured ``conn`` so ``conn.execute`` sees the call.
    conn.execution_options.return_value = conn
    engine.connect.return_value.__enter__.return_value = conn
    return engine, conn


@pytest.fixture
def trino_mock_mcp(monkeypatch):
    monkeypatch.setenv(
        "SQL_CONNECTIONS",
        json.dumps({"trino1": "trino://svc@trino.invalid:8080/system"}),
    )
    monkeypatch.delenv("SQL_ALLOW_WRITES", raising=False)
    from sql_mcp import auth

    auth.reset_api()
    api = auth.get_api()
    server = FastMCP("sql-mcp-trino-mock-test")
    _register_all(server)
    yield server, api
    auth.reset_api()


async def test_sql_trino_catalogs_runs_show_catalogs(trino_mock_mcp):
    server, api = trino_mock_mcp
    result = fake_result(["Catalog"], [("system",), ("lakehouse",)])
    engine, conn = fake_engine(result)
    with mock.patch.object(api, "engine", return_value=engine):
        async with Client(server) as client:
            out = await client.call_tool("sql_trino_catalogs", {"connection": "trino1"})
    payload = tool_payload(out)
    statement = str(conn.execute.call_args[0][0])
    assert statement == "SHOW CATALOGS"
    assert payload["rows"] == [{"Catalog": "system"}, {"Catalog": "lakehouse"}]


async def test_sql_trino_schemas_runs_show_schemas_from(trino_mock_mcp):
    server, api = trino_mock_mcp
    result = fake_result(["Schema"], [("information_schema",), ("analytics",)])
    engine, conn = fake_engine(result)
    with mock.patch.object(api, "engine", return_value=engine):
        async with Client(server) as client:
            out = await client.call_tool(
                "sql_trino_schemas",
                {
                    "params_json": json.dumps({"catalog": "lakehouse"}),
                    "connection": "trino1",
                },
            )
    payload = tool_payload(out)
    statement = str(conn.execute.call_args[0][0])
    assert statement == "SHOW SCHEMAS FROM lakehouse"
    assert {"Schema": "analytics"} in payload["rows"]


async def test_sql_trino_queries_caps_at_200_rows(trino_mock_mcp):
    server, api = trino_mock_mcp
    result = fake_result(
        ["query_id", "user", "state", "created", "query"],
        [(f"q{i}", "svc", "FINISHED", "2026-08-26", "SELECT 1") for i in range(5)],
    )
    engine, conn = fake_engine(result)
    with mock.patch.object(api, "engine", return_value=engine):
        async with Client(server) as client:
            out = await client.call_tool("sql_trino_queries", {"connection": "trino1"})
    tool_payload(out)
    statement = str(conn.execute.call_args[0][0])
    assert "system.runtime.queries" in statement
    assert "ORDER BY created DESC" in statement
    # The 200-row cap is enforced via api.query(max_rows=200): SqlApi.query()
    # streams with ``max_row_buffer = cap + 1`` — assert the tool always
    # requests the capped value, never an unbounded read.
    _, options_kwargs = conn.execution_options.call_args
    assert options_kwargs["max_row_buffer"] == 201


async def test_sql_trino_queries_filters_by_state(trino_mock_mcp):
    server, api = trino_mock_mcp
    result = fake_result(["query_id", "user", "state", "created", "query"], [])
    engine, conn = fake_engine(result)
    with mock.patch.object(api, "engine", return_value=engine):
        async with Client(server) as client:
            await client.call_tool(
                "sql_trino_queries",
                {
                    "params_json": json.dumps({"state": "RUNNING"}),
                    "connection": "trino1",
                },
            )
    statement, params = conn.execute.call_args[0]
    assert "WHERE state = :state" in str(statement)
    assert params == {"state": "RUNNING"}


async def test_sql_trino_explain_runs_explain_prefix(trino_mock_mcp):
    server, api = trino_mock_mcp
    result = fake_result(["_col0"], [("plan",)])
    engine, conn = fake_engine(result)
    with mock.patch.object(api, "engine", return_value=engine):
        async with Client(server) as client:
            out = await client.call_tool(
                "sql_trino_explain",
                {
                    "params_json": json.dumps({"sql": "SELECT 1"}),
                    "connection": "trino1",
                },
            )
    payload = tool_payload(out)
    statement = str(conn.execute.call_args[0][0])
    assert statement.startswith("EXPLAIN SELECT")
    assert payload["rows"] == [{"_col0": "plan"}]


# --------------------------------------------------------------------- #
# sql_duckdb_attach_iceberg — input validation + statement-sequence shape.
# The 'duckdb' import happens inside the tool; this module doesn't require
# duckdb to be installed to prove the SQL sequence and validation are right,
# but does require it in this environment (installed as a dev/test extra
# for the live proof this lane also ran). Skip cleanly if unavailable.
# --------------------------------------------------------------------- #

duckdb = pytest.importorskip("duckdb")


@pytest.fixture
def duckdb_mcp(monkeypatch):
    monkeypatch.delenv("SQL_CONNECTIONS", raising=False)
    monkeypatch.delenv("SQL_URL", raising=False)
    monkeypatch.delenv("SQL_ALLOW_WRITES", raising=False)
    from sql_mcp import auth

    auth.reset_api()
    server = FastMCP("sql-mcp-duckdb-test")
    _register_all(server)
    yield server
    auth.reset_api()


async def test_sql_duckdb_attach_iceberg_rejects_bad_token(duckdb_mcp):
    """A token outside the validated bearer-token charset is rejected before DuckDB runs."""
    async with Client(duckdb_mcp) as client:
        with pytest.raises(ToolError):
            await client.call_tool(
                "sql_duckdb_attach_iceberg",
                {
                    "params_json": json.dumps(
                        {
                            "alias": "lake",
                            "rest_uri": "http://lakekeeper.invalid/catalog",
                            "warehouse": "lakehouse",
                            "token": "not a valid token; DROP TABLE x",
                        }
                    ),
                },
            )


async def test_sql_duckdb_attach_iceberg_rejects_non_identifier_alias(duckdb_mcp):
    async with Client(duckdb_mcp) as client:
        with pytest.raises(ToolError):
            await client.call_tool(
                "sql_duckdb_attach_iceberg",
                {
                    "params_json": json.dumps(
                        {
                            "alias": "lake; DROP TABLE x",
                            "rest_uri": "http://lakekeeper.invalid/catalog",
                            "warehouse": "lakehouse",
                            "token": "abc.def-ghi_123",
                        }
                    ),
                },
            )


async def test_sql_duckdb_attach_iceberg_surfaces_typed_error_on_unreachable_catalog(
    duckdb_mcp,
):
    """An unreachable REST catalog fails explicitly, never a silent fallback."""
    async with Client(duckdb_mcp) as client:
        with pytest.raises(ToolError, match="ATTACH against Iceberg REST catalog"):
            await client.call_tool(
                "sql_duckdb_attach_iceberg",
                {
                    "params_json": json.dumps(
                        {
                            "alias": "lake",
                            "rest_uri": "http://127.0.0.1:1/catalog",
                            "warehouse": "lakehouse",
                            "token": "abc.def-ghi_123",
                        }
                    ),
                },
            )
