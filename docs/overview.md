# sql-mcp — Concept Overview

> **Category**: Integration | **Ecosystem Role**: MCP Server + A2A Agent
> Built on [`agent-utilities`](https://github.com/Knuckles-Team/agent-utilities) — the unified AGI Harness.

## Description

Generic SQL database **API + MCP Server + A2A Agent** — one connector for
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
- **A2A Agent Server**: a Pydantic-AI graph agent (console script `sql-agent`)
  that calls the MCP tool surface and exposes an AG-UI web interface.
- **Safety boundary**: `sql_mcp.safety.assert_read_only` (allowlist + CTE
  depth-zero scan) guards every `sql_query` statement; writes require the
  server-side `SQL_ALLOW_WRITES=True` switch.

## Concept Registry

This project implements or inherits the following ecosystem concepts:

| Concept ID | Description | Source |
|:-----------|:------------|:-------|
| ECO-4.1 | MCP & Universal Skills | `agent-utilities` (inherited) |
| ECO-4.2 | A2A Network & Consensus | `agent-utilities` (inherited) |
| CONCEPT:SQL-1.0 | Action-dispatch MCP tool surface | [`concepts.md`](concepts.md) |
| CONCEPT:SQL-1.3 | Read-only statement gate | [`concepts.md`](concepts.md) |

> 📖 **Full Registry**: See [`agent-utilities/docs/overview.md`](https://github.com/Knuckles-Team/agent-utilities/blob/main/docs/overview.md) for the complete 5-Pillar concept index.
