# CONN-SQL-MCP-CONNECTOR-CONTENT — Test specification

Governing spec: [spec.md](spec.md).

| Test ID | Requirement | Proving test | Expected observation |
|---|---|---|---|
| T-001 | `CONN-SQL-MCP-CONNECTOR-CONTENT-R001` | `tests/test_default_content_surfaces.py::test_default_content_surfaces` (planned) | `resources/list` includes `skill://` and `ontology://`; `prompts/list` includes each packaged prompt. |
| T-002 | `CONN-SQL-MCP-CONNECTOR-CONTENT-R002` | `tests/test_approved_sql_served.py::test_sql_mcp_serves_approved_query` (planned) | Test: `tests/test_approved_sql_served.py::test_sql_mcp_serves_approved_query` (L3) calls the registered tool against a local database. It asserts rows, bounds and a refusal for a write statement. |
| T-003 | `CONN-SQL-MCP-CONNECTOR-CONTENT-R003` | `sql_mcp/kg_ingest.py::catalog_to_entities` | Test: `tests/test_catalog_profile.py::test_every_column_entity_has_a_profile` (L3). A served test lists the column entities of a fixture database. |

## Negative and boundary cases

Each proving test above includes the refusal or error case that its row names. A vendor outage or an unauthorised call must return the SDK typed error.

## Quality and release proof

Run `uv run pytest tests` and `pre-commit run --all-files` from the repository root. A planned test is added by the code change that lands the row.
