# CONN-SQL-MCP-CONNECTOR-CONTENT — Requirements

Governing spec: [spec.md](spec.md).

Each row is one requirement. A row names the file it touches and the test that proves it. The generator sets each row's state in `status.json`.

| ID | Requirement | Acceptance |
|---|---|---|
| `CONN-SQL-MCP-CONNECTOR-CONTENT-R001` | **Default content.** `pyproject.toml` declares `sql-mcp` as the single `scion_sdk.connector` entry point. The server lists the packaged `skill://` and `ontology://` resources and the packaged prompts with no `content=` argument. Proving test: `tests/test_default_content_surfaces.py`. | `resources/list` includes `skill://` and `ontology://`; `prompts/list` includes each packaged prompt. |
| `CONN-SQL-MCP-CONNECTOR-CONTENT-R002` | **Register the approved SQL receiver in the served tool surface.** Subsystem: connector. Caller: process start → `sql_mcp/mcp_server.py` → `scion_sdk.adapters.sql_source.register_sql_source_tools(server, client)`. The connector implements `SqlExecutor` on its SQLAlchemy engine with `stream_results=True` and `fetchmany`, opened read-only. The connector keeps its driver and credentials; the SDK keeps approval and bounds. Refusals: `unsupported_dialect` for a dialect without a read-only session. Writes: none. Depends on: SCION-SOURCE-INGEST-R004.9. | Test: `tests/test_approved_sql_served.py::test_sql_mcp_serves_approved_query` (L3) calls the registered tool against a local database. It asserts rows, bounds and a refusal for a write statement. |
| `CONN-SQL-MCP-CONNECTOR-CONTENT-R003` | **Column profile in the SQL catalog ingest.** Subsystem: sql-mcp ingest. In `sql_mcp/kg_ingest.py::catalog_to_entities`, call `scion_sdk.ingest.sql_profile.build_column_profile` for each catalog column and put the result in the column entity properties under `column_profile`. The tool in `sql_mcp/mcp/mcp_sql.py` passes the sample size from `SQL_PROFILE_SAMPLE_ROWS`. Depends on: SCION-SOURCE-INGEST-R905. | Test: `tests/test_catalog_profile.py::test_every_column_entity_has_a_profile` (L3). A served test lists the column entities of a fixture database. |
