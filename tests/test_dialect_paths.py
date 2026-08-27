"""Mock-based coverage of dialect-specific SqlApi paths (no live servers)."""

from unittest import mock

import pytest

from sql_mcp.api_client import Api


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
    engine.connect.return_value.__enter__.return_value = conn
    return engine, conn


@pytest.fixture
def pg_api():
    client = Api(
        connections={"pg": "postgresql+psycopg://svc:pw@db:5432/app"},
        allow_writes=False,
        max_rows=50,
        timeout=5.0,
    )
    yield client
    client.dispose()


def test_explain_unsupported_for_mssql():
    client = Api(
        connections={"mart": "mssql+pyodbc://svc:pw@db:1433/mart"},
        allow_writes=False,
        max_rows=50,
        timeout=5.0,
    )
    try:
        with pytest.raises(ValueError, match="not safely supported"):
            client.explain("SELECT 1")
    finally:
        client.dispose()


def test_explain_unsupported_for_oracle():
    client = Api(
        connections={"oracle": "oracle+oracledb://svc:pw@db:1521/app"},
        allow_writes=False,
        max_rows=50,
        timeout=5.0,
    )
    try:
        with pytest.raises(ValueError, match="not safely supported"):
            client.explain("SELECT 1")
    finally:
        client.dispose()


def test_explain_uses_postgres_prefix(pg_api):
    result = fake_result(["QUERY PLAN"], [("Seq Scan on users",)])
    engine, conn = fake_engine(result)
    with mock.patch.object(pg_api, "engine", return_value=engine):
        plan = pg_api.explain("SELECT * FROM users")
    statement = conn.execute.call_args[0][0]
    assert str(statement).startswith("EXPLAIN SELECT")
    assert plan["rows"] == [{"QUERY PLAN": "Seq Scan on users"}]


def test_active_connections_runs_pg_stat_activity(pg_api):
    result = fake_result(["pid", "state"], [(42, "active")])
    engine, conn = fake_engine(result)
    with mock.patch.object(pg_api, "engine", return_value=engine):
        sessions = pg_api.active_connections()
    statement = str(conn.execute.call_args[0][0])
    assert "pg_stat_activity" in statement
    assert sessions["supported"] is True
    assert sessions["rows"] == [{"pid": 42, "state": "active"}]


def test_server_version_uses_dialect_sql(pg_api):
    result = mock.MagicMock()
    result.scalar.return_value = "PostgreSQL 16.3"
    engine, conn = fake_engine(result)
    conn.dialect.server_version_info = (16, 3)
    with mock.patch.object(pg_api, "engine", return_value=engine):
        version = pg_api.server_version()
    assert "PostgreSQL 16.3" in version["version"]
    assert str(conn.execute.call_args[0][0]) == "SELECT version()"


@pytest.mark.parametrize("dialect", ["postgresql", "mysql", "mariadb", "oracle"])
def test_supported_dialects_enable_database_read_only_transactions(pg_api, dialect):
    conn = mock.MagicMock()
    conn.dialect.name = dialect

    reset = pg_api._enable_read_only(conn)

    conn.exec_driver_sql.assert_called_once_with("SET TRANSACTION READ ONLY")
    assert reset is None


def test_sqlite_database_read_only_state_is_restored(pg_api):
    conn = mock.MagicMock()
    conn.dialect.name = "sqlite"
    conn.exec_driver_sql.return_value.scalar.return_value = 0

    reset = pg_api._enable_read_only(conn)

    conn.exec_driver_sql.assert_any_call("PRAGMA query_only = ON")
    assert reset is not None
    reset()
    conn.exec_driver_sql.assert_any_call("PRAGMA query_only = OFF")


def test_postgres_statement_timeout_is_applied_server_side(pg_api):
    conn = mock.MagicMock()
    conn.dialect.name = "postgresql"

    reset = pg_api._configure_statement_timeout(conn, 1.25)

    statement, params = conn.execute.call_args.args
    assert str(statement) == "SELECT set_config('statement_timeout', :value, true)"
    assert params == {"value": "1250ms"}
    conn.execute.return_value.close.assert_called_once_with()
    assert reset is None


def test_oracle_call_timeout_is_applied_and_restored(pg_api):
    conn = mock.MagicMock()
    conn.dialect.name = "oracle"
    driver_connection = mock.MagicMock()
    driver_connection.call_timeout = 900
    conn.connection.driver_connection = driver_connection

    reset = pg_api._configure_statement_timeout(conn, 1.25)

    assert driver_connection.call_timeout == 1250
    assert reset is not None
    reset()
    assert driver_connection.call_timeout == 900


def test_engine_creation_requires_driver(pg_api):
    with mock.patch(
        "sql_mcp.api.api_client_sql.require_driver",
        side_effect=ImportError("pip install sql-mcp[postgres]"),
    ):
        with pytest.raises(ImportError, match=r"sql-mcp\[postgres\]"):
            pg_api.engine("pg")


@pytest.fixture
def trino_api():
    client = Api(
        connections={"trino1": "trino://svc@trino.apps.svc:8080/system"},
        allow_writes=False,
        max_rows=50,
        timeout=5.0,
    )
    yield client
    client.dispose()


def test_explain_uses_trino_prefix(trino_api):
    result = fake_result(["_col0"], [("EXPLAIN plan text",)])
    engine, conn = fake_engine(result)
    with mock.patch.object(trino_api, "engine", return_value=engine):
        plan = trino_api.explain("SELECT 1")
    statement = conn.execute.call_args[0][0]
    assert str(statement).startswith("EXPLAIN SELECT")
    assert plan["rows"] == [{"_col0": "EXPLAIN plan text"}]


def test_active_connections_reads_runtime_queries(trino_api):
    result = fake_result(
        ["query_id", "user", "state", "created"],
        [("q1", "svc", "RUNNING", "2026-08-26")],
    )
    engine, conn = fake_engine(result)
    with mock.patch.object(trino_api, "engine", return_value=engine):
        sessions = trino_api.active_connections()
    statement = str(conn.execute.call_args[0][0])
    assert "system.runtime.queries" in statement
    assert sessions["supported"] is True
    assert sessions["rows"] == [
        {"query_id": "q1", "user": "svc", "state": "RUNNING", "created": "2026-08-26"}
    ]


def test_server_version_uses_trino_select_version(trino_api):
    result = mock.MagicMock()
    result.scalar.return_value = "476"
    engine, conn = fake_engine(result)
    conn.dialect.server_version_info = None
    with mock.patch.object(trino_api, "engine", return_value=engine):
        version = trino_api.server_version()
    assert version["version"] == "476"
    assert str(conn.execute.call_args[0][0]) == "SELECT version()"


def test_unregistered_dialect_reports_no_session_view():
    client = Api(
        connections={"fb": "firebird://svc:pw@db/x"},
        allow_writes=False,
        max_rows=50,
        timeout=5.0,
    )
    try:
        result = client.active_connections()
        assert result["supported"] is False
        assert "firebird" in result["detail"]
    finally:
        client.dispose()
