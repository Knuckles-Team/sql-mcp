---
name: sql-mcp-knowledge-graph-ingestion
skill_type: skill
description: >-
  Mirror a relational database's reflected schema into the medulla knowledge graph as typed OWL nodes (tables, columns, views, indexes, foreign keys) via the sql-mcp MCP server. Use to make a schema queryable in the KG. Not for running SQL (sql-mcp-query-execution) or listing schema without persisting (sql-mcp-schema-inspection).
license: MIT
tags: [sql, database, knowledge-graph, ingestion, ontology, mcp]
metadata:
  author: Knuckles-Team
  version: '0.1.0'
---
# SQL Knowledge-Graph Ingestion

Scope: Mirror a relational database's reflected structure into the medulla knowledge graph as typed OWL nodes via the sql-mcp MCP server. Use when the agent must make a database's schema queryable in the KG — tables, columns, views, indexes, and foreign-key relationships become :DatabaseTable / :DatabaseColumn / :DatabaseView / :DatabaseIndex nodes with structural links. Do NOT use to run SQL (use sql-mcp-query-execution) or merely list schema objects without persisting them (use sql-mcp-schema-inspection).

Push the **reflected schema** of any configured connection into the ONE
medulla knowledge graph as **typed OWL nodes**, via the **sql-mcp** MCP
server. The connector walks tables, columns, foreign keys, indexes, and views
and maps them to the classes federated by `sql_mcp.ontology`
(`https://knuckles-team.github.io/ontology/connector/database`).

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
see `sql-mcp-query-execution`) **and** a reachable medulla engine.
Ingestion is gated by `SQL_ALLOW_KG_INGEST=True` and fails closed when the engine is unreachable.

## Steps

1. Preview the structure by calling `sql_list_tables` with `schema` and `connection`. Verify the expected tables are listed and the count is reasonable.
2. Run the ingest by calling `sql_ingest_schema` with `schema`, `include_views`, `include_indexes` and `max_objects`. Verify the response reports ingested node and edge counts.
3. Re-run `sql_ingest_schema` with the same arguments after a migration. Verify counts are stable, since nodes merge on their deterministic id.
4. Spot check the graph by querying for a table node such as `database:table:<conn>.<schema>.<table>`. Verify it exists with its `:hasColumn` links.

## Failure recovery

| Failure | Cause | Recovery |
|---------|-------|----------|
| Ingest is refused | `SQL_ALLOW_KG_INGEST` is not `True` | Ask the operator to set `SQL_ALLOW_KG_INGEST=True` and call `sql_ingest_schema` again |
| Call raises with nothing written | The medulla engine is unreachable, so the tool fails closed | Restore the engine connection and re-run `sql_ingest_schema` |
| Very large write | Wide schema with many columns and indexes | Narrow with `schema`, set `include_indexes=false` or `include_views=false`, and lower `max_objects` |

## Tools
| Tool | Purpose |
|------|---------|
| `sql_ingest_schema` | Reflect a connection/schema and ingest it as typed KG nodes |

### Key parameters
- `schema` is the optional namespace to reflect (omit for the connection's default schema).
- `include_views` includes `:DatabaseView` nodes (default `true`).
- `include_indexes` includes `:DatabaseIndex` nodes (default `true`).
- `max_objects` caps reflected objects (default and maximum 5000).
- `connection` is an optional named connection (empty = the default one).

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

## Recipes
Ingest the default schema (tables, columns, foreign keys, indexes, views): call `sql_ingest_schema` with no arguments.

Ingest one named schema and skip indexes: `sql_ingest_schema` with `schema="public"`, `include_indexes=false`.

## Gotchas
- Ingest is off unless `SQL_ALLOW_KG_INGEST=True`, and it fails closed: an unreachable engine raises, nothing is half-written.
- Re-running is safe: nodes MERGE on their deterministic id, so re-ingest after a
  migration updates in place rather than duplicating.
- Foreign-key `:referencesTable` links assume the referred table lives in the
  **same** reflected schema label; cross-schema FKs are linked under that label.
- Wide schemas produce many nodes (one per column/index); scope with `schema` and
  toggle `include_views`/`include_indexes` to bound the write.

## Related
- `sql-mcp-schema-inspection` — inspect the same structure without persisting it.
- `sql-mcp-query-execution` — query the live database the graph mirrors.
