"""Dialect registry (CONCEPT:SQL-1.1): URL building, drivers, dialect SQL."""

from unittest import mock

import pytest
from sqlalchemy.engine import make_url

from sql_mcp.dialects import (
    DIALECTS,
    DialectSpec,
    build_url,
    dialect_for_url,
    driver_available,
    get_dialect,
    require_driver,
)

EXPECTED_DIALECTS = {"sqlite", "postgres", "mysql", "mssql", "oracle"}


def test_registry_covers_required_dialects():
    assert set(DIALECTS) == EXPECTED_DIALECTS


def test_extras_matrix():
    extras = {name: spec.extra for name, spec in DIALECTS.items()}
    assert extras == {
        "sqlite": None,  # stdlib-backed, ships in core
        "postgres": "postgres",
        "mysql": "mysql",
        "mssql": "mssql",
        "oracle": "oracle",
    }


@pytest.mark.parametrize(
    ("alias", "canonical"),
    [
        ("postgresql", "postgres"),
        ("pg", "postgres"),
        ("mariadb", "mysql"),
        ("sqlserver", "mssql"),
        ("sqlite3", "sqlite"),
        ("POSTGRES", "postgres"),
    ],
)
def test_aliases_resolve(alias, canonical):
    assert get_dialect(alias).name == canonical


def test_unknown_dialect_lists_supported():
    with pytest.raises(ValueError, match="postgres"):
        get_dialect("db2")


@pytest.mark.parametrize(
    ("dialect", "scheme", "port"),
    [
        ("postgres", "postgresql+psycopg", 5432),
        ("mysql", "mysql+pymysql", 3306),
        ("mssql", "mssql+pyodbc", 1433),
        ("oracle", "oracle+oracledb", 1521),
    ],
)
def test_build_url_applies_scheme_and_default_port(dialect, scheme, port):
    url = build_url(
        dialect,
        host="db.example.com",
        username="svc",
        password="pw",
        database="app",
    )
    assert url.drivername == scheme
    assert url.port == port
    assert url.password == "pw"


def test_build_url_explicit_port_wins():
    assert build_url("postgres", host="h", port=6543).port == 6543


def test_build_url_sqlite_paths():
    assert build_url("sqlite").database == ":memory:"
    assert build_url("sqlite", database="/data/x.db").database == "/data/x.db"


def test_build_url_quotes_special_characters():
    url = build_url("postgres", host="h", username="svc", password="p@:s/s")
    assert url.password == "p@:s/s"
    rendered = url.render_as_string(hide_password=False)
    assert "p@:s/s" not in rendered  # quoted, not raw-interpolated


def test_dialect_for_url_matches_backend():
    assert dialect_for_url(make_url("postgresql://h/db")).name == "postgres"
    assert dialect_for_url(make_url("mysql+pymysql://h/db")).name == "mysql"
    assert dialect_for_url(make_url("sqlite:///:memory:")).name == "sqlite"
    assert dialect_for_url(make_url("firebird://h/db")) is None


def test_require_driver_passes_for_stdlib_sqlite():
    require_driver(get_dialect("sqlite"))


def test_require_driver_error_names_extra():
    spec = DialectSpec(
        name="postgres",
        sqlalchemy_scheme="postgresql+psycopg",
        driver_module="psycopg_definitely_not_installed",
        extra="postgres",
        default_port=5432,
        explain_prefix="EXPLAIN",
        version_sql=None,
        active_connections_sql=None,
    )
    with pytest.raises(ImportError, match=r"sql-mcp\[postgres\]"):
        require_driver(spec)
    assert driver_available(spec) is False


def test_require_driver_with_mocked_import():
    spec = get_dialect("oracle")
    with mock.patch("sql_mcp.dialects.importlib.import_module") as imp:
        require_driver(spec)
        imp.assert_called_once_with("oracledb")


def test_every_networked_dialect_declares_admin_sql():
    for name in ("postgres", "mysql", "mssql", "oracle"):
        spec = DIALECTS[name]
        assert spec.version_sql
        assert spec.active_connections_sql


def test_mssql_has_no_portable_explain():
    assert DIALECTS["mssql"].explain_prefix is None
    for name in ("sqlite", "postgres", "mysql", "oracle"):
        assert DIALECTS[name].explain_prefix
