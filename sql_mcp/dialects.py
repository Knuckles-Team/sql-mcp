"""Dialect registry for sql-mcp (CONCEPT:SQL-1.1).

Mirrors the vector-mcp backend-registry pattern: every supported SQL engine is
described by a :class:`DialectSpec` entry in :data:`DIALECTS`. The spec carries
the SQLAlchemy URL scheme, the optional driver package (and which pip extra
ships it), and the dialect-specific administrative SQL the ``sql_admin`` tool
uses. Core ships SQLite only (stdlib-backed); the other drivers are optional
extras so the base install stays thin.
"""

import importlib
from dataclasses import dataclass

from sqlalchemy.engine import URL


@dataclass(frozen=True)
class DialectSpec:
    """Static description of one supported SQL dialect."""

    name: str
    sqlalchemy_scheme: str
    driver_module: str | None
    extra: str | None
    default_port: int | None
    explain_prefix: str | None
    version_sql: str | None
    active_connections_sql: str | None


DIALECTS: dict[str, DialectSpec] = {
    "sqlite": DialectSpec(
        name="sqlite",
        sqlalchemy_scheme="sqlite+pysqlite",
        driver_module=None,
        extra=None,
        default_port=None,
        explain_prefix="EXPLAIN QUERY PLAN",
        version_sql="SELECT sqlite_version()",
        active_connections_sql=None,
    ),
    "postgres": DialectSpec(
        name="postgres",
        sqlalchemy_scheme="postgresql+psycopg",
        driver_module="psycopg",
        extra="postgres",
        default_port=5432,
        explain_prefix="EXPLAIN",
        version_sql="SELECT version()",
        active_connections_sql=(
            "SELECT pid, usename, datname, state, application_name, query_start "
            "FROM pg_stat_activity WHERE pid <> pg_backend_pid()"
        ),
    ),
    "mysql": DialectSpec(
        name="mysql",
        sqlalchemy_scheme="mysql+pymysql",
        driver_module="pymysql",
        extra="mysql",
        default_port=3306,
        explain_prefix="EXPLAIN",
        version_sql="SELECT VERSION()",
        active_connections_sql=(
            "SELECT id, user, host, db, command, time, state "
            "FROM information_schema.processlist"
        ),
    ),
    "mssql": DialectSpec(
        name="mssql",
        sqlalchemy_scheme="mssql+pyodbc",
        driver_module="pyodbc",
        extra="mssql",
        default_port=1433,
        explain_prefix=None,
        version_sql="SELECT @@VERSION",
        active_connections_sql=(
            "SELECT session_id, login_name, status, host_name, program_name "
            "FROM sys.dm_exec_sessions WHERE is_user_process = 1"
        ),
    ),
    "oracle": DialectSpec(
        name="oracle",
        sqlalchemy_scheme="oracle+oracledb",
        driver_module="oracledb",
        extra="oracle",
        default_port=1521,
        explain_prefix="EXPLAIN PLAN FOR",
        version_sql="SELECT banner FROM v$version",
        active_connections_sql=(
            "SELECT sid, username, status, machine, program "
            "FROM v$session WHERE username IS NOT NULL"
        ),
    ),
}

ALIASES: dict[str, str] = {
    "postgresql": "postgres",
    "pg": "postgres",
    "pgsql": "postgres",
    "mariadb": "mysql",
    "sqlserver": "mssql",
    "mssqlserver": "mssql",
    "sqlite3": "sqlite",
}


def get_dialect(name: str) -> DialectSpec:
    """Resolve a dialect (or alias) name to its :class:`DialectSpec`.

    Raises ``ValueError`` listing the supported dialects when unknown.
    """
    key = ALIASES.get(name.lower().strip(), name.lower().strip())
    spec = DIALECTS.get(key)
    if spec is None:
        supported = ", ".join(sorted(DIALECTS))
        raise ValueError(f"Unknown SQL dialect {name!r}. Supported: {supported}.")
    return spec


def dialect_for_url(url: URL) -> DialectSpec | None:
    """Best-effort match of a SQLAlchemy URL to a registered dialect spec."""
    backend = url.get_backend_name()
    for spec in DIALECTS.values():
        if spec.sqlalchemy_scheme.split("+", 1)[0] == backend:
            return spec
    alias = ALIASES.get(backend)
    return DIALECTS.get(alias) if alias else None


def require_driver(spec: DialectSpec) -> None:
    """Verify the dialect's DBAPI driver is importable.

    Raises ``ImportError`` naming the pip extra that ships the driver, so the
    failure is self-explanatory (``pip install sql-mcp[postgres]`` etc.).
    """
    if spec.driver_module is None:
        return
    try:
        importlib.import_module(spec.driver_module)
    except ImportError as exc:
        raise ImportError(
            f"The {spec.name!r} dialect needs the {spec.driver_module!r} driver. "
            f"Install it with: pip install sql-mcp[{spec.extra}]"
        ) from exc


def driver_available(spec: DialectSpec) -> bool:
    """Return True when the dialect's DBAPI driver can be imported."""
    if spec.driver_module is None:
        return True
    try:
        importlib.import_module(spec.driver_module)
        return True
    except ImportError:
        return False


def build_url(
    dialect: str,
    host: str | None = None,
    port: int | None = None,
    username: str | None = None,
    password: str | None = None,
    database: str | None = None,
    options: dict[str, str] | None = None,
) -> URL:
    """Build a SQLAlchemy URL from discrete connection fields.

    Uses ``URL.create`` so credentials are quoted correctly and the password
    is never interpolated into a plain string (redaction-safe by design).
    """
    spec = get_dialect(dialect)
    if spec.name == "sqlite":
        return URL.create(spec.sqlalchemy_scheme, database=database or ":memory:")
    return URL.create(
        spec.sqlalchemy_scheme,
        username=username,
        password=password,
        host=host,
        port=port or spec.default_port,
        database=database,
        query=dict(options or {}),
    )
