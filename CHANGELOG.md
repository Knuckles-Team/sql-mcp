# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-06-11
### Added
- `SqlApi` — SQLAlchemy 2.x Core facade with named multi-connection support,
  read-only statement gate, per-call row cap + timeout, and bounded result
  envelopes (columns + rows + truncation flag).
- Dialect registry for SQLite (core), PostgreSQL, MySQL/MariaDB, MSSQL, and
  Oracle with per-dialect pip extras and self-explanatory missing-driver errors.
- Four action-routed MCP tools: `sql_query` (execute/explain), `sql_execute`
  (execute/script, gated by `SQL_ALLOW_WRITES`), `sql_schema`
  (schemas/tables/views/columns/indexes/foreign_keys/ddl/sample), and
  `sql_admin` (ping/version/active_connections/connections/dialects).
- Named connections from `SQL_CONNECTIONS` JSON, `SQL_URL`, or discrete
  `SQL_HOST`/`SQL_USERNAME`/... env fields; zero-infra in-memory SQLite
  fallback; passwords only rendered redacted.
- `sql-agent` A2A agent server entry point.
- Full pytest suite against in-memory SQLite plus mock-based dialect-path tests.
