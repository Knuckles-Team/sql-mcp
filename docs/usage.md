# Usage

## The MCP tools

Four consolidated, action-routed tools (few tools, many actions). Every tool
takes `action`, `params_json` (a JSON object of arguments), and an optional
`connection` naming one of the configured connections (defaults to the
sole/first one).

### `sql_query` — read-only queries

| Action | Arguments | Returns |
|---|---|---|
| `execute` | `{"sql", "params", "max_rows", "timeout"}` | `{columns, rows, row_count, truncated}` |
| `explain` | `{"sql", "params"}` | the dialect's query plan |

```json
{
  "action": "execute",
  "params_json": "{\"sql\": \"SELECT id, name FROM users WHERE id = :id\", \"params\": {\"id\": 1}, \"max_rows\": 100}",
  "connection": "warehouse"
}
```

Statements must be single and read-only (`SELECT`/`WITH`/`EXPLAIN`/`SHOW`/
`DESCRIBE`/`PRAGMA`/`VALUES`); values bind via `:name` parameters. `max_rows` is
clamped to the server's `SQL_MAX_ROWS`. EXPLAIN is unavailable on MSSQL (it has
no statement-level EXPLAIN).

### `sql_execute` — gated DML/DDL

Requires the server to run with `SQL_ALLOW_WRITES=True`; the default is
read-only and there is **no per-call override**.

| Action | Arguments | Returns |
|---|---|---|
| `execute` | `{"sql", "params"}` (dict, or list of dicts for executemany) | `{rowcount}` |
| `script` | `{"statements": [...]}` — ONE all-or-nothing transaction | `{statements, rowcounts}` |

### `sql_schema` — reflection

| Action | Arguments |
|---|---|
| `schemas` | `{}` |
| `tables` / `views` | `{"schema"}` (optional) |
| `columns` / `indexes` / `foreign_keys` / `ddl` | `{"table", "schema"}` |
| `sample` | `{"table", "limit", "schema"}` (limit clamped to the row cap) |

### `sql_admin` — health & registry

| Action | Returns |
|---|---|
| `ping` | connection test + latency |
| `version` | server version per dialect |
| `active_connections` | server sessions (Postgres/MySQL/MSSQL/Oracle; SQLite reports unsupported) |
| `connections` | configured connections, passwords redacted |
| `dialects` | supported dialects + driver availability |

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

```bash
sql-mcp                                                    # stdio
sql-mcp --transport streamable-http --host 0.0.0.0 --port 8000
sql-agent --mcp-url http://localhost:8000/mcp --port 8080  # A2A agent
```
