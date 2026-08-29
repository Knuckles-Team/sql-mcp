"""Connection config loading (CONCEPT:SQ-OS.identity.env-parsing-secret-redaction): env parsing + secret redaction."""

import json

import pytest

from sql_mcp import auth

ENV_VARS = [
    "SQL_CONNECTIONS",
    "SQL_URL",
    "SQL_DIALECT",
    "SQL_HOST",
    "SQL_PORT",
    "SQL_USERNAME",
    "SQL_PASSWORD",
    "SQL_DATABASE",
    "SQL_OPTIONS",
    "SQL_ALLOW_WRITES",
    "SQL_ALLOW_KG_INGEST",
    "SQL_WRITE_CONNECTIONS",
    "SQL_DEFAULT_CONNECTION",
    "SQL_MAX_ROWS",
    "SQL_TIMEOUT_SECONDS",
]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for var in ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    auth.reset_api()
    yield
    auth.reset_api()


def test_sql_connections_json_with_dsn_strings(monkeypatch):
    monkeypatch.setenv(
        "SQL_CONNECTIONS",
        json.dumps(
            {
                "warehouse": "postgresql+psycopg://bob:s3cret@db.example.com:5432/dw",
                "scratch": "sqlite+pysqlite:///:memory:",
            }
        ),
    )
    connections = auth.load_connections()
    assert list(connections) == ["warehouse", "scratch"]
    assert connections["warehouse"].host == "db.example.com"
    assert connections["warehouse"].password == "s3cret"


def test_sql_connections_json_with_discrete_fields(monkeypatch):
    monkeypatch.setenv(
        "SQL_CONNECTIONS",
        json.dumps(
            {
                "erp": {
                    "dialect": "mysql",
                    "host": "erp.example.com",
                    "username": "svc",
                    "password": "p@ss",
                    "database": "erp",
                    "options": {"charset": "utf8mb4"},
                }
            }
        ),
    )
    connections = auth.load_connections()
    url = connections["erp"]
    assert url.drivername == "mysql+pymysql"
    assert url.port == 3306  # dialect default applied
    assert url.query["charset"] == "utf8mb4"


def test_sql_connections_url_object_form(monkeypatch):
    monkeypatch.setenv(
        "SQL_CONNECTIONS",
        json.dumps({"main": {"url": "sqlite+pysqlite:////data/app.db"}}),
    )
    assert auth.load_connections()["main"].database == "/data/app.db"


def test_sql_connections_invalid_json_raises(monkeypatch):
    monkeypatch.setenv("SQL_CONNECTIONS", "{not json")
    with pytest.raises(ValueError, match="valid JSON"):
        auth.load_connections()


def test_sql_connections_bad_entry_raises(monkeypatch):
    monkeypatch.setenv("SQL_CONNECTIONS", json.dumps({"x": {"hostname": "nope"}}))
    with pytest.raises(ValueError, match="'url' or 'dialect'"):
        auth.load_connections()


def test_sql_url_registers_default(monkeypatch):
    monkeypatch.setenv("SQL_URL", "sqlite+pysqlite:///:memory:")
    connections = auth.load_connections()
    assert list(connections) == ["default"]


def test_discrete_env_fields_build_default(monkeypatch):
    monkeypatch.setenv("SQL_DIALECT", "postgres")
    monkeypatch.setenv("SQL_HOST", "pg.example.com")
    monkeypatch.setenv("SQL_PORT", "5433")
    monkeypatch.setenv("SQL_USERNAME", "svc")
    monkeypatch.setenv("SQL_PASSWORD", "hunter2")
    monkeypatch.setenv("SQL_DATABASE", "app")
    url = auth.load_connections()["default"]
    assert url.drivername == "postgresql+psycopg"
    assert url.port == 5433
    assert url.password == "hunter2"


def test_zero_config_falls_back_to_memory_sqlite():
    connections = auth.load_connections()
    assert list(connections) == ["memory"]
    assert connections["memory"].get_backend_name() == "sqlite"


def test_policy_defaults_are_read_only_and_bounded():
    assert auth.allow_writes() is False
    assert auth.allow_kg_ingest() is False
    assert auth.writable_connections() == set()
    assert auth.default_max_rows() == auth.DEFAULT_MAX_ROWS
    assert auth.default_timeout() == auth.DEFAULT_TIMEOUT_SECONDS


def test_policy_env_overrides(monkeypatch):
    monkeypatch.setenv("SQL_ALLOW_WRITES", "True")
    monkeypatch.setenv("SQL_ALLOW_KG_INGEST", "True")
    monkeypatch.setenv("SQL_MAX_ROWS", "25")
    monkeypatch.setenv("SQL_TIMEOUT_SECONDS", "2.5")
    assert auth.allow_writes() is True
    assert auth.allow_kg_ingest() is True
    assert auth.default_max_rows() == 25
    assert auth.default_timeout() == 2.5


@pytest.mark.parametrize(
    ("name", "value", "loader"),
    [
        ("SQL_MAX_ROWS", "0", auth.default_max_rows),
        ("SQL_MAX_ROWS", "-1", auth.default_max_rows),
        ("SQL_TIMEOUT_SECONDS", "0", auth.default_timeout),
        ("SQL_TIMEOUT_SECONDS", "nan", auth.default_timeout),
    ],
)
def test_invalid_resource_policy_is_rejected(monkeypatch, name, value, loader):
    monkeypatch.setenv(name, value)
    with pytest.raises(ValueError, match="positive"):
        loader()


def test_write_connection_allowlist(monkeypatch):
    monkeypatch.setenv("SQL_WRITE_CONNECTIONS", '["primary", "warehouse"]')
    assert auth.writable_connections() == {"primary", "warehouse"}


def test_write_connection_allowlist_is_required_when_writes_are_enabled(
    monkeypatch,
):
    monkeypatch.setenv("SQL_ALLOW_WRITES", "True")
    api = auth.get_api()
    with pytest.raises(PermissionError, match="SQL_WRITE_CONNECTIONS"):
        api.execute("CREATE TABLE denied (id INTEGER)")


def test_write_connection_allowlist_accepts_comma_separated_names(monkeypatch):
    monkeypatch.setenv("SQL_WRITE_CONNECTIONS", "primary, warehouse")
    assert auth.writable_connections() == {"primary", "warehouse"}


def test_explicit_default_connection(monkeypatch):
    monkeypatch.setenv(
        "SQL_CONNECTIONS",
        json.dumps(
            {
                "primary": "sqlite+pysqlite:///:memory:",
                "analytics": "sqlite+pysqlite:///:memory:",
            }
        ),
    )
    monkeypatch.setenv("SQL_DEFAULT_CONNECTION", "analytics")
    assert auth.get_api().default_connection() == "analytics"


def test_get_api_caches_until_reset(monkeypatch):
    monkeypatch.setenv("SQL_URL", "sqlite+pysqlite:///:memory:")
    first = auth.get_api()
    assert auth.get_api() is first
    auth.reset_api()
    assert auth.get_api() is not first


def test_passwords_redacted_in_connection_descriptions(monkeypatch):
    monkeypatch.setenv(
        "SQL_CONNECTIONS",
        json.dumps({"dw": "postgresql+psycopg://bob:supersecretpw@db:5432/dw"}),
    )
    api = auth.get_api()
    described = api.describe_connections()
    assert "supersecretpw" not in json.dumps(described)
    assert "***" in described[0]["url"]


def test_url_query_secrets_are_redacted_in_connection_descriptions(monkeypatch):
    monkeypatch.setenv(
        "SQL_CONNECTIONS",
        json.dumps(
            {
                "dw": (
                    "postgresql+psycopg://bob:pw@db:5432/dw?"
                    "sslmode=require&access_token=query-secret&sslpassword=tls-secret"
                )
            }
        ),
    )
    described = json.dumps(auth.get_api().describe_connections())
    assert "query-secret" not in described
    assert "tls-secret" not in described
    assert "sslmode=require" in described


def test_odbc_connect_query_is_fully_redacted(monkeypatch):
    monkeypatch.setenv(
        "SQL_CONNECTIONS",
        json.dumps(
            {
                "mart": (
                    "mssql+pyodbc:///?odbc_connect="
                    "DRIVER%3DODBC%2BDriver%3BSERVER%3Ddb%3BPWD%3Dodbc-secret"
                )
            }
        ),
    )
    described = auth.get_api().describe_connections()[0]
    assert "odbc-secret" not in json.dumps(described)
    assert "odbc_connect=%2A%2A%2A" in described["url"]


def test_passwords_never_in_logs(monkeypatch, caplog):
    monkeypatch.setenv(
        "SQL_CONNECTIONS",
        json.dumps({"dw": "postgresql+psycopg://bob:supersecretpw@db:5432/dw"}),
    )
    with caplog.at_level("DEBUG"):
        auth.load_connections()
        auth.get_api()
    assert "supersecretpw" not in caplog.text


# --------------------------------------------------------------------- #
# _connection_from_spec / load_connections: branches a plain round trip
# through a valid config never reaches
# --------------------------------------------------------------------- #


def test_connection_from_spec_rejects_invalid_dsn_string():
    with pytest.raises(ValueError, match="invalid SQL URL"):
        auth._connection_from_spec("x", "not a valid :// dsn ///")


def test_connection_from_spec_rejects_non_string_url_field():
    with pytest.raises(ValueError, match="invalid SQL URL"):
        auth._connection_from_spec("x", {"url": 123})


def test_connection_from_spec_rejects_invalid_url_field_value():
    with pytest.raises(ValueError, match="invalid SQL URL"):
        auth._connection_from_spec("x", {"url": "not a valid :// dsn ///"})


def test_connection_from_spec_rejects_non_string_dialect():
    with pytest.raises(ValueError, match="invalid SQL dialect"):
        auth._connection_from_spec("x", {"dialect": 123})


def test_connection_from_spec_rejects_non_dict_options():
    with pytest.raises(ValueError, match="options must be a JSON object"):
        auth._connection_from_spec("x", {"dialect": "postgres", "options": "nope"})


def test_connection_from_spec_rejects_non_string_non_dict_spec():
    with pytest.raises(ValueError, match="DSN string or"):
        auth._connection_from_spec("x", 12345)


def test_sql_connections_rejects_oversized_config(monkeypatch):
    monkeypatch.setenv(
        "SQL_CONNECTIONS",
        json.dumps({"x": "sqlite+pysqlite:///:memory:"})
        + " " * (auth.MAX_CONNECTION_CONFIG_BYTES),
    )
    with pytest.raises(ValueError, match="configuration size limit"):
        auth.load_connections()


def test_sql_connections_rejects_empty_mapping(monkeypatch):
    monkeypatch.setenv("SQL_CONNECTIONS", "{}")
    with pytest.raises(ValueError, match="non-empty JSON object"):
        auth.load_connections()


def test_sql_connections_rejects_non_object_json(monkeypatch):
    monkeypatch.setenv("SQL_CONNECTIONS", "[1, 2, 3]")
    with pytest.raises(ValueError, match="non-empty JSON object"):
        auth.load_connections()


def test_sql_connections_rejects_too_many_entries(monkeypatch):
    mapping = {
        f"conn{i}": "sqlite+pysqlite:///:memory:"
        for i in range(auth.MAX_CONNECTIONS + 1)
    }
    monkeypatch.setenv("SQL_CONNECTIONS", json.dumps(mapping))
    with pytest.raises(ValueError, match="connection limit"):
        auth.load_connections()


def test_sql_connections_rejects_invalid_connection_name(monkeypatch):
    monkeypatch.setenv(
        "SQL_CONNECTIONS", json.dumps({"": "sqlite+pysqlite:///:memory:"})
    )
    with pytest.raises(ValueError, match="non-empty bounded strings"):
        auth.load_connections()


def test_discrete_fields_reject_invalid_options_json(monkeypatch):
    monkeypatch.setenv("SQL_DIALECT", "postgres")
    monkeypatch.setenv("SQL_OPTIONS", "{not json")
    with pytest.raises(ValueError, match="SQL_OPTIONS is not valid JSON"):
        auth.load_connections()


def test_discrete_fields_reject_non_object_options(monkeypatch):
    monkeypatch.setenv("SQL_DIALECT", "postgres")
    monkeypatch.setenv("SQL_OPTIONS", "[1, 2]")
    with pytest.raises(ValueError, match="SQL_OPTIONS must be a JSON object"):
        auth.load_connections()


def test_discrete_fields_reject_non_numeric_port(monkeypatch):
    monkeypatch.setenv("SQL_DIALECT", "postgres")
    monkeypatch.setenv("SQL_PORT", "not-a-port")
    with pytest.raises(ValueError, match="SQL_PORT must be an integer"):
        auth.load_connections()


def test_discrete_fields_reject_out_of_range_port(monkeypatch):
    monkeypatch.setenv("SQL_DIALECT", "postgres")
    monkeypatch.setenv("SQL_PORT", "99999")
    with pytest.raises(ValueError, match="SQL_PORT must be an integer"):
        auth.load_connections()


# --------------------------------------------------------------------- #
# writable_connections: branches beyond the JSON-list and comma-list
# happy paths already covered above
# --------------------------------------------------------------------- #


def test_write_connection_allowlist_rejects_invalid_json_list(monkeypatch):
    monkeypatch.setenv("SQL_WRITE_CONNECTIONS", "[not json")
    with pytest.raises(ValueError, match="JSON list or comma-separated"):
        auth.writable_connections()


def test_write_connection_allowlist_rejects_non_string_json_entries(monkeypatch):
    monkeypatch.setenv("SQL_WRITE_CONNECTIONS", "[1, 2]")
    with pytest.raises(ValueError, match="must be a string list"):
        auth.writable_connections()


def test_write_connection_allowlist_rejects_too_many_names(monkeypatch):
    names = ",".join(f"conn{i}" for i in range(auth.MAX_CONNECTIONS + 1))
    monkeypatch.setenv("SQL_WRITE_CONNECTIONS", names)
    with pytest.raises(ValueError, match="connection limit"):
        auth.writable_connections()
