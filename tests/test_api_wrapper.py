"""SqlApi core paths: query/execute/schema/admin against in-memory SQLite."""

import math
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest import mock

import pytest
from sqlalchemy import create_engine as sqlalchemy_create_engine
from sqlalchemy.exc import OperationalError

from sql_mcp.api.api_client_sql import (
    SqlTimeoutError,
    WritesDisabledError,
)
from sql_mcp.api_client import Api
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


def test_query_preserves_duplicate_column_names(api):
    result = api.query("SELECT 1 AS value, 2 AS value")
    assert result["rows"] == [{"value": 1, "value__2": 2}]
    assert [column["source_name"] for column in result["columns"]] == [
        "value",
        "value",
    ]


def test_query_normalizes_binary_values_for_json(api):
    result = api.query("SELECT x'00ff' AS payload")
    assert result["rows"] == [
        {
            "payload": {
                "encoding": "base64",
                "data": "AP8=",
                "truncated": False,
            }
        }
    ]


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
    raw = api.engine("primary").raw_connection()
    try:

        def slow() -> int:
            time.sleep(2)
            return 1

        raw.driver_connection.create_function("slow", 0, slow)
        with pytest.raises(SqlTimeoutError):
            api.query("SELECT slow()", timeout=0.2)
    finally:
        raw.close()


def test_caller_cannot_disable_or_extend_server_timeout():
    client = Api(
        connections={"primary": MEMORY_URL},
        allow_writes=False,
        max_rows=10,
        timeout=0.05,
    )
    raw = client.engine("primary").raw_connection()
    try:

        def slow() -> int:
            time.sleep(0.2)
            return 1

        raw.driver_connection.create_function("slow", 0, slow)
        with pytest.raises(ValueError, match="positive"):
            client.query("SELECT slow()", timeout=0)
        with pytest.raises(SqlTimeoutError):
            client.query("SELECT slow()", timeout=30)
    finally:
        raw.close()
        client.dispose()


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


def test_write_policy_can_be_limited_per_connection():
    client = Api(
        connections={"primary": MEMORY_URL, "analytics": MEMORY_URL},
        allow_writes=True,
        writable_connections={"primary"},
        max_rows=10,
        timeout=1.0,
    )
    try:
        with pytest.raises(WritesDisabledError, match="disabled"):
            client.execute("CREATE TABLE denied (id INTEGER)", connection="analytics")
        assert (
            client.execute("CREATE TABLE allowed (id INTEGER)", connection="primary")[
                "rowcount"
            ]
            == -1
        )
    finally:
        client.dispose()


def test_database_errors_hide_bound_parameter_values(writable_api):
    secret = "should-never-appear-in-errors"
    with pytest.raises(Exception) as exc_info:
        writable_api.execute(
            "INSERT INTO users (id, name) VALUES (:id, :name)",
            params={"id": 1, "name": secret},
        )
    assert secret not in str(exc_info.value)


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


def test_execute_returns_bounded_rows_for_returning(writable_api):
    result = writable_api.execute(
        "INSERT INTO users (id, name) VALUES (:id, :name) RETURNING id, name",
        params={"id": 8, "name": "katherine"},
    )
    # sqlite3 reports rowcount=0 for RETURNING; the portable returned-row count
    # lives in the bounded result envelope.
    assert result["row_count"] == 1
    assert result["rows"] == [{"id": 8, "name": "katherine"}]
    assert result["truncated"] is False


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


def test_script_supports_bound_parameters(writable_api):
    result = writable_api.execute_script(
        [
            {
                "sql": "INSERT INTO users (id, name) VALUES (:id, :name)",
                "params": {"id": 8, "name": "dorothy"},
            },
            {
                "sql": "UPDATE users SET email = :email WHERE id = :id",
                "params": {"id": 8, "email": "dorothy@example.com"},
            },
        ]
    )
    assert result == {"statements": 2, "rowcounts": [1, 1], "atomic": True}
    rows = writable_api.query("SELECT name, email FROM users WHERE id = 8")["rows"]
    assert rows == [{"name": "dorothy", "email": "dorothy@example.com"}]


def test_script_rejects_empty_executemany_params(writable_api):
    with pytest.raises(ValueError, match="non-empty"):
        writable_api.execute_script([{"sql": "DELETE FROM users", "params": []}])
    assert writable_api.query("SELECT count(*) AS n FROM users")["rows"] == [{"n": 3}]


def test_timed_out_write_never_commits_later():
    client = Api(
        connections={"primary": MEMORY_URL},
        allow_writes=True,
        writable_connections={"primary"},
        max_rows=10,
        timeout=0.05,
    )
    raw = client.engine("primary").raw_connection()
    try:
        raw.driver_connection.create_function(
            "slow_name", 0, lambda: (time.sleep(0.2), "late")[1]
        )
        with client.engine("primary").begin() as conn:
            conn.exec_driver_sql("CREATE TABLE timed (name TEXT)")
        with pytest.raises(SqlTimeoutError):
            client.execute("INSERT INTO timed (name) VALUES (slow_name())")
        time.sleep(0.25)
        assert client.query("SELECT name FROM timed")["rows"] == []
    finally:
        raw.close()
        client.dispose()


def test_batch_and_script_limits_are_enforced():
    client = Api(
        connections={"primary": MEMORY_URL},
        allow_writes=True,
        writable_connections={"primary"},
        max_rows=10,
        timeout=1.0,
        max_batch_rows=2,
        max_script_statements=2,
    )
    try:
        with client.engine().begin() as conn:
            conn.exec_driver_sql("CREATE TABLE bounded (id INTEGER)")
        with pytest.raises(ValueError, match="batch"):
            client.execute(
                "INSERT INTO bounded (id) VALUES (:id)",
                params=[{"id": 1}, {"id": 2}, {"id": 3}],
            )
        with pytest.raises(ValueError, match="statements"):
            client.execute_script(["SELECT 1", "SELECT 2", "SELECT 3"])
    finally:
        client.dispose()


@pytest.mark.parametrize(
    "url",
    [
        "mysql+pymysql://svc:pw@db/app",
        "oracle+oracledb://svc:pw@db/app",
    ],
)
def test_implicit_commit_dialects_reject_multi_statement_ddl_scripts(url):
    client = Api(
        connections={"primary": url},
        allow_writes=True,
        writable_connections={"primary"},
        max_rows=10,
        timeout=1.0,
    )
    try:
        with pytest.raises(ValueError, match="implicitly commits DDL"):
            client.execute_script(
                [
                    "CREATE TABLE example (id INTEGER)",
                    "INSERT INTO example (id) VALUES (1)",
                ]
            )
    finally:
        client.dispose()


def test_script_rolls_back_on_failure(writable_api):
    with pytest.raises(OperationalError):
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


def test_schema_list_pagination(api):
    assert api.list_tables(limit=1, offset=0) == ["orders"]
    assert api.list_tables(limit=1, offset=1) == ["users"]
    with pytest.raises(ValueError, match="non-negative"):
        api.list_tables(offset=-1)


def test_materialized_views_and_sequences_are_portably_empty_on_sqlite(api):
    assert api.list_materialized_views() == []
    assert api.list_sequences() == []


def test_list_columns(api):
    cols = {c["name"]: c for c in api.list_columns("users")}
    assert cols["id"]["primary_key"] is True
    assert cols["name"]["nullable"] is False
    assert cols["email"]["nullable"] is True
    assert "INT" in cols["id"]["type"].upper()


def test_list_indexes(api):
    indexes = api.list_indexes("users")
    assert any(
        i["name"] == "ix_users_name" and i["columns"] == ["name"] for i in indexes
    )


def test_list_foreign_keys(api):
    fks = api.list_foreign_keys("orders")
    assert fks[0]["referred_table"] == "users"
    assert fks[0]["columns"] == ["user_id"]
    assert fks[0]["referred_columns"] == ["id"]
    assert fks[0]["referred_schema"] is None


def test_constraints_view_definition_and_comment(api):
    constraints = api.list_constraints("users")
    assert constraints["primary_key"]["columns"] == ["id"]
    assert constraints["unique"] == []
    definition = api.view_definition("user_emails")
    assert definition is not None and "SELECT" in definition.upper()
    assert api.table_comment("users") == {"text": None, "dialect_options": {}}


def test_schema_catalog_is_bounded_and_complete(api):
    catalog = api.schema_catalog(max_objects=2)
    assert catalog["connection"] == "primary"
    assert catalog["object_count"] == 2
    assert catalog["truncated"] is True
    users = next(item for item in catalog["objects"] if item["name"] == "users")
    assert {column["name"] for column in users["columns"]} == {
        "id",
        "name",
        "email",
    }


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


def test_admin_capabilities_pool_and_ping_all(api):
    capabilities = api.capabilities()
    assert capabilities["dialect"] == "sqlite"
    assert capabilities["transactional_ddl"] is True
    assert capabilities["distributed_transactions"] is False
    pool = api.pool_status()
    assert pool["connection"] == "primary"
    assert pool["pool"] == "StaticPool"
    health = api.ping_all()
    assert [item["connection"] for item in health] == ["primary", "analytics"]
    assert all(item["ok"] for item in health)


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


def test_default_connection_can_be_selected_explicitly():
    client = Api(
        connections={"primary": MEMORY_URL, "analytics": MEMORY_URL},
        default_connection="analytics",
        allow_writes=False,
        max_rows=10,
        timeout=1.0,
    )
    try:
        assert client.default_connection() == "analytics"
    finally:
        client.dispose()


def test_connections_are_isolated(api):
    assert api.list_tables(connection="analytics") == []
    assert sorted(api.list_tables(connection="primary")) == ["orders", "users"]


def test_concurrent_engine_creation_reuses_one_pool():
    client = Api(
        connections={"primary": MEMORY_URL},
        allow_writes=False,
        max_rows=10,
        timeout=1.0,
    )
    created = []

    def delayed_create_engine(*args, **kwargs):
        time.sleep(0.03)
        engine = sqlalchemy_create_engine(*args, **kwargs)
        created.append(engine)
        return engine

    try:
        with mock.patch(
            "sql_mcp.api.api_client_sql.create_engine",
            side_effect=delayed_create_engine,
        ):
            with ThreadPoolExecutor(max_workers=12) as executor:
                engines = list(executor.map(lambda _: client.engine(), range(12)))
        assert len({id(engine) for engine in engines}) == 1
        assert len(created) == 1
    finally:
        client.dispose()


def test_worker_submission_queue_is_bounded():
    client = Api(
        connections={"primary": MEMORY_URL},
        allow_writes=False,
        max_rows=10,
        timeout=5.0,
    )
    release = Event()
    futures = []
    try:
        for _ in range(client._max_workers * 2):
            futures.append(client._submit(lambda: release.wait(timeout=5.0)))
        with pytest.raises(RuntimeError, match="capacity is exhausted"):
            client._submit(lambda: None)
    finally:
        release.set()
        for future in futures:
            future.result(timeout=5.0)
            client._complete_future(future)
        client.dispose()


def test_unknown_connection_error_does_not_reflect_registry_or_input(api):
    with pytest.raises(ValueError, match="Unknown SQL connection") as exc_info:
        api.query("SELECT 1", connection="nope")
    message = str(exc_info.value)
    assert "primary" not in message
    assert "nope" not in message


def test_requires_at_least_one_connection():
    with pytest.raises(ValueError, match="At least one"):
        Api(connections={}, allow_writes=False, max_rows=10, timeout=5.0)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("max_rows", 0),
        ("max_rows", -1),
        ("timeout", 0),
        ("timeout", -1),
        ("timeout", math.nan),
        ("max_batch_rows", 0),
        ("max_script_statements", 0),
        ("max_sql_length", 0),
    ],
)
def test_resource_limits_must_be_positive(field, value):
    kwargs = {
        "connections": {"primary": MEMORY_URL},
        "allow_writes": False,
        "max_rows": 10,
        "timeout": 5.0,
    }
    kwargs[field] = value
    with pytest.raises(ValueError, match="positive"):
        Api(**kwargs)


def test_sql_length_limit_is_enforced():
    client = Api(
        connections={"primary": MEMORY_URL},
        allow_writes=False,
        max_rows=10,
        timeout=1.0,
        max_sql_length=8,
    )
    try:
        with pytest.raises(ValueError, match="length"):
            client.query("SELECT 123456789")
    finally:
        client.dispose()


def test_result_byte_limit_applies_to_the_first_row():
    client = Api(
        connections={"primary": MEMORY_URL},
        allow_writes=False,
        max_rows=10,
        timeout=1.0,
        max_result_bytes=10,
        max_cell_bytes=100,
    )
    try:
        result = client.query("SELECT 'abcdefghij' AS a, 'klmnopqrst' AS b")
        assert result["rows"] == []
        assert result["bytes_returned"] == 0
        assert result["truncated"] is True
    finally:
        client.dispose()
