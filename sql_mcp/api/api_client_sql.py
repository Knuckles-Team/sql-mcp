"""SQLAlchemy 2.x Core facade for sql-mcp (CONCEPT:SQL-1.4).

``SqlApi`` is the single API surface the MCP tools call. It owns the named
connection registry (lazy ``Engine`` per connection), enforces the read-only
gate, the per-call row cap, and the per-call timeout, and returns bounded
result envelopes (records + column metadata + truncation flag). All SQL is
executed through ``sqlalchemy.text()`` with bound parameters — user values are
never interpolated into statement strings.
"""

import concurrent.futures
from collections.abc import Callable, Mapping
from typing import Any

from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.engine import URL, Engine, make_url
from sqlalchemy.pool import StaticPool
from sqlalchemy.schema import CreateTable, MetaData, Table

from sql_mcp import auth
from sql_mcp.dialects import DialectSpec, dialect_for_url, require_driver
from sql_mcp.safety import assert_read_only, assert_single_statement

__version__ = "0.1.0"


class SqlTimeoutError(TimeoutError):
    """Raised when a statement exceeds the per-call timeout."""


class WritesDisabledError(PermissionError):
    """Raised when ``sql_execute`` is called while the server is read-only."""


def _is_memory_sqlite(url: URL) -> bool:
    return url.get_backend_name() == "sqlite" and url.database in (None, "", ":memory:")


class SqlApi:
    """Multi-connection SQL client over SQLAlchemy Core.

    Parameters default from the environment (see :mod:`sql_mcp.auth`); tests
    pass them explicitly. Engines are created lazily per named connection and
    reused; in-memory SQLite gets a ``StaticPool`` so every call shares one
    database.
    """

    def __init__(
        self,
        connections: dict[str, URL] | None = None,
        allow_writes: bool | None = None,
        max_rows: int | None = None,
        timeout: float | None = None,
    ) -> None:
        raw = dict(connections) if connections is not None else auth.load_connections()
        self._connections = {
            name: make_url(url) if isinstance(url, str) else url
            for name, url in raw.items()
        }
        if not self._connections:
            raise ValueError("At least one SQL connection must be configured.")
        self.allow_writes = (
            allow_writes if allow_writes is not None else auth.allow_writes()
        )
        self.max_rows = max_rows if max_rows is not None else auth.default_max_rows()
        self.timeout = timeout if timeout is not None else auth.default_timeout()
        self._engines: dict[str, Engine] = {}

    # ------------------------------------------------------------------ #
    # Connection registry
    # ------------------------------------------------------------------ #

    def connection_names(self) -> list[str]:
        """Names of all configured connections."""
        return list(self._connections)

    def default_connection(self) -> str:
        """The sole/first configured connection — used when none is named."""
        return next(iter(self._connections))

    def resolve_connection(self, connection: str | None = None) -> str:
        """Map an optional connection name to a configured one (or raise)."""
        if not connection:
            return self.default_connection()
        if connection not in self._connections:
            known = ", ".join(self._connections)
            raise ValueError(f"Unknown connection {connection!r}. Known: {known}.")
        return connection

    def dialect_spec(self, connection: str | None = None) -> DialectSpec | None:
        """The registered :class:`DialectSpec` for a connection, if any."""
        name = self.resolve_connection(connection)
        return dialect_for_url(self._connections[name])

    def engine(self, connection: str | None = None) -> Engine:
        """Lazily create (and cache) the Engine for a named connection."""
        name = self.resolve_connection(connection)
        eng = self._engines.get(name)
        if eng is None:
            url = self._connections[name]
            spec = dialect_for_url(url)
            if spec is not None:
                require_driver(spec)
            kwargs: dict[str, Any] = {"pool_pre_ping": True}
            if _is_memory_sqlite(url):
                kwargs = {
                    "poolclass": StaticPool,
                    "connect_args": {"check_same_thread": False},
                }
            eng = create_engine(url, **kwargs)
            self._engines[name] = eng
        return eng

    def dispose(self) -> None:
        """Dispose all pooled engines."""
        for eng in self._engines.values():
            eng.dispose()
        self._engines.clear()

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #

    def _run_with_timeout(self, fn: Callable[[], Any], timeout: float | None) -> Any:
        """Run ``fn`` on a worker thread, bounded by ``timeout`` seconds."""
        effective = self.timeout if timeout is None else float(timeout)
        if effective <= 0:
            return fn()
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        future = executor.submit(fn)
        try:
            return future.result(timeout=effective)
        except concurrent.futures.TimeoutError as exc:
            raise SqlTimeoutError(
                f"Statement exceeded the {effective:g}s timeout and was abandoned."
            ) from exc
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

    def _effective_max_rows(self, max_rows: int | None) -> int:
        if max_rows is None or max_rows <= 0:
            return self.max_rows
        return min(int(max_rows), self.max_rows)

    @staticmethod
    def _result_envelope(result: Any, cap: int) -> dict[str, Any]:
        """Fetch up to ``cap`` rows and describe columns (CONCEPT:SQL-1.4)."""
        columns = list(result.keys())
        fetched = result.fetchmany(cap + 1)
        truncated = len(fetched) > cap
        rows = [dict(zip(columns, row, strict=False)) for row in fetched[:cap]]
        column_meta = [
            {
                "name": col,
                "type": type(rows[0][col]).__name__ if rows else "unknown",
            }
            for col in columns
        ]
        return {
            "columns": column_meta,
            "rows": rows,
            "row_count": len(rows),
            "truncated": truncated,
        }

    # ------------------------------------------------------------------ #
    # Query (read-only)
    # ------------------------------------------------------------------ #

    def query(
        self,
        sql: str,
        params: Mapping[str, Any] | None = None,
        connection: str | None = None,
        max_rows: int | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Execute a read-only SELECT/CTE with bound parameters.

        Enforces the read-only gate, clamps ``max_rows`` to the server cap,
        and bounds execution time. Returns ``{"columns", "rows", "row_count",
        "truncated"}``.
        """
        assert_read_only(sql)
        cap = self._effective_max_rows(max_rows)
        eng = self.engine(connection)

        def run() -> dict[str, Any]:
            with eng.connect() as conn:
                result = conn.execute(text(sql), dict(params or {}))
                return self._result_envelope(result, cap)

        return self._run_with_timeout(run, timeout)

    def explain(
        self,
        sql: str,
        params: Mapping[str, Any] | None = None,
        connection: str | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Return the dialect's query plan for a read-only statement."""
        assert_read_only(sql)
        name = self.resolve_connection(connection)
        spec = self.dialect_spec(name)
        if spec is None or spec.explain_prefix is None:
            dialect = spec.name if spec else self._connections[name].get_backend_name()
            raise ValueError(
                f"EXPLAIN is not supported for dialect {dialect!r} "
                "(MSSQL uses SET SHOWPLAN, which needs a dedicated session)."
            )
        plan_sql = " ".join((spec.explain_prefix, sql))
        eng = self.engine(name)

        def run() -> dict[str, Any]:
            with eng.connect() as conn:
                result = conn.execute(text(plan_sql), dict(params or {}))
                if not result.returns_rows:
                    return {
                        "columns": [],
                        "rows": [],
                        "row_count": 0,
                        "truncated": False,
                    }
                return self._result_envelope(result, self.max_rows)

        return self._run_with_timeout(run, timeout)

    # ------------------------------------------------------------------ #
    # Execute (writes, gated)
    # ------------------------------------------------------------------ #

    def _assert_writes_allowed(self) -> None:
        if not self.allow_writes:
            raise WritesDisabledError(
                "Writes are disabled: the server is read-only by default. "
                "Start it with SQL_ALLOW_WRITES=True to enable sql_execute."
            )

    def execute(
        self,
        sql: str,
        params: Mapping[str, Any] | list[Mapping[str, Any]] | None = None,
        connection: str | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Execute one DML/DDL statement in a transaction (writes gate applies).

        ``params`` may be a mapping (single execution) or a list of mappings
        (``executemany``). Returns the affected-row count.
        """
        self._assert_writes_allowed()
        assert_single_statement(sql)
        eng = self.engine(connection)

        def run() -> dict[str, Any]:
            with eng.begin() as conn:
                result = conn.execute(text(sql), params or {})
                return {"rowcount": result.rowcount}

        return self._run_with_timeout(run, timeout)

    def execute_script(
        self,
        statements: list[str],
        connection: str | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Run several statements in ONE transaction (all-or-nothing).

        Any failure rolls back every prior statement in the list.
        """
        self._assert_writes_allowed()
        if not statements:
            raise ValueError("'statements' must be a non-empty list of SQL strings.")
        for stmt in statements:
            assert_single_statement(stmt)
        eng = self.engine(connection)

        def run() -> dict[str, Any]:
            rowcounts = []
            with eng.begin() as conn:
                for stmt in statements:
                    result = conn.execute(text(stmt))
                    rowcounts.append(result.rowcount)
            return {"statements": len(statements), "rowcounts": rowcounts}

        return self._run_with_timeout(run, timeout)

    # ------------------------------------------------------------------ #
    # Schema reflection
    # ------------------------------------------------------------------ #

    def list_schemas(self, connection: str | None = None) -> list[str]:
        """List schema names."""
        return list(inspect(self.engine(connection)).get_schema_names())

    def list_tables(
        self, schema: str | None = None, connection: str | None = None
    ) -> list[str]:
        """List table names (optionally within a schema)."""
        return list(inspect(self.engine(connection)).get_table_names(schema=schema))

    def list_views(
        self, schema: str | None = None, connection: str | None = None
    ) -> list[str]:
        """List view names (optionally within a schema)."""
        return list(inspect(self.engine(connection)).get_view_names(schema=schema))

    def list_columns(
        self, table: str, schema: str | None = None, connection: str | None = None
    ) -> list[dict[str, Any]]:
        """Describe a table's columns: name, type, nullable, default."""
        cols = inspect(self.engine(connection)).get_columns(table, schema=schema)
        return [
            {
                "name": col["name"],
                "type": str(col["type"]),
                "nullable": bool(col.get("nullable", True)),
                "default": col.get("default"),
                "primary_key": bool(col.get("primary_key", False)),
            }
            for col in cols
        ]

    def list_indexes(
        self, table: str, schema: str | None = None, connection: str | None = None
    ) -> list[dict[str, Any]]:
        """List a table's indexes (name, columns, uniqueness)."""
        idx = inspect(self.engine(connection)).get_indexes(table, schema=schema)
        return [
            {
                "name": entry.get("name"),
                "columns": list(entry.get("column_names") or []),
                "unique": bool(entry.get("unique", False)),
            }
            for entry in idx
        ]

    def list_foreign_keys(
        self, table: str, schema: str | None = None, connection: str | None = None
    ) -> list[dict[str, Any]]:
        """List a table's foreign keys (columns -> referred table/columns)."""
        fks = inspect(self.engine(connection)).get_foreign_keys(table, schema=schema)
        return [
            {
                "name": entry.get("name"),
                "columns": list(entry.get("constrained_columns") or []),
                "referred_table": entry.get("referred_table"),
                "referred_columns": list(entry.get("referred_columns") or []),
            }
            for entry in fks
        ]

    def table_ddl(
        self, table: str, schema: str | None = None, connection: str | None = None
    ) -> str:
        """Reflect a table and render its CREATE TABLE DDL for this dialect."""
        eng = self.engine(connection)
        metadata = MetaData()
        reflected = Table(table, metadata, schema=schema, autoload_with=eng)
        return str(CreateTable(reflected).compile(eng)).strip()

    def sample_rows(
        self,
        table: str,
        schema: str | None = None,
        limit: int = 10,
        connection: str | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Return up to ``limit`` rows from a table (cap still applies).

        Built with SQLAlchemy Core ``select()`` on the reflected table — the
        identifier is quoted by SQLAlchemy, never interpolated by hand.
        """
        eng = self.engine(connection)
        cap = self._effective_max_rows(limit)
        metadata = MetaData()
        reflected = Table(table, metadata, schema=schema, autoload_with=eng)

        def run() -> dict[str, Any]:
            with eng.connect() as conn:
                # Fetch one extra row so the envelope can flag truncation.
                result = conn.execute(select(reflected).limit(cap + 1))
                return self._result_envelope(result, cap)

        return self._run_with_timeout(run, timeout)

    # ------------------------------------------------------------------ #
    # Admin
    # ------------------------------------------------------------------ #

    def ping(self, connection: str | None = None) -> dict[str, Any]:
        """Connection test: ``SELECT 1`` round-trip with latency."""
        import time

        eng = self.engine(connection)
        started = time.monotonic()

        def run() -> None:
            with eng.connect() as conn:
                conn.execute(text("SELECT 1"))

        self._run_with_timeout(run, None)
        return {
            "connection": self.resolve_connection(connection),
            "ok": True,
            "latency_ms": round((time.monotonic() - started) * 1000, 2),
        }

    def server_version(self, connection: str | None = None) -> dict[str, Any]:
        """Report the server version (dialect SQL, else SQLAlchemy's probe)."""
        name = self.resolve_connection(connection)
        spec = self.dialect_spec(name)
        eng = self.engine(name)

        def run() -> dict[str, Any]:
            with eng.connect() as conn:
                version: str | None = None
                if spec is not None and spec.version_sql:
                    version = str(conn.execute(text(spec.version_sql)).scalar())
                info = getattr(conn.dialect, "server_version_info", None)
                return {
                    "connection": name,
                    "dialect": eng.dialect.name,
                    "version": version
                    or (".".join(str(part) for part in info) if info else "unknown"),
                }

        return self._run_with_timeout(run, None)

    def active_connections(self, connection: str | None = None) -> dict[str, Any]:
        """List active server sessions where the dialect supports it."""
        name = self.resolve_connection(connection)
        spec = self.dialect_spec(name)
        if spec is None or spec.active_connections_sql is None:
            dialect = spec.name if spec else self._connections[name].get_backend_name()
            return {
                "connection": name,
                "supported": False,
                "detail": f"Dialect {dialect!r} has no active-session view.",
            }
        eng = self.engine(name)

        def run() -> dict[str, Any]:
            with eng.connect() as conn:
                result = conn.execute(text(spec.active_connections_sql))
                envelope = self._result_envelope(result, self.max_rows)
            envelope.update({"connection": name, "supported": True})
            return envelope

        return self._run_with_timeout(run, None)

    def describe_connections(self) -> list[dict[str, Any]]:
        """Describe configured connections with passwords redacted."""
        described = []
        for name, url in self._connections.items():
            spec = dialect_for_url(url)
            described.append(
                {
                    "name": name,
                    "url": url.render_as_string(hide_password=True),
                    "dialect": spec.name if spec else url.get_backend_name(),
                    "default": name == self.default_connection(),
                }
            )
        return described
