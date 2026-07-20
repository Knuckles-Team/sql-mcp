"""SQLAlchemy 2.x Core facade for sql-mcp (CONCEPT:SQ-OS.governance.sql-3).

``SqlApi`` is the single API surface the MCP tools call. It owns the named
connection registry (lazy ``Engine`` per connection), enforces the read-only
gate, the per-call row cap, and the per-call timeout, and returns bounded
result envelopes (records + column metadata + truncation flag). All SQL is
executed through ``sqlalchemy.text()`` with bound parameters — user values are
never interpolated into statement strings.
"""

import asyncio
import base64
import concurrent.futures
import datetime as dt
import enum
import json
import math
import threading
import uuid
from collections.abc import Callable, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from decimal import Decimal
from typing import Any

from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.engine import URL, Connection, Engine, make_url
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


_ASYNC_SQL_EXECUTION: ContextVar[bool] = ContextVar(
    "sql_mcp_async_execution",
    default=False,
)


@contextmanager
def asynchronous_sql_execution():
    """Return submitted SQL operations as awaitables for an async caller."""
    token = _ASYNC_SQL_EXECUTION.set(True)
    try:
        yield
    finally:
        _ASYNC_SQL_EXECUTION.reset(token)


class _AsyncSqlOperation:
    """Await a submitted operation while preserving timeout cancellation."""

    def __init__(
        self,
        future: concurrent.futures.Future[Any],
        timeout: float,
        on_cancel: Callable[[], None] | None,
        on_done: Callable[[concurrent.futures.Future[Any]], None],
    ) -> None:
        self._future = future
        self._timeout = timeout
        self._on_cancel = on_cancel
        self._on_done = on_done
        self._cleanup_started = False

    async def _cleanup_when_done(self) -> None:
        while not self._future.done():
            await asyncio.sleep(0.05)
        self._on_done(self._future)

    def _schedule_cleanup(self) -> None:
        if self._cleanup_started:
            return
        self._cleanup_started = True
        if self._future.done():
            self._on_done(self._future)
        else:
            asyncio.create_task(self._cleanup_when_done())

    async def _wait(self) -> Any:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._timeout
        try:
            while not self._future.done():
                remaining = deadline - loop.time()
                if remaining <= 0:
                    if self._on_cancel is not None:
                        self._on_cancel()
                    self._future.cancel()
                    raise SqlTimeoutError(
                        f"Statement exceeded the {self._timeout:g}s timeout; "
                        "cancellation was requested."
                    )
                await asyncio.sleep(min(0.01, remaining))
            return self._future.result()
        except asyncio.CancelledError:
            if self._on_cancel is not None:
                self._on_cancel()
            self._future.cancel()
            raise
        finally:
            self._schedule_cleanup()

    def __await__(self):
        return self._wait().__await__()


DEFAULT_MAX_BATCH_ROWS = 1_000
DEFAULT_MAX_SCRIPT_STATEMENTS = 100
DEFAULT_MAX_SQL_LENGTH = 1_000_000
DEFAULT_MAX_RESULT_BYTES = 4 * 1024 * 1024
DEFAULT_MAX_CELL_BYTES = 1 * 1024 * 1024
DEFAULT_MAX_COLUMNS = 1_000

_SENSITIVE_QUERY_PARTS = (
    "credential",
    "key",
    "odbc_connect",
    "password",
    "passwd",
    "pwd",
    "secret",
    "token",
)


def _is_memory_sqlite(url: URL) -> bool:
    return url.get_backend_name() == "sqlite" and url.database in (None, "", ":memory:")


def _positive_int(name: str, value: Any) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a positive integer.")
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        raise ValueError(f"{name} must be a positive integer.") from None
    if parsed <= 0 or (isinstance(value, float) and not value.is_integer()):
        raise ValueError(f"{name} must be a positive integer.")
    return parsed


def _positive_float(name: str, value: Any) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a finite, positive number.")
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        raise ValueError(f"{name} must be a finite, positive number.") from None
    if not math.isfinite(parsed) or parsed <= 0:
        raise ValueError(f"{name} must be a finite, positive number.")
    return parsed


class SqlApi:
    """Multi-connection SQL client over SQLAlchemy Core.

    Parameters default from the environment (see :mod:`sql_mcp.auth`); tests
    pass them explicitly. Engines are created lazily per named connection and
    reused; in-memory SQLite gets a ``StaticPool`` so every call shares one
    database.
    """

    def __init__(
        self,
        connections: Mapping[str, URL | str] | None = None,
        allow_writes: bool | None = None,
        max_rows: int | None = None,
        timeout: float | None = None,
        max_batch_rows: int = DEFAULT_MAX_BATCH_ROWS,
        max_script_statements: int = DEFAULT_MAX_SCRIPT_STATEMENTS,
        max_sql_length: int = DEFAULT_MAX_SQL_LENGTH,
        max_result_bytes: int = DEFAULT_MAX_RESULT_BYTES,
        max_cell_bytes: int = DEFAULT_MAX_CELL_BYTES,
        max_columns: int = DEFAULT_MAX_COLUMNS,
        writable_connections: set[str] | None = None,
        default_connection: str | None = None,
    ) -> None:
        raw = dict(connections) if connections is not None else auth.load_connections()
        if not raw:
            raise ValueError("At least one SQL connection must be configured.")
        if len(raw) > auth.MAX_CONNECTIONS:
            raise ValueError(
                f"SQL connection count exceeds the {auth.MAX_CONNECTIONS}-connection limit."
            )
        self._connections: dict[str, URL] = {}
        for name, url in raw.items():
            if not auth._valid_connection_name(name):
                raise ValueError("Connection names must be non-empty bounded strings.")
            try:
                parsed_url = make_url(url) if isinstance(url, str) else url
            except Exception:
                raise ValueError(
                    f"Connection {name!r} has an invalid SQL URL."
                ) from None
            if not isinstance(parsed_url, URL):
                raise ValueError(f"Connection {name!r} has an invalid SQL URL.")
            self._connections[name] = parsed_url
        configured_allow_writes = (
            allow_writes if allow_writes is not None else auth.allow_writes()
        )
        if not isinstance(configured_allow_writes, bool):
            raise ValueError("allow_writes must be a boolean.")
        self.allow_writes = configured_allow_writes
        self.max_rows = _positive_int(
            "max_rows", max_rows if max_rows is not None else auth.default_max_rows()
        )
        self.timeout = _positive_float(
            "timeout", timeout if timeout is not None else auth.default_timeout()
        )
        self.max_batch_rows = _positive_int("max_batch_rows", max_batch_rows)
        self.max_script_statements = _positive_int(
            "max_script_statements", max_script_statements
        )
        self.max_sql_length = _positive_int("max_sql_length", max_sql_length)
        self.max_result_bytes = _positive_int("max_result_bytes", max_result_bytes)
        self.max_cell_bytes = _positive_int("max_cell_bytes", max_cell_bytes)
        self.max_columns = _positive_int("max_columns", max_columns)
        unknown_writable = set(writable_connections or ()) - set(self._connections)
        if unknown_writable:
            raise ValueError("The SQL write allowlist contains unknown connections.")
        self._writable_connections = frozenset(writable_connections or ())
        if (
            default_connection is not None
            and default_connection not in self._connections
        ):
            raise ValueError("The configured default SQL connection is unknown.")
        self._default_connection = default_connection or next(iter(self._connections))
        self._engines: dict[str, Engine] = {}
        self._operation_locks: dict[Engine, threading.Lock] = {}
        self._engine_lock = threading.RLock()
        self._executor: concurrent.futures.ThreadPoolExecutor | None = None
        self._executor_lock = threading.Lock()
        self._futures: set[concurrent.futures.Future[Any]] = set()
        self._futures_lock = threading.Lock()
        self._max_workers = max(4, min(32, len(self._connections) * 4))
        self._worker_slots = threading.BoundedSemaphore(self._max_workers * 2)
        self._closed = False

    # ------------------------------------------------------------------ #
    # Connection registry
    # ------------------------------------------------------------------ #

    def connection_names(self) -> list[str]:
        """Names of all configured connections."""
        return list(self._connections)

    def default_connection(self) -> str:
        """The sole/first configured connection — used when none is named."""
        return self._default_connection

    def resolve_connection(self, connection: str | None = None) -> str:
        """Map an optional connection name to a configured one (or raise)."""
        if not connection:
            return self.default_connection()
        if connection not in self._connections:
            raise ValueError(
                "Unknown SQL connection. Use sql_admin 'connections' to inspect "
                "the configured registry."
            )
        return connection

    def dialect_spec(self, connection: str | None = None) -> DialectSpec | None:
        """The registered :class:`DialectSpec` for a connection, if any."""
        name = self.resolve_connection(connection)
        return dialect_for_url(self._connections[name])

    def engine(self, connection: str | None = None) -> Engine:
        """Lazily create (and cache) the Engine for a named connection."""
        name = self.resolve_connection(connection)
        with self._engine_lock:
            if self._closed:
                raise RuntimeError("SQL client is closed.")
            eng = self._engines.get(name)
            if eng is None:
                url = self._connections[name]
                spec = dialect_for_url(url)
                if spec is not None:
                    require_driver(spec)
                kwargs: dict[str, Any] = {
                    "hide_parameters": True,
                    "pool_pre_ping": True,
                }
                if _is_memory_sqlite(url):
                    kwargs.update(
                        {
                            "poolclass": StaticPool,
                            "connect_args": {"check_same_thread": False},
                        }
                    )
                eng = create_engine(url, **kwargs)
                self._engines[name] = eng
                if _is_memory_sqlite(url):
                    self._operation_locks[eng] = threading.Lock()
            return eng

    def dispose(self) -> None:
        """Dispose all pooled engines."""
        with self._executor_lock:
            self._closed = True
            executor, self._executor = self._executor, None
            if executor is not None:
                executor.shutdown(wait=False, cancel_futures=True)
        with self._futures_lock:
            has_active_workers = any(not future.done() for future in self._futures)
        with self._engine_lock:
            engines = list(self._engines.values())
            self._engines.clear()
            self._operation_locks.clear()
        for eng in engines:
            # Closing a DBAPI connection beneath an active cancellation worker can
            # crash native drivers (notably sqlite3). Detach the old pool instead;
            # the worker owns and releases its checked-out connection safely.
            eng.dispose(close=not has_active_workers)

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #

    def _submit(self, fn: Callable[[], Any]) -> concurrent.futures.Future[Any]:
        if not self._worker_slots.acquire(blocking=False):
            raise RuntimeError("SQL worker capacity is exhausted; retry later.")
        try:
            with self._executor_lock:
                if self._closed:
                    raise RuntimeError("SQL client is closed.")
                if self._executor is None:
                    self._executor = concurrent.futures.ThreadPoolExecutor(
                        max_workers=self._max_workers,
                        thread_name_prefix="sql-mcp",
                    )
                future = self._executor.submit(fn)
        except BaseException:
            self._worker_slots.release()
            raise
        with self._futures_lock:
            self._futures.add(future)
        return future

    def _complete_future(self, completed: concurrent.futures.Future[Any]) -> None:
        with self._futures_lock:
            self._futures.discard(completed)
        self._worker_slots.release()

    def _effective_timeout(self, timeout: float | None) -> float:
        if timeout is None:
            return self.timeout
        return min(_positive_float("timeout", timeout), self.timeout)

    def _run_with_timeout(
        self,
        fn: Callable[[], Any],
        timeout: float | None,
        on_timeout: Callable[[], None] | None = None,
    ) -> Any:
        """Run ``fn`` on a bounded shared worker pool with cancellation."""
        effective = self._effective_timeout(timeout)
        future = self._submit(fn)
        if _ASYNC_SQL_EXECUTION.get():
            return _AsyncSqlOperation(
                future,
                effective,
                on_timeout,
                self._complete_future,
            )
        try:
            return future.result(timeout=effective)
        except concurrent.futures.TimeoutError as exc:
            if on_timeout is not None:
                on_timeout()
            future.cancel()
            raise SqlTimeoutError(
                f"Statement exceeded the {effective:g}s timeout; cancellation was requested."
            ) from exc
        finally:
            if future.done():
                self._complete_future(future)
            else:
                future.add_done_callback(self._complete_future)

    @staticmethod
    def _cancel_driver_connection(driver_connection: Any) -> bool:
        for method_name in ("cancel", "interrupt"):
            method = getattr(driver_connection, method_name, None)
            if callable(method):
                try:
                    method()
                except Exception:
                    continue
                return True
        return False

    @staticmethod
    def _configure_statement_timeout(
        conn: Connection, timeout: float
    ) -> Callable[[], None] | None:
        """Install a native statement/round-trip timeout where available."""
        milliseconds = max(1, math.ceil(timeout * 1_000))
        if conn.dialect.name == "postgresql":
            result = conn.execute(
                text("SELECT set_config('statement_timeout', :value, true)"),
                {"value": f"{milliseconds}ms"},
            )
            result.close()
            return None
        if conn.dialect.name == "oracle":
            driver_connection = conn.connection.driver_connection
            if hasattr(driver_connection, "call_timeout"):
                previous = driver_connection.call_timeout
                driver_connection.call_timeout = milliseconds

                def reset() -> None:
                    driver_connection.call_timeout = previous

                return reset
        return None

    @staticmethod
    def _enable_read_only(conn: Connection) -> Callable[[], None] | None:
        """Enable database-enforced read-only mode where the dialect supports it."""
        dialect = conn.dialect.name
        if dialect == "sqlite":
            previous = bool(conn.exec_driver_sql("PRAGMA query_only").scalar())
            if not previous:
                conn.exec_driver_sql("PRAGMA query_only = ON")

            def reset() -> None:
                if not previous:
                    conn.exec_driver_sql("PRAGMA query_only = OFF")

            return reset
        if dialect in {"postgresql", "mysql", "mariadb", "oracle"}:
            conn.exec_driver_sql("SET TRANSACTION READ ONLY")
        return None

    def _run_on_connection(
        self,
        eng: Engine,
        operation: Callable[[Connection], Any],
        timeout: float | None,
        *,
        transactional: bool = False,
        read_only: bool = False,
    ) -> Any:
        """Run one connection-scoped operation with cancel and rollback semantics."""
        effective_timeout = self._effective_timeout(timeout)
        timed_out = threading.Event()
        state_lock = threading.Lock()
        state: dict[str, Any] = {}

        def cancel() -> None:
            timed_out.set()
            with state_lock:
                driver_connection = state.get("driver_connection")
            if driver_connection is not None:
                cancelled = self._cancel_driver_connection(driver_connection)
                with state_lock:
                    state["cancel_supported"] = cancelled

        def run() -> Any:
            with self._engine_lock:
                operation_lock = self._operation_locks.get(eng)
            lock = operation_lock or threading.Lock()
            with lock:
                if timed_out.is_set():
                    raise SqlTimeoutError("Statement expired before execution began.")
                with eng.connect() as conn:
                    with state_lock:
                        state["driver_connection"] = conn.connection.driver_connection
                    transaction = conn.begin() if transactional else None
                    reset_read_only: Callable[[], None] | None = None
                    reset_timeout: Callable[[], None] | None = None
                    try:
                        if read_only:
                            reset_read_only = self._enable_read_only(conn)
                        reset_timeout = self._configure_statement_timeout(
                            conn, effective_timeout
                        )
                        result = operation(conn)
                        if timed_out.is_set():
                            raise SqlTimeoutError(
                                "Statement completed after its timeout."
                            )
                        if transaction is not None:
                            transaction.commit()
                        return result
                    except BaseException:
                        if transaction is not None and transaction.is_active:
                            transaction.rollback()
                        raise
                    finally:
                        if reset_timeout is not None:
                            try:
                                reset_timeout()
                            except Exception:
                                conn.invalidate()
                        if reset_read_only is not None:
                            try:
                                reset_read_only()
                            except Exception:
                                conn.invalidate()
                        with state_lock:
                            cancel_supported = state.get("cancel_supported", False)
                        if timed_out.is_set() and not cancel_supported:
                            conn.invalidate()
                        with state_lock:
                            state.pop("driver_connection", None)

        return self._run_with_timeout(run, effective_timeout, on_timeout=cancel)

    def _effective_max_rows(self, max_rows: int | None) -> int:
        if max_rows is None:
            return self.max_rows
        return min(_positive_int("max_rows", max_rows), self.max_rows)

    def _validate_sql(self, sql: str) -> str:
        if not isinstance(sql, str):
            raise ValueError("sql must be a string.")
        if len(sql) > self.max_sql_length:
            raise ValueError(
                f"SQL length exceeds the {self.max_sql_length} character limit."
            )
        return sql

    def _json_safe_value(self, value: Any, _depth: int = 0) -> Any:
        if _depth > 10:
            raw = str(value).encode("utf-8")[: self.max_cell_bytes]
            return raw.decode("utf-8", errors="ignore") + "…"
        if isinstance(value, str):
            encoded_value = value.encode("utf-8")
            if len(encoded_value) <= self.max_cell_bytes:
                return value
            return (
                encoded_value[: self.max_cell_bytes].decode("utf-8", errors="ignore")
                + "…"
            )
        if value is None or isinstance(value, (bool, int)):
            normalized = value
        elif isinstance(value, float):
            normalized = value if math.isfinite(value) else str(value)
        elif isinstance(value, (dt.date, dt.time, dt.datetime)):
            normalized = value.isoformat()
        elif isinstance(value, (Decimal, uuid.UUID)):
            normalized = str(value)
        elif isinstance(value, enum.Enum):
            normalized = self._json_safe_value(value.value, _depth + 1)
        elif isinstance(value, (bytes, bytearray, memoryview)):
            raw = bytes(value)
            clipped = raw[: self.max_cell_bytes]
            normalized = {
                "encoding": "base64",
                "data": base64.b64encode(clipped).decode("ascii"),
                "truncated": len(raw) > len(clipped),
            }
        elif isinstance(value, Mapping):
            normalized = {}
            for index, (key, item) in enumerate(value.items()):
                if index >= 1_000:
                    normalized["__truncated__"] = True
                    break
                normalized[str(key)] = self._json_safe_value(item, _depth + 1)
        elif isinstance(value, (list, tuple, set, frozenset)):
            sequence = list(value)
            normalized = [
                self._json_safe_value(item, _depth + 1) for item in sequence[:1_000]
            ]
            if len(sequence) > 1_000:
                normalized.append({"__truncated__": True})
        else:
            normalized = str(value)

        encoded = json.dumps(normalized, ensure_ascii=False, default=str).encode(
            "utf-8"
        )
        if len(encoded) <= self.max_cell_bytes:
            return normalized
        text_value = str(normalized).encode("utf-8")[: self.max_cell_bytes]
        return text_value.decode("utf-8", errors="ignore") + "…"

    def _result_envelope(self, result: Any, cap: int) -> dict[str, Any]:
        """Fetch up to ``cap`` rows and describe columns (CONCEPT:SQ-OS.governance.sql-3)."""
        all_columns = [str(column) for column in result.keys()]
        columns_truncated = len(all_columns) > self.max_columns
        raw_columns = all_columns[: self.max_columns]
        seen: dict[str, int] = {}
        columns: list[str] = []
        for column in raw_columns:
            seen[column] = seen.get(column, 0) + 1
            columns.append(column if seen[column] == 1 else f"{column}__{seen[column]}")
        fetched = result.fetchmany(cap + 1)
        truncated = len(fetched) > cap or columns_truncated
        rows: list[dict[str, Any]] = []
        bytes_returned = 0
        for raw_row in fetched[:cap]:
            row = {
                column: self._json_safe_value(value)
                for column, value in zip(columns, raw_row, strict=False)
            }
            row_bytes = len(
                json.dumps(row, ensure_ascii=False, default=str).encode("utf-8")
            )
            if bytes_returned + row_bytes > self.max_result_bytes:
                truncated = True
                break
            rows.append(row)
            bytes_returned += row_bytes
        column_meta = [
            {
                "name": col,
                "source_name": raw_columns[index],
                "type": next(
                    (
                        type(raw_row[index]).__name__
                        for raw_row in fetched[:cap]
                        if raw_row[index] is not None
                    ),
                    "unknown",
                ),
            }
            for index, col in enumerate(columns)
        ]
        return {
            "columns": column_meta,
            "rows": rows,
            "row_count": len(rows),
            "truncated": truncated,
            "bytes_returned": bytes_returned,
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
        sql = self._validate_sql(sql)
        assert_read_only(sql)
        cap = self._effective_max_rows(max_rows)
        eng = self.engine(connection)

        def run(conn: Connection) -> dict[str, Any]:
            streaming = conn.execution_options(
                stream_results=True,
                max_row_buffer=cap + 1,
            )
            result = streaming.execute(text(sql), dict(params or {}))
            try:
                if not result.returns_rows:
                    raise ValueError("Read-only statement did not return rows.")
                return self._result_envelope(result, cap)
            finally:
                result.close()

        return self._run_on_connection(
            eng,
            run,
            timeout,
            read_only=True,
        )

    def explain(
        self,
        sql: str,
        params: Mapping[str, Any] | None = None,
        connection: str | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Return the dialect's query plan for a read-only statement."""
        sql = self._validate_sql(sql)
        assert_read_only(sql)
        name = self.resolve_connection(connection)
        spec = self.dialect_spec(name)
        if spec is None or spec.explain_prefix is None:
            dialect = spec.name if spec else self._connections[name].get_backend_name()
            raise ValueError(
                f"EXPLAIN is not safely supported for dialect {dialect!r} by "
                "this portable action; use the dialect's native plan tooling."
            )
        plan_sql = " ".join((spec.explain_prefix, sql))
        eng = self.engine(name)

        def run(conn: Connection) -> dict[str, Any]:
            result = conn.execute(text(plan_sql), dict(params or {}))
            try:
                if not result.returns_rows:
                    return {
                        "columns": [],
                        "rows": [],
                        "row_count": 0,
                        "truncated": False,
                        "bytes_returned": 0,
                    }
                return self._result_envelope(result, self.max_rows)
            finally:
                result.close()

        return self._run_on_connection(
            eng,
            run,
            timeout,
            read_only=True,
        )

    # ------------------------------------------------------------------ #
    # Execute (writes, gated)
    # ------------------------------------------------------------------ #

    def _assert_writes_allowed(self, connection: str | None = None) -> str:
        name = self.resolve_connection(connection)
        if not self.allow_writes:
            raise WritesDisabledError(
                "Writes are disabled: the server is read-only by default. "
                "Start it with SQL_ALLOW_WRITES=True to enable sql_execute."
            )
        if name not in self._writable_connections:
            raise WritesDisabledError(
                "Writes are disabled for this connection. Add its exact name to "
                "SQL_WRITE_CONNECTIONS after enabling SQL_ALLOW_WRITES."
            )
        return name

    def execute(
        self,
        sql: str,
        params: Mapping[str, Any] | list[Mapping[str, Any]] | None = None,
        connection: str | None = None,
        timeout: float | None = None,
        max_rows: int | None = None,
    ) -> dict[str, Any]:
        """Execute one DML/DDL statement in a transaction (writes gate applies).

        ``params`` may be a mapping (single execution) or a list of mappings
        (``executemany``). Returns the affected-row count.
        """
        from sql_mcp.safety import assert_no_transaction_control

        name = self._assert_writes_allowed(connection)
        sql = self._validate_sql(sql)
        assert_single_statement(sql)
        assert_no_transaction_control(sql)
        cap = self._effective_max_rows(max_rows)
        eng = self.engine(name)

        if isinstance(params, list):
            if len(params) > self.max_batch_rows:
                raise ValueError(
                    f"Parameter batch exceeds the {self.max_batch_rows} row limit."
                )
            if not params:
                return {"rowcount": 0}
            if not all(isinstance(item, Mapping) for item in params):
                raise ValueError("Every batch parameter entry must be an object.")
            bound_params: Mapping[str, Any] | list[Mapping[str, Any]] = [
                dict(item) for item in params
            ]
        elif params is None:
            bound_params = {}
        elif isinstance(params, Mapping):
            bound_params = dict(params)
        else:
            raise ValueError("params must be an object or a list of objects.")

        def run(conn: Connection) -> dict[str, Any]:
            result = conn.execute(text(sql), bound_params)
            try:
                response: dict[str, Any] = {"rowcount": result.rowcount}
                if result.returns_rows:
                    response.update(self._result_envelope(result, cap))
                return response
            finally:
                result.close()

        return self._run_on_connection(
            eng,
            run,
            timeout,
            transactional=True,
        )

    def execute_script(
        self,
        statements: list[str | Mapping[str, Any]],
        connection: str | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Run several statements in ONE transaction (all-or-nothing).

        Any failure rolls back every prior statement in the list.
        """
        from sql_mcp.safety import assert_no_transaction_control

        name = self._assert_writes_allowed(connection)
        if not statements:
            raise ValueError("'statements' must be a non-empty list of SQL strings.")
        if len(statements) > self.max_script_statements:
            raise ValueError(
                f"Script exceeds the {self.max_script_statements} statements limit."
            )
        prepared: list[tuple[str, Mapping[str, Any] | list[Mapping[str, Any]]]] = []
        for entry in statements:
            if isinstance(entry, str):
                statement, entry_params = entry, {}
            elif isinstance(entry, Mapping):
                statement = entry.get("sql")
                entry_params = entry.get("params")
                if entry_params is None:
                    entry_params = {}
                if not isinstance(statement, str):
                    raise ValueError(
                        "Every script object requires a string 'sql' field."
                    )
                if isinstance(entry_params, list):
                    if len(entry_params) > self.max_batch_rows:
                        raise ValueError(
                            f"Parameter batch exceeds the {self.max_batch_rows} row limit."
                        )
                    if not entry_params or not all(
                        isinstance(item, Mapping) for item in entry_params
                    ):
                        raise ValueError(
                            "Script batch params must be a non-empty list of objects."
                        )
                    entry_params = [dict(item) for item in entry_params]
                elif isinstance(entry_params, Mapping):
                    entry_params = dict(entry_params)
                else:
                    raise ValueError(
                        "Script params must be an object or list of objects."
                    )
            else:
                raise ValueError("Every script entry must be a SQL string or object.")
            statement = self._validate_sql(statement)
            assert_single_statement(statement)
            assert_no_transaction_control(statement)
            prepared.append((statement, entry_params))
        dialect = self.dialect_spec(name)
        dialect_name = (
            dialect.name
            if dialect is not None
            else self._connections[name].get_backend_name()
        )
        if len(prepared) > 1 and dialect_name in {"mysql", "oracle"}:
            from sql_mcp.safety import first_keyword, strip_literals_and_comments

            ddl_keywords = {"alter", "create", "drop", "rename", "truncate"}
            if any(
                first_keyword(strip_literals_and_comments(statement)) in ddl_keywords
                for statement, _ in prepared
            ):
                raise ValueError(
                    f"Dialect {dialect_name!r} implicitly commits DDL; mixed or "
                    "multi-statement DDL scripts cannot be guaranteed atomic. "
                    "Execute each DDL statement explicitly."
                )
        eng = self.engine(name)

        def run(conn: Connection) -> dict[str, Any]:
            rowcounts: list[int] = []
            returned: list[dict[str, Any] | None] = []
            has_returned_rows = False
            for statement, entry_params in prepared:
                result = conn.execute(text(statement), entry_params)
                try:
                    rowcounts.append(result.rowcount)
                    if result.returns_rows:
                        returned.append(self._result_envelope(result, self.max_rows))
                        has_returned_rows = True
                    else:
                        returned.append(None)
                finally:
                    result.close()
            response: dict[str, Any] = {
                "statements": len(prepared),
                "rowcounts": rowcounts,
                "atomic": True,
            }
            if has_returned_rows:
                response["results"] = returned
            return response

        return self._run_on_connection(
            eng,
            run,
            timeout,
            transactional=True,
        )

    # ------------------------------------------------------------------ #
    # Schema reflection
    # ------------------------------------------------------------------ #

    def _reflection(
        self,
        connection: str | None,
        operation: Callable[[Any], Any],
        timeout: float | None = None,
    ) -> Any:
        eng = self.engine(connection)

        def run(conn: Connection) -> Any:
            return operation(inspect(conn))

        return self._run_on_connection(
            eng,
            run,
            timeout,
            read_only=True,
        )

    def _page(self, values: Any, limit: int | None, offset: int) -> list[Any]:
        if isinstance(offset, bool):
            raise ValueError("offset must be a non-negative integer.")
        try:
            start = int(offset)
        except (TypeError, ValueError, OverflowError):
            raise ValueError("offset must be a non-negative integer.") from None
        if start < 0:
            raise ValueError("offset must be a non-negative integer.")
        cap = self._effective_max_rows(limit)
        return list(values)[start : start + cap]

    def _column_records(self, columns: Any) -> list[dict[str, Any]]:
        return [
            {
                "name": column["name"],
                "type": str(column["type"]),
                "nullable": bool(column.get("nullable", True)),
                "default": self._json_safe_value(column.get("default")),
                "primary_key": bool(column.get("primary_key", False)),
                "autoincrement": self._json_safe_value(column.get("autoincrement")),
                "identity": self._json_safe_value(column.get("identity")),
                "computed": self._json_safe_value(column.get("computed")),
                "comment": self._json_safe_value(column.get("comment")),
            }
            for column in list(columns)[: self.max_rows]
        ]

    def _index_records(self, indexes: Any) -> list[dict[str, Any]]:
        return [
            {
                "name": entry.get("name"),
                "columns": list(entry.get("column_names") or []),
                "expressions": self._json_safe_value(entry.get("expressions") or []),
                "include_columns": list(entry.get("include_columns") or []),
                "unique": bool(entry.get("unique", False)),
                "dialect_options": self._json_safe_value(
                    entry.get("dialect_options") or {}
                ),
            }
            for entry in list(indexes)[: self.max_rows]
        ]

    def _foreign_key_records(self, foreign_keys: Any) -> list[dict[str, Any]]:
        return [
            {
                "name": entry.get("name"),
                "columns": list(entry.get("constrained_columns") or []),
                "referred_schema": entry.get("referred_schema"),
                "referred_table": entry.get("referred_table"),
                "referred_columns": list(entry.get("referred_columns") or []),
                "options": self._json_safe_value(entry.get("options") or {}),
            }
            for entry in list(foreign_keys)[: self.max_rows]
        ]

    def list_schemas(
        self,
        connection: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[str]:
        """List schema names."""
        return self._reflection(
            connection,
            lambda inspector: self._page(
                inspector.get_schema_names(), limit, offset
            ),
        )

    def list_tables(
        self,
        schema: str | None = None,
        connection: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[str]:
        """List table names (optionally within a schema)."""
        return self._reflection(
            connection,
            lambda inspector: self._page(
                inspector.get_table_names(schema=schema), limit, offset
            ),
        )

    def list_views(
        self,
        schema: str | None = None,
        connection: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[str]:
        """List view names (optionally within a schema)."""
        return self._reflection(
            connection,
            lambda inspector: self._page(
                inspector.get_view_names(schema=schema), limit, offset
            ),
        )

    def list_materialized_views(
        self,
        schema: str | None = None,
        connection: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[str]:
        """List materialized views when the dialect exposes them."""

        def reflect(inspector: Any) -> Any:
            method = getattr(inspector, "get_materialized_view_names", None)
            if method is None:
                values = []
            else:
                try:
                    values = method(schema=schema)
                except NotImplementedError:
                    values = []
            return self._page(values, limit, offset)

        return self._reflection(connection, reflect)

    def list_sequences(
        self,
        schema: str | None = None,
        connection: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[str]:
        """List sequence names when the dialect supports sequences."""

        def reflect(inspector: Any) -> Any:
            try:
                values = inspector.get_sequence_names(schema=schema)
            except NotImplementedError:
                values = []
            return self._page(values, limit, offset)

        return self._reflection(connection, reflect)

    def list_columns(
        self, table: str, schema: str | None = None, connection: str | None = None
    ) -> list[dict[str, Any]]:
        """Describe a table's columns: name, type, nullable, default."""
        return self._reflection(
            connection,
            lambda inspector: self._column_records(
                inspector.get_columns(table, schema=schema)
            ),
        )

    def list_indexes(
        self, table: str, schema: str | None = None, connection: str | None = None
    ) -> list[dict[str, Any]]:
        """List a table's indexes (name, columns, uniqueness)."""
        return self._reflection(
            connection,
            lambda inspector: self._index_records(
                inspector.get_indexes(table, schema=schema)
            ),
        )

    def list_foreign_keys(
        self, table: str, schema: str | None = None, connection: str | None = None
    ) -> list[dict[str, Any]]:
        """List a table's foreign keys (columns -> referred table/columns)."""
        return self._reflection(
            connection,
            lambda inspector: self._foreign_key_records(
                inspector.get_foreign_keys(table, schema=schema)
            ),
        )

    def list_constraints(
        self,
        table: str,
        schema: str | None = None,
        connection: str | None = None,
    ) -> dict[str, Any]:
        """Return primary-key, unique, and check constraints for a table."""

        def reflect(inspector: Any) -> dict[str, Any]:
            primary_key = inspector.get_pk_constraint(table, schema=schema)
            try:
                unique = inspector.get_unique_constraints(table, schema=schema)
            except NotImplementedError:
                unique = []
            try:
                checks = inspector.get_check_constraints(table, schema=schema)
            except NotImplementedError:
                checks = []
            return {
                "primary_key": {
                    "name": primary_key.get("name"),
                    "columns": list(primary_key.get("constrained_columns") or []),
                    "dialect_options": self._json_safe_value(
                        primary_key.get("dialect_options") or {}
                    ),
                },
                "unique": [
                    {
                        "name": item.get("name"),
                        "columns": list(item.get("column_names") or []),
                        "dialect_options": self._json_safe_value(
                            item.get("dialect_options") or {}
                        ),
                    }
                    for item in list(unique)[: self.max_rows]
                ],
                "check": [
                    {
                        "name": item.get("name"),
                        "sqltext": self._json_safe_value(item.get("sqltext")),
                        "dialect_options": self._json_safe_value(
                            item.get("dialect_options") or {}
                        ),
                    }
                    for item in list(checks)[: self.max_rows]
                ],
            }

        return self._reflection(connection, reflect)

    def view_definition(
        self,
        view: str,
        schema: str | None = None,
        connection: str | None = None,
    ) -> str | None:
        """Return a view's SQL definition when reflection supports it."""

        def reflect(inspector: Any) -> str | None:
            try:
                definition = inspector.get_view_definition(view, schema=schema)
            except NotImplementedError:
                return None
            if definition is None:
                return None
            encoded = str(definition).encode("utf-8")
            return encoded[: self.max_result_bytes].decode("utf-8", errors="ignore")

        return self._reflection(connection, reflect)

    def table_comment(
        self,
        table: str,
        schema: str | None = None,
        connection: str | None = None,
    ) -> dict[str, Any]:
        """Return a table comment and dialect options when supported."""

        def reflect(inspector: Any) -> dict[str, Any]:
            try:
                comment = inspector.get_table_comment(table, schema=schema)
            except NotImplementedError:
                return {"text": None, "dialect_options": {}}
            return {
                "text": self._json_safe_value(comment.get("text")),
                "dialect_options": self._json_safe_value(
                    comment.get("dialect_options") or {}
                ),
            }

        return self._reflection(connection, reflect)

    def table_ddl(
        self, table: str, schema: str | None = None, connection: str | None = None
    ) -> str:
        """Reflect a table and render its CREATE TABLE DDL for this dialect."""
        eng = self.engine(connection)

        def run(conn: Connection) -> str:
            metadata = MetaData()
            reflected = Table(table, metadata, schema=schema, autoload_with=conn)
            ddl = str(CreateTable(reflected).compile(eng)).strip()
            return ddl.encode("utf-8")[: self.max_result_bytes].decode(
                "utf-8", errors="ignore"
            )

        return self._run_on_connection(eng, run, None, read_only=True)

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

        def run(conn: Connection) -> dict[str, Any]:
            metadata = MetaData()
            reflected = Table(table, metadata, schema=schema, autoload_with=conn)
            result = conn.execute(select(reflected).limit(cap + 1))
            try:
                return self._result_envelope(result, cap)
            finally:
                result.close()

        return self._run_on_connection(
            eng,
            run,
            timeout,
            read_only=True,
        )

    def schema_catalog(
        self,
        schema: str | None = None,
        connection: str | None = None,
        max_objects: int | None = None,
        include_views: bool = True,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Return a bounded schema snapshot using one cached Inspector."""
        name = self.resolve_connection(connection)
        eng = self.engine(name)
        cap = self._effective_max_rows(max_objects)

        def run(conn: Connection) -> dict[str, Any]:
            inspector = inspect(conn)
            table_names = list(inspector.get_table_names(schema=schema))
            view_names = (
                list(inspector.get_view_names(schema=schema)) if include_views else []
            )
            candidates = [("table", item) for item in table_names] + [
                ("view", item) for item in view_names
            ]
            objects: list[dict[str, Any]] = []
            bytes_returned = 0
            truncated = len(candidates) > cap
            for object_type, object_name in candidates[:cap]:
                if object_type == "view":
                    definition = inspector.get_view_definition(
                        object_name, schema=schema
                    )
                    record = {
                        "name": object_name,
                        "type": "view",
                        "definition": self._json_safe_value(definition),
                    }
                else:
                    record = {
                        "name": object_name,
                        "type": "table",
                        "columns": self._column_records(
                            inspector.get_columns(object_name, schema=schema)
                        ),
                        "indexes": self._index_records(
                            inspector.get_indexes(object_name, schema=schema)
                        ),
                        "foreign_keys": self._foreign_key_records(
                            inspector.get_foreign_keys(object_name, schema=schema)
                        ),
                    }
                record_bytes = len(
                    json.dumps(record, ensure_ascii=False, default=str).encode("utf-8")
                )
                if bytes_returned + record_bytes > self.max_result_bytes:
                    truncated = True
                    break
                objects.append(record)
                bytes_returned += record_bytes
            return {
                "connection": name,
                "schema": schema,
                "dialect": eng.dialect.name,
                "objects": objects,
                "object_count": len(objects),
                "truncated": truncated,
                "bytes_returned": bytes_returned,
            }

        return self._run_on_connection(eng, run, timeout, read_only=True)

    # ------------------------------------------------------------------ #
    # Admin
    # ------------------------------------------------------------------ #

    def ping(self, connection: str | None = None) -> dict[str, Any]:
        """Connection test: ``SELECT 1`` round-trip with latency."""
        import time

        name = self.resolve_connection(connection)
        eng = self.engine(name)
        started = time.monotonic()

        def run(conn: Connection) -> dict[str, Any]:
            result = conn.execute(text("SELECT 1"))
            result.close()
            return {
                "connection": name,
                "ok": True,
                "latency_ms": round((time.monotonic() - started) * 1000, 2),
            }

        return self._run_on_connection(eng, run, None, read_only=True)

    def server_version(self, connection: str | None = None) -> dict[str, Any]:
        """Report the server version (dialect SQL, else SQLAlchemy's probe)."""
        name = self.resolve_connection(connection)
        spec = self.dialect_spec(name)
        eng = self.engine(name)

        def run(conn: Connection) -> dict[str, Any]:
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

        return self._run_on_connection(eng, run, None, read_only=True)

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
        active_sql = spec.active_connections_sql

        def run(conn: Connection) -> dict[str, Any]:
            result = conn.execute(text(active_sql))
            try:
                envelope = self._result_envelope(result, self.max_rows)
            finally:
                result.close()
            envelope.update({"connection": name, "supported": True})
            return envelope

        return self._run_on_connection(eng, run, None, read_only=True)

    def ping_all(self) -> list[dict[str, Any]]:
        """Check every configured connection without exposing credentials."""
        results: list[dict[str, Any]] = []
        for name in self.connection_names():
            try:
                results.append(self.ping(name))
            except Exception as exc:
                results.append(
                    {
                        "connection": name,
                        "ok": False,
                        "error": type(exc).__name__,
                    }
                )
        return results

    def pool_status(self, connection: str | None = None) -> dict[str, Any]:
        """Return non-secret SQLAlchemy pool pressure metrics."""
        name = self.resolve_connection(connection)
        pool = self.engine(name).pool

        def metric(method_name: str) -> int | None:
            method = getattr(pool, method_name, None)
            if not callable(method):
                return None
            try:
                return int(method())
            except (NotImplementedError, TypeError, ValueError):
                return None

        return {
            "connection": name,
            "pool": type(pool).__name__,
            "size": metric("size"),
            "checked_in": metric("checkedin"),
            "checked_out": metric("checkedout"),
            "overflow": metric("overflow"),
        }

    def capabilities(self, connection: str | None = None) -> dict[str, Any]:
        """Report portable and dialect-specific behavior for one connection."""
        name = self.resolve_connection(connection)
        spec = self.dialect_spec(name)
        dialect = spec.name if spec else self._connections[name].get_backend_name()
        return {
            "connection": name,
            "dialect": dialect,
            "sqlalchemy_scheme": self._connections[name].drivername,
            "read_only_transactions": dialect
            in {"sqlite", "postgres", "mysql", "oracle"},
            "explain": bool(spec and spec.explain_prefix),
            "active_connections": bool(spec and spec.active_connections_sql),
            "transactional_ddl": dialect in {"sqlite", "postgres", "mssql"},
            "materialized_views": dialect in {"postgres", "oracle", "mssql"},
            "sequences": dialect in {"postgres", "oracle", "mssql"},
            "distributed_transactions": False,
            "writes_enabled": bool(self.allow_writes)
            and name in self._writable_connections,
        }

    def describe_connections(self) -> list[dict[str, Any]]:
        """Describe configured connections with passwords redacted."""
        described = []
        for name, url in self._connections.items():
            spec = dialect_for_url(url)
            redacted_query = {
                key: (
                    "***"
                    if any(part in key.lower() for part in _SENSITIVE_QUERY_PARTS)
                    else value
                )
                for key, value in url.query.items()
            }
            safe_url = url.set(query=redacted_query)
            described.append(
                {
                    "name": name,
                    "url": safe_url.render_as_string(hide_password=True),
                    "dialect": spec.name if spec else url.get_backend_name(),
                    "host": url.host,
                    "port": url.port,
                    "database": url.database,
                    "username": url.username,
                    "default": name == self.default_connection(),
                    "writes_enabled": bool(self.allow_writes)
                    and name in self._writable_connections,
                }
            )
        return described
