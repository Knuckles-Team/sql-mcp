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

*Version: 2.0.0*

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

The table below is auto-generated from the MCP server — do not edit by hand.

<!-- MCP-TOOLS-TABLE:START -->

#### Condensed action-routed tools (default — `MCP_TOOL_MODE=condensed`)

| MCP Tool | Toggle Env Var | Description |
|----------|----------------|-------------|
| `sql_admin` | `SQLTOOL` | Connection health, server version, sessions, and registry info. |
| `sql_schema` | `SQLTOOL` | Inspect schemas, tables, views, columns, indexes, FKs, and DDL. |

#### Verbose 1:1 API-mapped tools (`MCP_TOOL_MODE=verbose` or `both`)

<details>
<summary>22 per-operation tools — one per public API method (click to expand)</summary>

| MCP Tool | Toggle Env Var | Description |
|----------|----------------|-------------|
| `sql_active_connections` | `SQL_APITOOL` | List active server sessions where the dialect supports it. |
| `sql_connection_names` | `SQL_APITOOL` | Names of all configured connections. |
| `sql_default_connection` | `SQL_APITOOL` | The sole/first configured connection — used when none is named. |
| `sql_describe_connections` | `SQL_APITOOL` | Describe configured connections with passwords redacted. |
| `sql_dialect_spec` | `SQL_APITOOL` | The registered :class:`DialectSpec` for a connection, if any. |
| `sql_dispose` | `SQL_APITOOL` | Dispose all pooled engines. |
| `sql_engine` | `SQL_APITOOL` | Lazily create (and cache) the Engine for a named connection. |
| `sql_execute` | `SQLTOOL` | Execute one DML/DDL statement in a transaction (writes gate applies). |
| `sql_execute_script` | `SQL_APITOOL` | Run several statements in ONE transaction (all-or-nothing). |
| `sql_explain` | `SQL_APITOOL` | Return the dialect's query plan for a read-only statement. |
| `sql_list_columns` | `SQL_APITOOL` | Describe a table's columns: name, type, nullable, default. |
| `sql_list_foreign_keys` | `SQL_APITOOL` | List a table's foreign keys (columns -> referred table/columns). |
| `sql_list_indexes` | `SQL_APITOOL` | List a table's indexes (name, columns, uniqueness). |
| `sql_list_schemas` | `SQL_APITOOL` | List schema names. |
| `sql_list_tables` | `SQL_APITOOL` | List table names (optionally within a schema). |
| `sql_list_views` | `SQL_APITOOL` | List view names (optionally within a schema). |
| `sql_ping` | `SQL_APITOOL` | Connection test: ``SELECT 1`` round-trip with latency. |
| `sql_query` | `SQLTOOL` | Execute a read-only SELECT/CTE with bound parameters. |
| `sql_resolve_connection` | `SQL_APITOOL` | Map an optional connection name to a configured one (or raise). |
| `sql_sample_rows` | `SQL_APITOOL` | Return up to ``limit`` rows from a table (cap still applies). |
| `sql_server_version` | `SQL_APITOOL` | Report the server version (dialect SQL, else SQLAlchemy's probe). |
| `sql_table_ddl` | `SQL_APITOOL` | Reflect a table and render its CREATE TABLE DDL for this dialect. |

</details>

_2 action-routed tool(s) (default) · 22 verbose 1:1 tool(s). Each is enabled unless its `<DOMAIN>TOOL` toggle is set false; `MCP_TOOL_MODE` selects the surface (`condensed` default · `verbose` 1:1 · `both`). Auto-generated — do not edit._
<!-- MCP-TOOLS-TABLE:END -->

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

Pick the extra that matches what you want to run. DB-driver extras
(`postgres` / `mysql` / `mssql` / `oracle`) are **additive** — combine them with
`[mcp]` or `[agent]`, e.g. `sql-mcp[mcp,postgres]` (see [Dialects & extras](#dialects--extras)).

| Extra | Installs | Use when |
|-------|----------|----------|
| `sql-mcp[mcp]` | Connector-focused MCP server (`agent-utilities[mcp]` — FastMCP/FastAPI + `epistemic-graph[full]`) | You only run the **MCP server** (smallest install / image) |
| `sql-mcp[agent]` | Agent runtime (`agent-utilities[agent-runtime,logfire]` — model orchestration + `epistemic-graph[full]`) | You run the **integrated agent** |
| `sql-mcp[all]` | Everything (`mcp` + `agent` + **every** DB driver + `logfire`) | Development / both surfaces |

```bash
pip install sql-mcp                  # core (SQLite only, MCP server, API)
pip install "sql-mcp[mcp]"           # connector-focused MCP server (add drivers: [mcp,postgres])
pip install "sql-mcp[agent]"         # agent runtime runtime (Pydantic AI + engine)
pip install "sql-mcp[all]"           # every driver + MCP + agent extras
pip install -e .                     # from source
```

### Container images (`:mcp` vs `:agent`)

One multi-stage `docker/Dockerfile` builds two right-sized images, selected by `--target`:

| Image tag | Build target | Contents | Entrypoint |
|-----------|--------------|----------|------------|
| `example/sql-mcp:mcp` | `--target mcp` | `sql-mcp[mcp]` — **connector-focused**, includes `epistemic-graph[full]`; no model-orchestration stack | `sql-mcp` |
| `example/sql-mcp@sha256:<digest>` | `--target agent` (default) | `sql-mcp[agent]` — **agent runtime**, model orchestration + `epistemic-graph[full]` | `sql-agent` |

```bash
docker pull example/sql-mcp:mcp                                   # connector-focused MCP server
docker build --target mcp   -t example/sql-mcp:mcp    docker/     # build MCP server
docker build --target agent -t example/sql-mcp:agent-local docker/     # build full agent
```

`docker/mcp.compose.yml` runs the connector-focused `:mcp` server; `docker/agent.compose.yml` runs the
agent (`immutable agent digest`) with a co-located `:mcp` sidecar.

### Knowledge-graph database (`epistemic-graph`)

Both `[mcp]` and `[agent]` carry the **epistemic-graph** engine through the required
Agent Utilities core dependency (`epistemic-graph[full]`). The `[mcp]` extra keeps
the server connector-focused; `[agent]` additionally enables model orchestration. Local
deployments can use the bundled engine. For production or shared state, run
**epistemic-graph as a dedicated database service** and configure the runtime to use it.
Deployment recipes (single-node + Raft HA), connection configuration, and architecture
diagrams are documented in the
[epistemic-graph deployment guide](https://knuckles-team.github.io/epistemic-graph/deployment/).

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

> **Install the connector-focused `[mcp]` extra.** Examples use `sql-mcp[mcp]` to add
> FastMCP / FastAPI through `agent-utilities[mcp]`; the required Agent Utilities core
> still carries `epistemic-graph[full]`. The `[agent]` extra additionally
> enables model orchestration.
> Combine it with the database-driver extras needed by the deployment.

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

`sql-mcp` can run as a local stdio process or container, or behind a remote
network boundary. The
[Deployment guide](https://knuckles-team.github.io/sql-mcp/deployment/) carries
the detailed transport contract.

- **Local container** — launch a reviewed immutable image as a least-privilege
  stdio child with no listener or published port.
- **Remote URL** — connect through an operator-supplied authenticated HTTPS
  ingress. Keep its URL, outbound identity references, trust profile, and exact
  `MCP_ALLOWED_HOSTS` in `AgentConfig`.
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


<!-- BEGIN agent-utilities-deployment (generated; do not edit between markers) -->

## Deploy with `agent-utilities-deployment`

Provision this package with the consolidated **`agent-utilities-deployment`**
workflow. It selects an installed-package, editable-source, or immutable-container
path; records only runtime secret and TLS-profile references in `AgentConfig`; and
runs doctor, registration, policy, observability, and rollback gates. Ask your agent
to **"deploy `sql-mcp` with agent-utilities-deployment"**.

| Install mode | Command |
|------|---------|
| Installed package | `uv tool install "sql-mcp[mcp]"`, then run `sql-mcp` |
| Editable source | `uv pip install -e ".[agent]"`, then run `sql-mcp` |
| Immutable container | deploy `registry.example.invalid/sql-mcp@sha256:<digest>` through the operator-selected orchestrator |

The repository embeds no deployment profile, credential value, certificate path, or
environment-specific endpoint. Supply those at runtime through `AgentConfig` and the
configured secret provider.

<!-- END agent-utilities-deployment -->

## Environment Variables

<!-- ENV-VARS-TABLE:START -->

#### Package environment variables

| Variable | Example | Description |
|----------|---------|-------------|
| `HOST` | `0.0.0.0` |  |
| `PORT` | `8000` |  |
| `TRANSPORT` | `stdio` | options: stdio, streamable-http, sse |
| `ENABLE_OTEL` | `True` |  |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `http://localhost:8080/api/public/otel` |  |
| `OTEL_EXPORTER_OTLP_PUBLIC_KEY` | `pk-...` |  |
| `OTEL_EXPORTER_OTLP_SECRET_KEY` | `sk-...` |  |
| `OTEL_EXPORTER_OTLP_PROTOCOL` | `http/protobuf` |  |
| `EUNOMIA_TYPE` | `none` | options: none, embedded, remote |
| `EUNOMIA_POLICY_FILE` | `mcp_policies.json` |  |
| `EUNOMIA_REMOTE_URL` | `http://eunomia-server:8000` |  |
| `SQL_CONNECTIONS` | `{"warehouse": "postgresql+psycopg://svc:password@db:5432/dw"}` | password, database, options} objects. Takes priority over SQL_URL. |
| `SQL_URL` | `postgresql+psycopg://svc:password@db.example.com:5432/app` | Single connection (registered as "default") |
| `SQL_DIALECT` | `postgres` | ... or discrete fields for a single "default" connection |
| `SQL_HOST` | `db.example.com` |  |
| `SQL_PORT` | `5432` |  |
| `SQL_USERNAME` | `svc` |  |
| `SQL_PASSWORD` | — |  |
| `SQL_DATABASE` | `app` |  |
| `SQL_OPTIONS` | `{"sslmode": "require"}` |  |
| `SQL_ALLOW_WRITES` | `False` | Policy (read-only by default) |
| `SQL_MAX_ROWS` | `500` |  |
| `SQL_TIMEOUT_SECONDS` | `30` |  |
| `SQLTOOL` | `True` |  |

#### Inherited agent-utilities variables (apply to every connector)

| Variable | Example | Description |
|----------|---------|-------------|
| `MCP_TOOL_MODE` | `condensed` | Tool surface: `condensed` | `verbose` | `both` |
| `MCP_ENABLED_TOOLS` | — | Comma-separated tool allow-list |
| `MCP_DISABLED_TOOLS` | — | Comma-separated tool deny-list |
| `MCP_ENABLED_TAGS` | — | Comma-separated tag allow-list |
| `MCP_DISABLED_TAGS` | — | Comma-separated tag deny-list |
| `MCP_CLIENT_AUTH` | — | Outbound MCP auth (`oidc-client-credentials` for fleet calls) |
| `OIDC_CLIENT_ID` | — | OIDC client id (service-account auth) |
| `OIDC_CLIENT_SECRET` | — | OIDC client secret (service-account auth) |
| `DEBUG` | `False` | Verbose logging |
| `PYTHONUNBUFFERED` | `1` | Unbuffered stdout (recommended in containers) |
| `MCP_URL` | `http://localhost:8000/mcp` | URL of the MCP server the agent connects to |
| `PROVIDER` | `openai` | LLM provider for the agent |
| `MODEL_ID` | `gpt-4o` | Model id for the agent |
| `ENABLE_WEB_UI` | `True` | Serve the AG-UI web interface |

_24 package + 14 inherited variable(s). Auto-generated from `.env.example` + the shared agent-utilities set — do not edit._
<!-- ENV-VARS-TABLE:END -->

<!-- GOVERNED-CAPABILITY:START -->
## Governed capability contract

This package ships a compact canonical skill surface with specialist procedures
kept as referenced workflows. The current MCP tools, skill metadata,
`connector_manifest.yml`, ontology, mappings, shapes, fixtures, migrations,
tool-schema fingerprints, and certification metadata form one versioned
capability contract. Validate them together; do not rely on stale tool names or
historical per-task skill wrappers.

Runtime endpoints, credentials, certificate trust, tenant identity, retention,
and observability policy are deployment inputs and are never packaged values.
See [Configuration, trust, and privacy](docs/configuration.md) before enabling a
network transport, connector ingestion, GraphOS delegation, or trace export.
<!-- GOVERNED-CAPABILITY:END -->
