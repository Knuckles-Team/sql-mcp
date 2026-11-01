# CONN-SQL-MCP-CONNECTOR-CONTENT — Quickstart

The shortest path that shows the served behaviour working.

```text
uv run pytest sql_mcp/kg_ingest.py tests/test_approved_sql_served.py tests/test_catalog_profile.py tests/test_default_content_surfaces.py
```

The command starts the connector in process and calls the served tools through the MCP client. A test marked planned in `test-spec.md` runs once the code change that lands its row adds it.
