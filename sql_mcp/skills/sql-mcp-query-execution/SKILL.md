---
name: sql-mcp-query-execution
skill_type: skill
description: >-
  Run parameterized SQL over the sql-mcp MCP server: read-only SELECT/CTE queries, query plans, and gated DML/DDL writes and scripts. Use to read rows with a row cap and timeout, check a plan or, when writes are enabled, change data. Not for schema discovery (sql-mcp-schema-inspection) or KG ingest (sql-mcp-knowledge-graph-ingestion).
license: MIT
tags: [sql, database, query, sqlalchemy, mcp]
metadata:
  author: Knuckles-Team
  version: '0.1.0'
---
# SQL Query Execution

Scope: Run parameterized SQL over the sql-mcp MCP server — read-only SELECT/CTE queries and query plans, plus gated DML/DDL writes and multi-statement scripts. Use when the agent must query a relational database (Postgres, MySQL/MariaDB, MSSQL, Oracle, SQLite), read rows with a row cap and timeout, inspect a query plan with EXPLAIN, or (when writes are enabled) run an INSERT/UPDATE/DELETE/DDL statement in a transaction. Do NOT use for schema discovery (use sql-mcp-schema-inspection) or for pushing schema into the knowledge graph (use sql-mcp-knowledge-graph-ingestion).

Parameterized read and write access to any configured SQL connection through the
**sql-mcp** MCP server. Every statement runs through SQLAlchemy `text()` with
**bound `:name` parameters** — values are never interpolated into the SQL string.
Reads are bounded by a server row cap and per-call timeout; writes are gated off
by default.

## When to use
- Run a read-only `SELECT`/`WITH` (CTE) and get back a bounded row envelope.
- Get a dialect query plan for a statement (`EXPLAIN`).
- Run a single DML/DDL statement or an all-or-nothing multi-statement script
  **when the server was started with writes enabled**.

## When NOT to use
- Listing schemas/tables/columns/indexes/FKs or reflecting DDL →
  `sql-mcp-schema-inspection`.
- Mirroring the schema into the knowledge graph →
  `sql-mcp-knowledge-graph-ingestion`.
- Inline, string-concatenated SQL — always use `:name` binds.

## Prerequisites & environment
Connect via the `mcp-client` skill against the **`sql-mcp`** MCP server.

| Variable | Required | Notes |
|----------|----------|-------|
| `SQL_CONNECTIONS` | one of these | JSON map `name -> DSN` or connection object |
| `SQL_URL` | one of these | single DSN, registered as connection `default` |
| `SQL_DIALECT` + `SQL_HOST`/`SQL_PORT`/`SQL_USERNAME`/`SQL_PASSWORD`/`SQL_DATABASE` | one of these | discrete fields, registered as `default` |
| `SQL_ALLOW_WRITES` | optional | `True` enables `sql_execute` (default read-only) |
| `SQL_MAX_ROWS` | optional | per-call row cap (default 500) |
| `SQL_TIMEOUT_SECONDS` | optional | per-call statement timeout (default 30) |

With nothing configured the server registers a zero-infra in-memory SQLite
connection named `memory`, so the tools work out of the box.

## Steps

1. Discover the objects first by calling `sql_list_tables` with the target `connection`. Verify the tables you will query are listed.
2. Check cost on large reads by calling `sql_explain` with `sql` and `params`. Verify a plan comes back (not supported on MSSQL).
3. Read rows by calling `sql_query` with a bound `sql` using `:name` parameters, plus `params`, `max_rows` and `timeout`. Verify the envelope has rows and check whether `truncated` is true.
4. Change data only when `SQL_ALLOW_WRITES=True` and approved, by calling `sql_execute` or `sql_execute_script`. Verify the reported affected row count matches the intent.
5. Confirm the write by calling `sql_query` on the changed rows. Verify the expected values are present.

## Failure recovery

| Failure | Cause | Recovery |
|---------|-------|----------|
| `WritesDisabledError` | `SQL_ALLOW_WRITES` is not `True` on the server | Ask the operator to enable `SQL_ALLOW_WRITES=True` for the server, or keep the task read-only with `sql_query` |
| Statement rejected by the safety gate | `sql_query` received a write or several statements | Send one read-only SELECT or WITH statement, or move the change to `sql_execute` |
| Result has `truncated` true | Row cap reached | Page with `LIMIT` and `OFFSET` in `sql` and keep `max_rows` at or below the server cap |

## Tools
One typed tool per operation. Every tool takes an optional `connection` naming a configured connection (empty = default).

| Tool | Purpose |
|------|---------|
| `sql_query` | Read-only SELECT/CTE with bound `params`, `max_rows` and `timeout` |
| `sql_explain` | Query plan for a read-only statement |
| `sql_execute` | One DML/DDL statement in a transaction; `params` may be a list for executemany |
| `sql_execute_script` | A list of statements in one all-or-nothing transaction |

## Recipes
Read rows with bound parameters and a row cap: call `sql_query` with `sql="SELECT id, email FROM users WHERE status = :s ORDER BY id LIMIT :n"`, `params={"s": "active", "n": 50}`, `max_rows=50`, `timeout=10`.

Query plan: call `sql_explain` with `sql="SELECT * FROM orders WHERE customer_id = :c"`, `params={"c": 42}`.

`executemany` insert (writes must be enabled): call `sql_execute` with `sql="INSERT INTO audit (actor, action) VALUES (:a, :act)"` and `params=[{"a": "svc", "act": "login"}, {"a": "svc", "act": "logout"}]`.

All-or-nothing script (rolls back on any failure): call `sql_execute_script` with `statements=["CREATE TABLE t (id INTEGER PRIMARY KEY)", "INSERT INTO t (id) VALUES (1)"]`.

## Gotchas
- Reads must be a **single** statement and read-only (`SELECT`/`WITH`/`EXPLAIN`/
  `SHOW`/`DESCRIBE`/`PRAGMA`/`VALUES`); anything else is rejected by the safety gate.
- `sql_execute` raises `WritesDisabledError` unless `SQL_ALLOW_WRITES=True`.
- `max_rows` is **clamped** to the server cap; a truncated read sets
  `"truncated": true` in the envelope — page with `LIMIT`/`OFFSET`, do not raise the cap blindly.
- `EXPLAIN` is unsupported on MSSQL (it needs `SET SHOWPLAN` on a dedicated session).

## Related
- `sql-mcp-schema-inspection` — discover the objects before you query them.
- `sql-mcp-knowledge-graph-ingestion` — mirror the reflected schema into the KG.
