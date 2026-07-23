# Recipe — the epistemic-graph KG as a sql-mcp connection

> Cross-repo concept: `CONCEPT:KG-2.205` (KG-SQL surface) over
> `CONCEPT:KG-2.189` (engine pg-wire listener) + `CONCEPT:KG-2.202` (SCRAM auth).

The [epistemic-graph](../../../../epistemic-graph/) engine exposes its Knowledge
Graph over the **Postgres wire protocol**. A server built with the `pgwire`
feature and started with `EPISTEMIC_GRAPH_PGWIRE_ADDR` set accepts native
SQLAlchemy/psycopg connections and runs read-only SQL over the `nodes`/`edges`
tables (the same DataFusion path `Method::Sql` uses). So the KG needs **no
special connector** in sql-mcp — it is just another named connection.

This is the complement to the native KG-SQL MCP tool: agent-utilities' graph-os
exposes `graph_query(scope="sql")` (+ REST `/graph/query`) for SQL-on-the-KG over
MCP; this recipe reaches the *same* engine surface from a generic SQL client.

## 1. Deploy the engine with pg-wire + SCRAM

Build/run the engine with the listener bound (loopback by convention) and an auth
secret set so SCRAM is the default:

```bash
# engine side (epistemic-graph)
cargo build --release --features "server,query,pgwire,redb"
GRAPH_SERVICE_AUTH_SECRET=<engine-secret> \
EPISTEMIC_GRAPH_PGWIRE_ADDR=127.0.0.1:5433 \
EPISTEMIC_GRAPH_PGWIRE_AUTH=scram \
  target/release/epistemic-graph-server --persist-dir /var/lib/epistemic-graph
```

When `GRAPH_SERVICE_AUTH_SECRET` is set, `scram` is the default auth mode; the pg
`user` maps to an engine `agent_id`, and queries run under that identity against
the engine ACL / row-level security (`IsolationLayer::check_access`).

## 2. Derive the SCRAM password

Under SCRAM the per-user password is **derived** from the engine secret — it is
never stored:

```
derived_password(user) = hex(HMAC-SHA256(GRAPH_SERVICE_AUTH_SECRET, "pgwire:" + user))
```

`sql-mcp` ships a helper that reproduces that derivation exactly:

```bash
export GRAPH_SERVICE_AUTH_SECRET=<engine-secret>
python -m sql_mcp.kg_pgwire derive-password --user sql-mcp
# -> <hex password>

# or the whole DSN in one shot:
python -m sql_mcp.kg_pgwire dsn --user sql-mcp --host 127.0.0.1 --port 5433 --graph __commons__
# -> postgresql+psycopg://sql-mcp:<hex>@127.0.0.1:5433/__commons__
```

Store the derived password as a **vault ref** (OpenBao `apps/sql-mcp`, key
`KG_PGWIRE_PASSWORD`); it is injected into the service env at deploy time. The
engine secret itself stays in OpenBao and is never committed.

```bash
bao kv put apps/sql-mcp \
  KG_PGWIRE_USER=sql-mcp \
  KG_PGWIRE_PASSWORD="$(python -m sql_mcp.kg_pgwire derive-password --user sql-mcp)"
```

## 3. Register the `kg` connection

Point one of sql-mcp's named connections at the listener
(`SQL_CONNECTIONS`, `CONCEPT:SQL-1.2`). The deployed stack
(`services/sql-mcp/compose.dev.yml`) already wires this from the vault-injected
vars:

```bash
SQL_CONNECTIONS='{"kg":"postgresql+psycopg://sql-mcp:<KG_PGWIRE_PASSWORD>@127.0.0.1:5433/__commons__"}'
```

The `database` segment (`__commons__`) selects the engine graph; use any
registered graph name, e.g. `team:alpha`.

## 4. Validate

```bash
# connection health
sql_admin  action=ping            connection=kg
# read the graph as SQL
sql_query  action=execute  connection=kg \
           params_json='{"sql":"SELECT id, label FROM nodes LIMIT 5"}'
```

`sql_admin ping` confirms the SCRAM handshake + latency; the `sql_query` returns
the bounded `{columns, rows, row_count, truncated}` envelope (`CONCEPT:SQL-1.4`)
over real KG nodes.

## Notes

- **Read-only by default.** sql-mcp's `sql_query` only runs SELECT/CTE; the engine
  pg-wire surface also classifies writes and routes them through the governed
  write path. Leave `SQL_ALLOW_WRITES` off for the `kg` connection unless you
  intend governed DML over `nodes`.
- **Driver.** Requires the `postgres` extra (`sql-mcp[postgres]` → `psycopg`).
- **No new connector code.** This is config + the derivation helper only — the KG
  is reached through the standard SQLAlchemy Postgres dialect.
