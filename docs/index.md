# sql-mcp

Generic SQL database **API + MCP Server + A2A Agent** for the agent-utilities
ecosystem — one connector for PostgreSQL, MySQL/MariaDB, Microsoft SQL Server,
Oracle, and SQLite over SQLAlchemy 2.x Core.

!!! info "Official documentation"
    This site is the canonical reference for `sql-mcp`, maintained alongside every
    release.

[![PyPI](https://img.shields.io/pypi/v/sql-mcp)](https://pypi.org/project/sql-mcp/)
![MCP Server](https://badge.mcpx.dev?type=server 'MCP Server')
[![License](https://img.shields.io/pypi/l/sql-mcp)](https://github.com/Knuckles-Team/sql-mcp/blob/main/LICENSE)
[![GitHub](https://img.shields.io/badge/source-GitHub-181717?logo=github)](https://github.com/Knuckles-Team/sql-mcp)

## Overview

`sql-mcp` wraps relational databases with typed, deterministic MCP tools, and
ships an optional Pydantic-AI agent server. It provides:

- **`SqlApi`** — a SQLAlchemy 2.x Core facade with named multi-connection
  support, lazy engine creation, a read-only statement gate, row-cap/timeout
  enforcement, and bounded result envelopes.
- **Four MCP tools** — action-dispatch wrappers (`sql_query`, `sql_execute`,
  `sql_schema`, `sql_admin`) that expose queries, gated writes, schema
  reflection, and connection administration to an agent or policy router.
- **A dialect registry** — SQLite ships in core (stdlib-backed); PostgreSQL,
  MySQL/MariaDB, MSSQL, and Oracle drivers install via pip extras.

The server is **read-only by default**: writes require `SQL_ALLOW_WRITES=True`
at server start, every query passes a statement-type allowlist, and all values
travel as bound parameters.

## Explore the documentation

<div class="grid cards" markdown>

- :material-rocket-launch: **[Installation](installation.md)** — pip, source, the per-dialect extras matrix, and Docker.
- :material-console: **[Usage](usage.md)** — the MCP tools and their actions, the `SqlApi` client, and the CLI.
- :material-tag-multiple: **[Concepts](concepts.md)** — the `CONCEPT:SQL-1.x` registry.

</div>

## Quick start

```bash
pip install "sql-mcp[mcp]"
sql-mcp                        # stdio MCP server, zero-infra in-memory SQLite
```

Connect it to a real database:

```bash
pip install "sql-mcp[postgres]"
export SQL_URL="postgresql+psycopg://svc:****@db.example.com:5432/app"
sql-mcp --transport streamable-http --host 0.0.0.0 --port 8000
```

See **[Installation](installation.md)** for the full matrix (PyPI extras, Docker
image, transports, the agent server).
