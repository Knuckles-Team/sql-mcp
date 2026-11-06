# Sql Mcp Schema Inspection

Reflect relational database structure over the sql-mcp MCP server — list schemas, tables, and views; describe a table's columns, indexes, and foreign keys; render CREATE TABLE DDL; and preview sample rows. Use when the agent must discover what a database contains before querying it, map relationships between tables, or produce dialect-correct DDL. Do NOT use to run arbitrary SQL (use sql-mcp-query-execution) or to push the reflected structure into the knowledge graph (use sql-mcp-knowledge-graph-ingestion).

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

## Tools
One typed tool per operation, each with an optional `connection`.

| Tool | Purpose |
|------|---------|
| `sql_list_schemas` / `sql_list_tables` / `sql_list_views` | Names, with optional `schema`, `limit`, `offset` |
| `sql_list_materialized_views` / `sql_list_sequences` | Materialized views and sequences |
| `sql_list_columns` / `sql_list_indexes` / `sql_list_foreign_keys` / `sql_list_constraints` | Describe one `table` |
| `sql_table_ddl` / `sql_table_comment` / `sql_view_definition` | DDL, comment and view SQL |
| `sql_sample_rows` | Preview rows (`limit` clamped to the server row cap) |
| `sql_schema_catalog` | Bounded catalog of a schema (`max_objects`, `include_views`) |

### Key parameters
- `schema` is an optional namespace (omit for the default).
- `table` is required for the table-scoped tools; `view` for `sql_view_definition`.
- `limit` is the row preview count for `sql_sample_rows`.

## Recipes
List tables in a schema: `sql_list_tables` with `schema="public"`.

Describe a table: `sql_list_columns` with `table="users"`, `schema="public"`; map relationships with `sql_list_foreign_keys` on `table="orders"`.

Reflect CREATE TABLE DDL: `sql_table_ddl` with `table="users"`. Preview 5 rows: `sql_sample_rows` with `table="users"`, `limit=5`.

## Gotchas
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
