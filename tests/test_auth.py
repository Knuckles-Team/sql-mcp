"""Connection config loading (CONCEPT:SQL-1.2): env parsing + secret redaction."""

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
    assert auth.default_max_rows() == auth.DEFAULT_MAX_ROWS
    assert auth.default_timeout() == auth.DEFAULT_TIMEOUT_SECONDS


def test_policy_env_overrides(monkeypatch):
    monkeypatch.setenv("SQL_ALLOW_WRITES", "True")
    monkeypatch.setenv("SQL_MAX_ROWS", "25")
    monkeypatch.setenv("SQL_TIMEOUT_SECONDS", "2.5")
    assert auth.allow_writes() is True
    assert auth.default_max_rows() == 25
    assert auth.default_timeout() == 2.5


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


def test_passwords_never_in_logs(monkeypatch, caplog):
    monkeypatch.setenv(
        "SQL_CONNECTIONS",
        json.dumps({"dw": "postgresql+psycopg://bob:supersecretpw@db:5432/dw"}),
    )
    with caplog.at_level("DEBUG"):
        auth.load_connections()
        auth.get_api()
    assert "supersecretpw" not in caplog.text
