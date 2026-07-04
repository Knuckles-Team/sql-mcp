---
name: sql-mcp-schema-inspection
description: >-
  Reflect relational database structure over the sql-mcp MCP server — list
  schemas, tables, and views; describe a table's columns, indexes, and foreign
  keys; render CREATE TABLE DDL; and preview sample rows. Use when the agent
  must discover what a database contains before querying it, map relationships
  between tables, or produce dialect-correct DDL. Do NOT use to run arbitrary
  SQL (use sql-mcp-query-execution) or to push the reflected structure into the
  knowledge graph (use sql-mcp-knowledge-graph-ingestion).
license: MIT
tags: [sql, database, schema, reflection, mcp]
metadata:
  author: Genius
  version: '0.1.0'
---
# SQL Schema Inspection

Read-only reflection of the live schema of any configured connection through the
**sql-mcp** MCP server, built on SQLAlchemy's inspector. Table/column identifiers
are quoted by SQLAlchemy, never interpolated by hand, so reflection is safe on
any dialect (Postgres, MySQL/MariaDB, MSSQL, Oracle, SQLite).

## When to use
- Enumerate schemas, tables, or views (optionally within a schema).
- Describe a table: columns (name/type/nullable/default/PK), indexes, foreign keys.
- Reflect a table's `CREATE TABLE` DDL for the target dialect.
- Preview a handful of rows from a table (`sample`) to understand its shape.

## When NOT to use
- Running SELECTs, DML, or DDL statements → `sql-mcp-query-execution`.
- Ingesting the schema as typed graph nodes → `sql-mcp-knowledge-graph-ingestion`.

## Prerequisites & environment
Connect via the `mcp-client` skill against the **`sql-mcp`** MCP server. The same
connection variables as query execution apply (`SQL_CONNECTIONS` / `SQL_URL` /
discrete `SQL_DIALECT`+host fields); reflection needs no write access. See
`sql-mcp-query-execution` for the full env matrix.

## Tools & actions
The condensed `sql_schema` tool takes an `action` + `params_json` **JSON string**
and an optional `connection`.

| Tool | Actions |
|------|---------|
| `sql_schema` | `schemas`, `tables`, `views`, `columns`, `indexes`, `foreign_keys`, `ddl`, `sample` |

### Key parameters
- `schema` — optional namespace for `tables`/`views`/`columns`/… (omit for the default).
- `table` — required for `columns`, `indexes`, `foreign_keys`, `ddl`, `sample`.
- `limit` — row preview count for `sample` (clamped to the server row cap).

## Recipes (`params_json`)
List tables in a schema:
```json
{"schema":"public"}
```
Describe a table's columns:
```json
{"table":"users","schema":"public"}
```
Read the foreign keys off a table (to map relationships):
```json
{"table":"orders","schema":"public"}
```
Reflect CREATE TABLE DDL:
```json
{"table":"users","schema":"public"}
```
Preview 5 rows:
```json
{"table":"users","limit":5,"schema":"public"}
```

## Gotchas
- `params_json` is a **string** of JSON, not an object.
- `schema` is optional; when omitted the dialect's default schema is used —
  which differs per engine (`public` on Postgres, the database name on MySQL, etc.).
- `sample` still obeys the server row cap: `limit` is clamped to `SQL_MAX_ROWS`.
- `ddl` reflects the table via SQLAlchemy and re-emits DDL for **that** dialect;
  it is a faithful round-trip, not the server's verbatim stored definition.
- Very wide schemas: list `tables` first, then describe the specific tables you
  need — do not fan out `columns` across every table blindly.

## Related
- `sql-mcp-query-execution` — query the objects you discovered here.
- `sql-mcp-knowledge-graph-ingestion` — persist this reflected structure into the KG.
