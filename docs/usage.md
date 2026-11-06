# Usage

## The MCP tools

One typed tool per operation. Every tool takes an optional `connection` naming one of the
configured connections (defaults to the sole/first one).

### Queries (read-only)

| Tool | Arguments | Returns |
|---|---|---|
| `sql_query` | `sql`, `params`, `max_rows`, `timeout` | `{columns, rows, row_count, truncated}` |
| `sql_explain` | `sql`, `params` | the dialect's query plan |

Statements must be single and read-only (`SELECT`/`WITH`/`EXPLAIN`/`SHOW`/
`DESCRIBE`/`PRAGMA`/`VALUES`); values bind via `:name` parameters. `max_rows` is
clamped to the server's `SQL_MAX_ROWS`. EXPLAIN is unavailable on MSSQL (it has
no statement-level EXPLAIN).

### Writes (gated)

Require the server to run with `SQL_ALLOW_WRITES=True`; the default is read-only and
there is **no per-call override**.

| Tool | Arguments | Returns |
|---|---|---|
| `sql_execute` | `sql`, `params` (dict, or list of dicts for executemany) | `{rowcount}` |
| `sql_execute_script` | `statements`: ONE all-or-nothing transaction | `{statements, rowcounts}` |

### Schema reflection

`sql_list_schemas`, `sql_list_tables`, `sql_list_views`, `sql_list_materialized_views`,
`sql_list_sequences` (optional `schema`, `limit`, `offset`); `sql_list_columns`,
`sql_list_indexes`, `sql_list_foreign_keys`, `sql_list_constraints`, `sql_table_ddl`,
`sql_table_comment` (`table`, optional `schema`); `sql_view_definition` (`view`);
`sql_sample_rows` (`table`, `limit` clamped to the row cap); `sql_schema_catalog`
(bounded catalog of a schema).

### Health and registry

| Tool | Returns |
|---|---|
| `sql_ping` / `sql_ping_all` | connection test and latency |
| `sql_server_version` | server version per dialect |
| `sql_active_connections` | server sessions (SQLite reports unsupported) |
| `sql_describe_connections` / `sql_connection_names` / `sql_default_connection` / `sql_resolve_connection` | configured connections, passwords redacted |
| `sql_pool_status` / `sql_capabilities` | pool state and dialect capabilities |
| `sql_list_dialects` | supported dialects and driver availability |

### Knowledge graph

`sql_ingest_schema` (`schema`, `include_views`, `include_indexes`, `max_objects`) reflects a
schema and ingests it; it needs `SQL_ALLOW_KG_INGEST=True`.

## The `SqlApi` client

```python
from sql_mcp import Api

api = Api(
    connections={"app": "postgresql+psycopg://svc:secret@db:5432/app"},
    allow_writes=False,
    max_rows=500,
    timeout=30.0,
)
result = api.query("SELECT * FROM users WHERE id = :id", params={"id": 1})
print(result["rows"], result["truncated"])
print(api.list_tables(), api.table_ddl("users"))
```

Construct it without arguments to read the `SQL_*` environment (see the README
configuration table).

## CLI
