# CONN-SQL-MCP-CONNECTOR-CONTENT — The connector serves its packaged content

Owner: sql-mcp. Cross-repo IDs: `SCION-CONNECTOR-CONTROL-R071`, `SCION-CONNECTOR-CONTROL-R073`.

## Purpose and user stories

The `sql-mcp` server serves its packaged skills, prompts and ontology to any client, with no wiring of its own.

## Delivery mapping

Component: sql-mcp connector

Code: ../../sql_mcp/__init__.py

## Why a new spec

Searched `specs/` of `sql-mcp` with `git grep` for the terms of this spec. No other spec of this repository owns the capability, so this spec owns it.

## User Scenarios & Testing

### User Story 1 - Default content (Priority: P1)

The fleet operator and the engine rely on this behaviour of `sql-mcp`: `pyproject.toml` declares `sql-mcp` as the single `scion_sdk.connector` entry point. It is proven independently of the other stories.

**Acceptance Scenarios**:

1. **Given** the `sql-mcp` connector built from the default branch, **When** `tests/test_default_content_surfaces.py::test_default_content_surfaces` runs, **Then** `resources/list` includes `skill://` and `ontology://`; `prompts/list` includes each packaged prompt.

### User Story 2 - Register the approved SQL receiver in the served tool surface (Priority: P1)

The fleet operator and the engine rely on this behaviour of `sql-mcp`: Subsystem: connector. It is proven independently of the other stories.

**Acceptance Scenarios**:

1. **Given** the `sql-mcp` connector built from the default branch, **When** `tests/test_approved_sql_served.py::test_sql_mcp_serves_approved_query` runs, **Then** test: `tests/test_approved_sql_served.py::test_sql_mcp_serves_approved_query` (L3) calls the registered tool against a local database. It asserts rows, bounds and a refusal for a write statement.

### User Story 3 - Column profile in the SQL catalog ingest (Priority: P1)

The fleet operator and the engine rely on this behaviour of `sql-mcp`: Subsystem: sql-mcp ingest. It is proven independently of the other stories.

**Acceptance Scenarios**:

1. **Given** the `sql-mcp` connector built from the default branch, **When** `sql_mcp/kg_ingest.py::catalog_to_entities` runs, **Then** test: `tests/test_catalog_profile.py::test_every_column_entity_has_a_profile` (L3). A served test lists the column entities of a fixture database.

### Edge Cases

- The vendor service is unreachable or rejects the credential: the connector returns the SDK typed error and never a partial result.
- An argument outside the documented inputs is refused with the SDK typed refusal and causes no effect on the vendor service.

## Requirements

- **FR-001**: Default content. Rows: `CONN-SQL-MCP-CONNECTOR-CONTENT-R001`.
- **FR-002**: Register the approved SQL receiver in the served tool surface. Rows: `CONN-SQL-MCP-CONNECTOR-CONTENT-R002`.
- **FR-003**: Column profile in the SQL catalog ingest. Rows: `CONN-SQL-MCP-CONNECTOR-CONTENT-R003`.

## Success Criteria

- **SC-001**: `resources/list` includes `skill://` and `ontology://`; `prompts/list` includes each packaged prompt. Rows: `CONN-SQL-MCP-CONNECTOR-CONTENT-R001`.
- **SC-002**: Test: `tests/test_approved_sql_served.py::test_sql_mcp_serves_approved_query` (L3) calls the registered tool against a local database. It asserts rows, bounds and a refusal for a write statement. Rows: `CONN-SQL-MCP-CONNECTOR-CONTENT-R002`.
- **SC-003**: Test: `tests/test_catalog_profile.py::test_every_column_entity_has_a_profile` (L3). A served test lists the column entities of a fixture database. Rows: `CONN-SQL-MCP-CONNECTOR-CONTENT-R003`.

## Assumptions

- The `sql-mcp` package keeps the entry point and module layout named in the rows.
- The shared SDK supplies the transport, authentication, retry and certification helpers the rows reuse.

## Traceability

| Label | Rows | Design section | Test ID | Evidence |
|---|---|---|---|---|
| FR-001 | `CONN-SQL-MCP-CONNECTOR-CONTENT-R001` | plan.md Production caller chain | T-001 | tests/test_default_content_surfaces.py::test_default_content_surfaces |
| FR-002 | `CONN-SQL-MCP-CONNECTOR-CONTENT-R002` | plan.md Production caller chain | T-002 | tests/test_approved_sql_served.py::test_sql_mcp_serves_approved_query |
| FR-003 | `CONN-SQL-MCP-CONNECTOR-CONTENT-R003` | plan.md Production caller chain | T-003 | sql_mcp/kg_ingest.py::catalog_to_entities |
