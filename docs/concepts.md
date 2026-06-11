# Concept Registry — sql-mcp

> **Prefix**: `CONCEPT:SQL-1.x`

Stable concept IDs trace the connector's core ideas across the documentation,
code docstrings, and tests.

| Concept ID | Name | Description |
|---|---|---|
| `CONCEPT:SQL-1.0` | SQL MCP Domain | The SQL tool domain registered by `register_sql_tools()` — four consolidated, action-routed tools |
| `CONCEPT:SQL-1.1` | Dialect Registry | `DIALECTS` — per-engine `DialectSpec` (URL scheme, optional driver + pip extra, EXPLAIN prefix, admin SQL); the vector-mcp backend-registry pattern |
| `CONCEPT:SQL-1.2` | Named Connection Config | `SQL_CONNECTIONS` JSON / `SQL_URL` / discrete env fields -> named `sqlalchemy.URL` registry; passwords only ever rendered redacted |
| `CONCEPT:SQL-1.3` | Read-Only Statement Gate | Literal/comment-stripping classifier: allowlisted starters, depth-zero CTE inspection, single-statement enforcement; writes only via `sql_execute` + `SQL_ALLOW_WRITES` |
| `CONCEPT:SQL-1.4` | Bounded Result Envelope | Every result is `{columns, rows, row_count, truncated}` with a clamped row cap and a per-call timeout on a worker thread |
| `CONCEPT:SQL-1.5` | Action-Dispatch Tools | `sql_query`, `sql_execute`, `sql_schema`, `sql_admin` — thin `action` + `params_json` shims over `SqlApi` |
| `CONCEPT:SQL-1.6` | A2A Agent Server | The Pydantic-AI agent server (`sql-agent`) wired to the MCP server via `MCP_URL` |
