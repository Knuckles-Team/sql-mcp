# Sql Mcp
## API | MCP Server | A2A Agent

![PyPI - Version](https://img.shields.io/pypi/v/sql-mcp)
![MCP Server](https://badge.mcpx.dev?type=server 'MCP Server')
![PyPI - Downloads](https://img.shields.io/pypi/dd/sql-mcp)
![GitHub Repo stars](https://img.shields.io/github/stars/Knuckles-Team/sql-mcp)
![GitHub forks](https://img.shields.io/github/forks/Knuckles-Team/sql-mcp)
![GitHub contributors](https://img.shields.io/github/contributors/Knuckles-Team/sql-mcp)
![PyPI - License](https://img.shields.io/pypi/l/sql-mcp)
![GitHub](https://img.shields.io/github/license/Knuckles-Team/sql-mcp)
![GitHub last commit (by committer)](https://img.shields.io/github/last-commit/Knuckles-Team/sql-mcp)
![GitHub pull requests](https://img.shields.io/github/issues-pr/Knuckles-Team/sql-mcp)
![GitHub closed pull requests](https://img.shields.io/github/issues-pr-closed/Knuckles-Team/sql-mcp)
![GitHub issues](https://img.shields.io/github/issues/Knuckles-Team/sql-mcp)
![GitHub top language](https://img.shields.io/github/languages/top/Knuckles-Team/sql-mcp)
![GitHub language count](https://img.shields.io/github/languages/count/Knuckles-Team/sql-mcp)
![GitHub repo size](https://img.shields.io/github/repo-size/Knuckles-Team/sql-mcp)
![PyPI - Wheel](https://img.shields.io/pypi/wheel/sql-mcp)
![PyPI - Implementation](https://img.shields.io/pypi/implementation/sql-mcp)

Generic SQL database **API + MCP Server + A2A Agent** for the agent-utilities
ecosystem — one connector for **PostgreSQL, MySQL/MariaDB, Microsoft SQL Server,
Oracle, and SQLite** over SQLAlchemy 2.x Core.

*Version: 0.4.0*

> **Documentation** — Installation, deployment, and usage across the API, CLI, and
> MCP interfaces are maintained in [`docs/`](docs/index.md).

## Table of Contents

- [Overview](#overview)
- [What it provides](#what-it-provides)
- [MCP tools](#mcp-tools)
- [Dialects & extras](#dialects--extras)
- [Configuration (environment)](#configuration-environment)
- [Installation](#installation)
- [Usage](#usage)
- [MCP config](#mcp-config)
- [Docker deployment](#docker-deployment)
- [Safety model](#safety-model)
- [Tests](#tests)

## Overview

`sql-mcp` exposes read-only queries, gated DML/DDL, schema reflection, and
connection administration as typed, deterministic MCP tools, and ships an optional
Pydantic-AI agent server. It is **read-only by default**: every query passes a
statement-type allowlist, every result is bounded by a row cap and a timeout, and
all values travel as bound parameters — never interpolated into SQL strings.

## What it provides

- **`SqlApi`** (`sql_mcp.api.api_client_sql`) — a SQLAlchemy 2.x Core facade with
  named multi-connection support, lazy engine creation, the read-only statement
  gate, row-cap/timeout enforcement, and bounded result envelopes
  (`{columns, rows, row_count, truncated}`).
- **Four MCP tools** (`sql-mcp` console script): `sql_query` (execute/explain),
  `sql_execute` (execute/script — gated by `SQL_ALLOW_WRITES`), `sql_schema`
  (schemas/tables/views/columns/indexes/foreign_keys/ddl/sample), and `sql_admin`
  (ping/version/active_connections/connections/dialects). See
  [`docs/usage.md`](docs/usage.md) for the full action surface.
- **A dialect registry** (`sql_mcp.dialects`) — per-engine driver, URL scheme, pip
  extra, EXPLAIN prefix, and admin SQL. Core ships SQLite only; the other drivers
  install via extras.
- **An A2A agent server** (`sql-agent` console script) — a Pydantic-AI graph agent
  wired to the MCP server via `MCP_URL`.

## MCP tools

| Tool | Actions | Description |
|---|---|---|
| `sql_query` | `execute`, `explain` | Run a read-only SELECT/CTE with bound parameters, or return the dialect's query plan |
| `sql_execute` | `execute`, `script` | One DML/DDL statement (or an all-or-nothing statement list) in a transaction — requires `SQL_ALLOW_WRITES=True` |
| `sql_schema` | `schemas`, `tables`, `views`, `columns`, `indexes`, `foreign_keys`, `ddl`, `sample` | Reflect schemas, tables, columns, indexes, FKs, CREATE DDL, and preview rows |
| `sql_admin` | `ping`, `version`, `active_connections`, `connections`, `dialects` | Connection health, server version, server sessions, registry info, driver availability |

Every tool takes `action`, `params_json`, and an optional `connection` naming one
of the configured connections. The whole set is toggled with `SQLTOOL`.

## Dialects & extras

| Dialect | SQLAlchemy scheme | Driver | Install |
|---|---|---|---|
| SQLite | `sqlite+pysqlite` | stdlib | `pip install sql-mcp` (core) |
| PostgreSQL | `postgresql+psycopg` | psycopg 3 | `pip install sql-mcp[postgres]` |
| MySQL / MariaDB | `mysql+pymysql` | PyMySQL | `pip install sql-mcp[mysql]` |
| SQL Server | `mssql+pyodbc` | pyodbc | `pip install sql-mcp[mssql]` |
| Oracle | `oracle+oracledb` | python-oracledb | `pip install sql-mcp[oracle]` |

`pip install sql-mcp[all]` pulls every driver plus the MCP and agent extras.

## Configuration (environment)

| Var | Default | Meaning |
|---|---|---|
| `SQL_CONNECTIONS` | _(empty)_ | JSON map of named connections: DSN strings or `{dialect, host, port, username, password, database, options}` objects |
| `SQL_URL` | _(empty)_ | Single DSN registered as connection `default` |
| `SQL_DIALECT` / `SQL_HOST` / `SQL_PORT` / `SQL_USERNAME` / `SQL_PASSWORD` / `SQL_DATABASE` / `SQL_OPTIONS` | _(empty)_ | Discrete fields for a single `default` connection |
| `SQL_ALLOW_WRITES` | `False` | Enable `sql_execute` (DML/DDL). **Read-only by default** |
| `SQL_MAX_ROWS` | `500` | Per-call row cap; tool requests are clamped to it |
| `SQL_TIMEOUT_SECONDS` | `30` | Per-statement timeout |
| `SQLTOOL` | `True` | Register the SQL tool set |

With nothing configured the server registers a zero-infra in-memory SQLite
connection named `memory`, so it works out of the box. Tools take an optional
`connection` parameter naming one of the configured connections; it defaults to
the sole/first one. Passwords are parsed into `sqlalchemy.URL` objects and only
ever rendered redacted. Copy [`.env.example`](.env.example) to `.env` and
populate only what you use.

## Installation

```bash
pip install sql-mcp            # core (SQLite, MCP server, API)
pip install sql-mcp[all]       # every driver + MCP + agent extras
pip install -e .               # from source
```

Or pull the container image:

```bash
docker pull knucklessg1/sql-mcp:latest
```

## Usage

```bash
sql-mcp                        # stdio MCP server (default transport)
sql-mcp --transport streamable-http --host 0.0.0.0 --port 8000
```

Point it at a database:

```bash
export SQL_URL="postgresql+psycopg://svc:****@db.example.com:5432/app"
sql-mcp
```

Or several:

```bash
export SQL_CONNECTIONS='{
  "warehouse": "postgresql+psycopg://svc:****@dw.example.com:5432/dw",
  "erp": {"dialect": "mysql", "host": "erp.example.com", "username": "svc",
           "password": "****", "database": "erp"}
}'
sql-mcp
```

Run the agent server against a live MCP server:

```bash
sql-agent --mcp-url http://localhost:8000/mcp --host 0.0.0.0 --port 8080
```

## MCP config

```json
{
  "mcpServers": {
    "sql-mcp": {
      "command": "uv",
      "args": ["run", "sql-mcp"],
      "env": {
        "SQL_URL": "postgresql+psycopg://svc:****@db.example.com:5432/app",
        "SQL_ALLOW_WRITES": "False"
      }
    }
  }
}
```

<!-- BEGIN GENERATED: additional-deployment-options -->
### Additional Deployment Options

`sql-mcp` can also run as a **local container** (Docker / Podman / `uv`) or be
consumed from a **remote deployment**. The
[Deployment guide](https://knuckles-team.github.io/sql-mcp/deployment/) has full, copy-paste
`mcp_config.json` for all four transports — **stdio**, **streamable-http**,
**local container / uv**, and **remote URL**:

- **Local container / uv** — launch the server from `mcp_config.json` via `uvx`,
  `docker run`, or `podman run`, or point at a local streamable-http container by `url`.
- **Remote URL** — connect to a server deployed behind Caddy at
  `http://sql-mcp.arpa/mcp` using the `"url"` key.
<!-- END GENERATED: additional-deployment-options -->

## Docker deployment

```bash
docker compose -f docker/mcp.compose.yml up -d      # MCP server only
docker compose -f docker/agent.compose.yml up -d    # MCP + A2A agent
curl -s http://localhost:8000/health                 # {"status":"OK"}
```

Both services read configuration from `../.env` (copy
[`.env.example`](.env.example)); see [`docs/deployment.md`](docs/deployment.md).

## Safety model

- **Read-only by default** — `sql_execute` refuses to run unless the *server* was
  started with `SQL_ALLOW_WRITES=True`; agents cannot flip the flag per call.
- **Statement allowlist** — `sql_query` accepts only `SELECT`/`WITH`/`EXPLAIN`/
  `SHOW`/`DESCRIBE`/`PRAGMA`/`VALUES`; CTEs are inspected at paren depth zero so
  `WITH ... INSERT` cannot smuggle a write, `SELECT INTO` is rejected, and
  multi-statement payloads are refused.
- **Bounded results** — per-call row caps clamp to `SQL_MAX_ROWS`; statements run
  under `SQL_TIMEOUT_SECONDS` on a worker thread.
- **Parameterized only** — values bind via `:name` parameters; identifiers are
  quoted by SQLAlchemy reflection, never hand-interpolated.

## Tests

```bash
python -m pytest          # full suite against in-memory SQLite (no live DBs)
pre-commit run --all-files
```
