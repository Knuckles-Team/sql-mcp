# sql-mcp — Concept Overview

> Built on [`scion-sdk`](https://github.com/Knuckles-Team/scion-sdk) — the unified AGI Harness.

## Description

PostgreSQL, MySQL/MariaDB, Microsoft SQL Server, Oracle, and SQLite over
SQLAlchemy 2.x Core. Read-only by default, with server-side write gating,
bound parameters everywhere, row caps, and statement timeouts.

## Architecture

This project follows the standardized agent-package pattern:

- **Modular Design**: split into `api/` (the `SqlApi` SQLAlchemy 2.x Core
  facade — all business logic) and `mcp/` (action-routed tool modules — thin
  shims) for cleaner organization.
- **Dynamic Tool Registration**: action-routed dynamic tool tags, strictly
  lowercase, each togglable with a `*TOOL` environment flag (`SQLTOOL`).
- **Safety boundary**: `sql_mcp.safety.assert_read_only` (allowlist + CTE
  depth-zero scan) guards every `sql_query` statement; writes require the
  server-side `SQL_ALLOW_WRITES=True` switch.

## Concept Registry

This project implements or inherits the following ecosystem concepts:

| Concept ID | Description | Source |
|:-----------|:------------|:-------|
| ECO-4.1 | MCP & Universal Skills | `scion-sdk` (inherited) |
| CONCEPT:SQ-OS.governance.sql-2 | Action-dispatch MCP tool surface | [`concepts.md`](concepts.md) |
| CONCEPT:SQ-OS.safety.allow-deny-classification | Read-only statement gate | [`concepts.md`](concepts.md) |

> 📖 **Full Registry**: See [`scion-sdk/docs/overview.md`](https://github.com/Knuckles-Team/scion-sdk/blob/main/docs/overview.md) for the complete 5-Pillar concept index.
