# Concept Registry — sql-mcp

> **Prefix**: `CONCEPT:SQ-OS.governance.sql-x` | **Version**: 0.1.0

This connector inherits the ecosystem bridge concept `ECO-4.0`
(connector parity standard) from
[`agent-utilities`](https://github.com/Knuckles-Team/agent-utilities/blob/main/docs/overview.md),
alongside `ECO-4.1` (MCP & Universal Skills) and `AU-ECO.toolkit.journey-map-narrative` (A2A Network).

Stable concept IDs trace the connector's core ideas across the documentation,
code docstrings, and tests.

| Concept ID | Name | Description |
|---|---|---|
| `CONCEPT:SQ-OS.governance.sql-2` | SQL MCP Domain | The SQL tool domain registered by `register_sql_tools()` — four consolidated, action-routed tools |
| `CONCEPT:SQ-OS.governance.url-building-drivers-dialect` | Dialect Registry | `DIALECTS` — per-engine `DialectSpec` (URL scheme, optional driver + pip extra, EXPLAIN prefix, admin SQL); the vector-mcp backend-registry pattern |
| `CONCEPT:SQ-OS.identity.env-parsing-secret-redaction` | Named Connection Config | `SQL_CONNECTIONS` JSON / `SQL_URL` / discrete env fields -> named `sqlalchemy.URL` registry; passwords only ever rendered redacted |
| `CONCEPT:SQ-OS.safety.allow-deny-classification` | Read-Only Statement Gate | Literal/comment-stripping classifier: allowlisted starters, depth-zero CTE inspection, single-statement enforcement; writes only via `sql_execute` + `SQL_ALLOW_WRITES` |
| `CONCEPT:SQ-OS.governance.sql-3` | Bounded Result Envelope | Every result is `{columns, rows, row_count, truncated}` with a clamped row cap and a per-call timeout on a worker thread |
| `CONCEPT:SQ-OS.governance.action-routing-through-fastmcp` | Action-Dispatch Tools | `sql_query`, `sql_execute`, `sql_schema`, `sql_admin` — thin `action` + `params_json` shims over `SqlApi` |
| `CONCEPT:SQ-OS.governance.sql-4` | A2A Agent Server | The Pydantic-AI agent server (`sql-agent`) wired to the MCP server via `MCP_URL` |
