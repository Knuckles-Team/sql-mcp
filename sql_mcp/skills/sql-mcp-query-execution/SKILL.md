---
name: sql-mcp-query-execution
description: >-
  Run parameterized SQL over the sql-mcp MCP server — read-only SELECT/CTE
  queries and query plans, plus gated DML/DDL writes and multi-statement
  scripts. Use when the agent must query a relational database (Postgres,
  MySQL/MariaDB, MSSQL, Oracle, SQLite), read rows with a row cap and timeout,
  inspect a query plan with EXPLAIN, or (when writes are enabled) run an
  INSERT/UPDATE/DELETE/DDL statement in a transaction. Do NOT use for schema
  discovery (use sql-mcp-schema-inspection) or for pushing schema into the
  knowledge graph (use sql-mcp-knowledge-graph-ingestion).
license: MIT
tags: [sql, database, query, sqlalchemy, mcp]
metadata:
  author: Genius
  version: '0.1.0'
---
# SQL Query Execution

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

## Tools & actions
Each condensed tool takes an `action` + a `params_json` **JSON string** and an
optional `connection` naming a configured connection (empty = default).

| Tool | Actions |
|------|---------|
| `sql_query` | `execute` (read-only SELECT/CTE), `explain` (query plan) |
| `sql_execute` | `execute` (one DML/DDL stmt), `script` (statements in one txn) |

## Recipes (`params_json`)
Read rows with bound parameters and a row cap:
```json
{"sql":"SELECT id, email FROM users WHERE status = :s ORDER BY id LIMIT :n","params":{"s":"active","n":50},"max_rows":50,"timeout":10}
```
Query plan for a statement:
```json
{"sql":"SELECT * FROM orders WHERE customer_id = :c","params":{"c":42}}
```
`executemany` insert (writes must be enabled), one statement, list of param dicts:
```json
{"sql":"INSERT INTO audit (actor, action) VALUES (:a, :act)","params":[{"a":"svc","act":"login"},{"a":"svc","act":"logout"}]}
```
All-or-nothing script (rolls back on any failure):
```json
{"statements":["CREATE TABLE t (id INTEGER PRIMARY KEY)","INSERT INTO t (id) VALUES (1)"]}
```

## Gotchas
- `params_json` is a **string** of JSON, not an object — serialize it.
- Reads must be a **single** statement and read-only (`SELECT`/`WITH`/`EXPLAIN`/
  `SHOW`/`DESCRIBE`/`PRAGMA`/`VALUES`); anything else is rejected by the safety gate.
- `sql_execute` raises `WritesDisabledError` unless `SQL_ALLOW_WRITES=True`.
- `max_rows` is **clamped** to the server cap; a truncated read sets
  `"truncated": true` in the envelope — page with `LIMIT`/`OFFSET`, do not raise the cap blindly.
- `EXPLAIN` is unsupported on MSSQL (it needs `SET SHOWPLAN` on a dedicated session).

## Related
- `sql-mcp-schema-inspection` — discover the objects before you query them.
- `sql-mcp-knowledge-graph-ingestion` — mirror the reflected schema into the KG.
