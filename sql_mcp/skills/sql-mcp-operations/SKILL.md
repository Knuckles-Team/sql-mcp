---
name: sql-mcp-operations
skill_type: skill
description: >-
  Operate sql-mcp through its governed MCP and Arbora capabilities, including sql mcp knowledge graph ingestion, sql mcp query execution, sql mcp schema inspection. Use when a request requires this provider's read, change, automation, ingestion, troubleshooting, or evidence workflows.
---

# Sql Mcp Operations

Use the provider's governed MCP tools through Arbora delegation.

## Workflow

1. Establish the verified GraphSession and tenant before discovery or retrieval.
2. Discover the current tool surface; never assume a stale tool name or schema.
3. Prefer read-only inspection first. For changes, present impact and use the provider's
   dry-run or preview mode when available.
4. Execute mutations as fenced WorkItems so retries remain idempotent and auditable.
5. Ingest source data only through the signed connector preset and ChangeEnvelope path.
6. Verify the durable result and its trace/evidence before reporting completion.

## Steps

1. Confirm the connection works by calling `sql_list_schemas` with `connection`. Verify at least one schema is returned.
2. Discover the current tool surface by reading `references/catalog.md`. Verify every tool name you plan to use is listed there.
3. Inspect read-only first by calling `sql_query` with a bound `sql` and `max_rows`. Verify the rows match the request.
4. Apply changes only after approval, by calling `sql_execute` as a fenced WorkItem. Verify the affected row count is as intended.
5. Confirm the result by calling `sql_query` on the changed rows. Verify the expected values and record the WorkItem trace.

## Failure recovery

| Failure | Cause | Recovery |
|---------|-------|----------|
| `WritesDisabledError` | Server runs with writes disabled | Keep to `sql_query`, or have the operator set `SQL_ALLOW_WRITES=True` after approval |
| Unknown tool name | Stale tool name assumed | Re-read `references/catalog.md` and use the current name |
| Connection error | Missing `SQL_CONNECTIONS` or `SQL_URL` | Set one of them, or pass a valid `connection` name to `sql_list_schemas` |

## Safety contract

- Never persist credentials, endpoints, raw personal identifiers, hostnames, or local paths.
- Resolve TLS trust and verification from environment/configuration; never hardcode bypasses.
- Treat unknown ACL, tenant, schema, or tool-contract state as a hard failure.
- Require explicit approval for destructive, externally visible, or irreversible actions.
- Keep runtime traces policy-scoped and privacy-sanitized.

## Specialized workflows

Read [the workflow catalog](references/catalog.md) only when the request needs a
provider-specific procedure, parameter map, script, or reference asset.
