"""SqlApi core paths: query/execute/schema/admin against in-memory SQLite."""

import pytest

from sql_mcp.api_client import Api
from sql_mcp.api.api_client_sql import (
    SqlTimeoutError,
    WritesDisabledError,
)
from sql_mcp.safety import StatementNotAllowedError
from tests.conftest import MEMORY_URL


# --------------------------------------------------------------------- #
# query
# --------------------------------------------------------------------- #


def test_query_returns_rows_and_column_metadata(api):
    result = api.query("SELECT id, name FROM users ORDER BY id")
    assert result["row_count"] == 3
    assert result["truncated"] is False
    assert [c["name"] for c in result["columns"]] == ["id", "name"]
    assert result["rows"][0] == {"id": 1, "name": "ada"}
    types = {c["name"]: c["type"] for c in result["columns"]}
    assert types["id"] == "int"
    assert types["name"] == "str"


def test_query_binds_named_parameters(api):
    result = api.query(
        "SELECT name FROM users WHERE id = :id AND name = :name",
        params={"id": 2, "name": "grace"},
    )
    assert result["rows"] == [{"name": "grace"}]


def test_query_rejects_writes(api):
    with pytest.raises(StatementNotAllowedError):
        api.query("DELETE FROM users")


def test_query_rejects_multi_statement(api):
    with pytest.raises(StatementNotAllowedError):
        api.query("SELECT 1; SELECT 2")


def test_query_row_cap_clamps_and_flags_truncation(api):
    result = api.query("SELECT id FROM users ORDER BY id", max_rows=2)
    assert result["row_count"] == 2
    assert result["truncated"] is True


def test_query_row_cap_never_exceeds_server_cap():
    client = Api(
        connections={"primary": MEMORY_URL},
        allow_writes=False,
        max_rows=2,
        timeout=10.0,
    )
    try:
        result = client.query(
            "SELECT 1 AS a UNION ALL SELECT 2 UNION ALL SELECT 3",
            max_rows=999,
        )
        assert result["row_count"] == 2
        assert result["truncated"] is True
    finally:
        client.dispose()


def test_query_timeout_enforced(api):
    import time

    raw = api.engine("primary").raw_connection()
    try:
        raw.driver_connection.create_function("slow", 0, lambda: time.sleep(2) or 1)
        with pytest.raises(SqlTimeoutError):
            api.query("SELECT slow()", timeout=0.2)
    finally:
        raw.close()


def test_explain_returns_plan(api):
    result = api.explain("SELECT * FROM users WHERE id = :id", params={"id": 1})
    assert result["row_count"] >= 1


def test_explain_rejects_writes(api):
    with pytest.raises(StatementNotAllowedError):
        api.explain("DELETE FROM users")


# --------------------------------------------------------------------- #
# execute (writes gate)
# --------------------------------------------------------------------- #


def test_execute_blocked_when_read_only(api):
    with pytest.raises(WritesDisabledError, match="SQL_ALLOW_WRITES"):
        api.execute("INSERT INTO users (id, name) VALUES (4, 'lin')")


def test_execute_script_blocked_when_read_only(api):
    with pytest.raises(WritesDisabledError):
        api.execute_script(["CREATE TABLE t (a int)"])


def test_execute_insert_reports_rowcount(writable_api):
    result = writable_api.execute(
        "INSERT INTO users (id, name) VALUES (:id, :name)",
        params={"id": 4, "name": "lin"},
    )
    assert result["rowcount"] == 1
    rows = writable_api.query("SELECT count(*) AS n FROM users")["rows"]
    assert rows == [{"n": 4}]


def test_execute_many_with_param_list(writable_api):
    result = writable_api.execute(
        "INSERT INTO users (id, name) VALUES (:id, :name)",
        params=[{"id": 5, "name": "a"}, {"id": 6, "name": "b"}],
    )
    assert result["rowcount"] == 2


def test_execute_update_rowcount(writable_api):
    result = writable_api.execute("UPDATE users SET email = NULL WHERE id <= 2")
    assert result["rowcount"] == 2


def test_execute_rejects_multi_statement(writable_api):
    with pytest.raises(StatementNotAllowedError):
        writable_api.execute("DELETE FROM orders; DELETE FROM users")


def test_script_runs_in_one_transaction(writable_api):
    result = writable_api.execute_script(
        [
            "CREATE TABLE tags (id INTEGER PRIMARY KEY, label TEXT)",
            "INSERT INTO tags (id, label) VALUES (1, 'x')",
        ]
    )
    assert result["statements"] == 2
    assert writable_api.query("SELECT label FROM tags")["rows"] == [{"label": "x"}]


def test_script_rolls_back_on_failure(writable_api):
    with pytest.raises(Exception):
        writable_api.execute_script(
            [
                "INSERT INTO users (id, name) VALUES (7, 'temp')",
                "INSERT INTO no_such_table (id) VALUES (1)",
            ]
        )
    rows = writable_api.query("SELECT count(*) AS n FROM users WHERE id = 7")["rows"]
    assert rows == [{"n": 0}]


def test_script_requires_statements(writable_api):
    with pytest.raises(ValueError):
        writable_api.execute_script([])


# --------------------------------------------------------------------- #
# schema reflection
# --------------------------------------------------------------------- #


def test_list_schemas(api):
    assert "main" in api.list_schemas()


def test_list_tables_and_views(api):
    assert sorted(api.list_tables()) == ["orders", "users"]
    assert api.list_views() == ["user_emails"]


def test_list_columns(api):
    cols = {c["name"]: c for c in api.list_columns("users")}
    assert cols["id"]["primary_key"] is True
    assert cols["name"]["nullable"] is False
    assert cols["email"]["nullable"] is True
    assert "INT" in cols["id"]["type"].upper()


def test_list_indexes(api):
    indexes = api.list_indexes("users")
    assert any(i["name"] == "ix_users_name" and i["columns"] == ["name"] for i in indexes)


def test_list_foreign_keys(api):
    fks = api.list_foreign_keys("orders")
    assert fks[0]["referred_table"] == "users"
    assert fks[0]["columns"] == ["user_id"]
    assert fks[0]["referred_columns"] == ["id"]


def test_table_ddl_reflection(api):
    ddl = api.table_ddl("users")
    assert ddl.upper().startswith("CREATE TABLE")
    assert "users" in ddl


def test_sample_rows_respects_limit(api):
    sample = api.sample_rows("users", limit=2)
    assert sample["row_count"] == 2
    assert sample["truncated"] is True


# --------------------------------------------------------------------- #
# admin
# --------------------------------------------------------------------- #


def test_ping_reports_latency(api):
    result = api.ping()
    assert result == {
        "connection": "primary",
        "ok": True,
        "latency_ms": result["latency_ms"],
    }
    assert result["latency_ms"] >= 0


def test_server_version(api):
    result = api.server_version()
    assert result["dialect"] == "sqlite"
    assert result["version"][0].isdigit()


def test_active_connections_unsupported_on_sqlite(api):
    result = api.active_connections()
    assert result["supported"] is False
    assert "sqlite" in result["detail"]


def test_describe_connections_marks_default(api):
    described = {d["name"]: d for d in api.describe_connections()}
    assert described["primary"]["default"] is True
    assert described["analytics"]["default"] is False
    assert described["primary"]["dialect"] == "sqlite"


# --------------------------------------------------------------------- #
# multi-connection routing
# --------------------------------------------------------------------- #


def test_default_connection_is_first_configured(api):
    assert api.default_connection() == "primary"
    assert api.resolve_connection(None) == "primary"
    assert api.resolve_connection("") == "primary"


def test_connections_are_isolated(api):
    assert api.list_tables(connection="analytics") == []
    assert sorted(api.list_tables(connection="primary")) == ["orders", "users"]


def test_unknown_connection_error_lists_known(api):
    with pytest.raises(ValueError, match="primary"):
        api.query("SELECT 1", connection="nope")


def test_requires_at_least_one_connection():
    with pytest.raises(ValueError, match="At least one"):
        Api(connections={}, allow_writes=False, max_rows=10, timeout=5.0)
