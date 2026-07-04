---
name: sql-mcp-knowledge-graph-ingestion
description: >-
  Mirror a relational database's reflected structure into the epistemic-graph
  knowledge graph as typed OWL nodes via the sql-mcp MCP server. Use when the
  agent must make a database's schema queryable in the KG — tables, columns,
  views, indexes, and foreign-key relationships become :DatabaseTable /
  :DatabaseColumn / :DatabaseView / :DatabaseIndex nodes with structural links.
  Do NOT use to run SQL (use sql-mcp-query-execution) or merely list schema
  objects without persisting them (use sql-mcp-schema-inspection).
license: MIT
tags: [sql, database, knowledge-graph, ingestion, ontology, mcp]
metadata:
  author: Genius
  version: '0.1.0'
---
# SQL Knowledge-Graph Ingestion

Push the **reflected schema** of any configured connection into the ONE
epistemic-graph knowledge graph as **typed OWL nodes**, via the **sql-mcp** MCP
server. The connector walks tables, columns, foreign keys, indexes, and views
and maps them to the classes federated by `sql_mcp.ontology`
(`http://knuckles.team/kg/database`).

## When to use
- Make a database's structure discoverable/queryable inside the KG.
- Keep the graph's `:DatabaseTable`/`:DatabaseColumn`/`:DatabaseView`/
  `:DatabaseIndex` nodes in sync after a schema change (re-run; nodes MERGE on id).
- Seed cross-source reasoning that joins database layout to other ingested facts.

## When NOT to use
- Running queries or writes → `sql-mcp-query-execution`.
- One-off schema listing with no intent to persist → `sql-mcp-schema-inspection`.

## Prerequisites & environment
Connect via the `mcp-client` skill against the **`sql-mcp`** MCP server. Needs the
usual SQL connection variables (`SQL_CONNECTIONS` / `SQL_URL` / discrete fields —
see `sql-mcp-query-execution`) **and** a reachable epistemic-graph engine.
Ingestion is **best-effort**: with no engine reachable it cleanly no-ops
(`{"ingested": null}`) and the connector keeps working.

## Tools & actions
| Tool | Purpose |
|------|---------|
| `sql_ingest_schema` | Reflect a connection/schema and ingest it as typed KG nodes |

### Key parameters (`params_json`, a JSON string)
- `schema` — optional namespace to reflect (omit for the connection's default schema).
- `include_views` — include `:DatabaseView` nodes (default `true`).
- `include_indexes` — include `:DatabaseIndex` nodes (default `true`).
- `connection` — optional named connection (empty = the default one).

## What lands in the graph
| Class | Id shape | Key properties |
|-------|----------|----------------|
| `:DatabaseSchema` | `database:schema:<conn>.<schema>` | `name`, `sqlDialect` |
| `:DatabaseTable` | `database:table:<conn>.<schema>.<table>` | `name`, `schema` |
| `:DatabaseColumn` | `database:column:<conn>.<schema>.<table>.<col>` | `dataType`, `isNullable`, `isPrimaryKey`, `isForeignKey` |
| `:DatabaseView` | `database:view:<conn>.<schema>.<view>` | `name`, `schema` |
| `:DatabaseIndex` | `database:index:<conn>.<schema>.<table>.<idx>` | `columns`, `isUnique` |

Links: `:hasTable` (schema→table), `:hasColumn` (table→column), `:hasView`
(schema→view), `:hasIndex` (table→index), `:referencesTable` (FK table→table).

## Recipes (`params_json`)
Ingest the default schema (tables + columns + FKs + indexes + views):
```json
{}
```
Ingest one named schema, skip indexes:
```json
{"schema":"public","include_indexes":false}
```

## Gotchas
- `params_json` is a **string** of JSON, not an object.
- Best-effort by design: a `null` `ingested` value means no engine was reachable,
  **not** an error — nothing is raised.
- Re-running is safe: nodes MERGE on their deterministic id, so re-ingest after a
  migration updates in place rather than duplicating.
- Foreign-key `:referencesTable` links assume the referred table lives in the
  **same** reflected schema label; cross-schema FKs are linked under that label.
- Wide schemas produce many nodes (one per column/index); scope with `schema` and
  toggle `include_views`/`include_indexes` to bound the write.

## Related
- `sql-mcp-schema-inspection` — inspect the same structure without persisting it.
- `sql-mcp-query-execution` — query the live database the graph mirrors.
