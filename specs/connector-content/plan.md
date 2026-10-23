# CONN-SQL-MCP-CONNECTOR-CONTENT — Design and implementation plan

Governing spec: [spec.md](spec.md).

## Architecture

`pyproject.toml` declares `sql-mcp` as the connector identity. `create_mcp_server` resolves the packaged content of `sql_mcp` from it.
