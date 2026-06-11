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
        with pytest.raises(ValueError, match="SHOWPLAN"):
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


def test_engine_creation_requires_driver(pg_api):
    with mock.patch(
        "sql_mcp.api.api_client_sql.require_driver",
        side_effect=ImportError("pip install sql-mcp[postgres]"),
    ):
        with pytest.raises(ImportError, match=r"sql-mcp\[postgres\]"):
            pg_api.engine("pg")


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
