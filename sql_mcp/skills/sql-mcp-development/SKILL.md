---
name: sql-mcp-development
skill_type: skill
description: >-
  Develop, test, and release the sql-mcp connector while preserving its
  SQLAlchemy Core, MCP action, safety, packaged-content, and spec-delivery
  contracts. Use when changing SQL access, dialect support, connector content,
  documentation, workflows, or repository-owned specifications.
license: MIT
tags: [sql, database, connector, development, testing, pages, specs]
metadata:
  author: Genius
  version: '0.1.0'
---
# SQL MCP Development

Use this skill for changes inside the `sql-mcp` package. The connector owns the
SQLAlchemy Core facade, named-connection configuration, dialect registry,
read-only safety gate, bounded result envelopes, knowledge-graph ingestion, and
the action-routed MCP tools. Shared transports and connector contracts belong
to `agent-connector-sdk`; admission, serving, and durable graph state belong to
their owning repositories.

## Repository map

- `sql_mcp/api_client.py` is the SQLAlchemy Core facade and connection lifecycle.
- `sql_mcp/mcp_server.py` exposes the four action-routed MCP tool surfaces.
- `sql_mcp/dialects.py` owns dialect registration and driver guidance.
- `sql_mcp/safety.py` owns read-only classification and write-policy checks.
- `sql_mcp/auth.py` owns named connections, environment parsing, and redaction.
- `sql_mcp/skills/`, prompts, ontology, and connector resources are packaged
  content exposed through the connector entry point.
- `specs/` contains repository-owned source specifications and generated status
  evidence; `docs/` is the MkDocs source published by the shared Pages workflow.

## Rapid delivery: the 5-minute contract

Specs are already designed. Deliver one small, reviewable slice at a time.

- Find the owning row with `git grep -n "<term>" -- specs` before adding
  behavior. Extend an existing spec before writing a new requirement.
- Trace a changed action from its typed input through the MCP router, the
  SQLAlchemy Core facade, safety policy, and bounded response envelope. Reuse
  those seams instead of duplicating a connector path.
- Keep a change inside this connector. SDK transports, Arbora admission, MCP
  multiplexing, and graph persistence belong in their owning repositories.
- Bind every user value through SQLAlchemy `text()` parameters. Never assemble
  user SQL with f-strings, `%`, or string concatenation, and route identifiers
  through SQLAlchemy reflection or expression objects.
- Preserve the read-only statement gate for `sql_query`; `sql_execute` writes
  remain server-policy controlled by `SQL_ALLOW_WRITES` and never gain a
  per-call override. Keep row caps and statement timeouts on every result path.
- Keep credentials, DSNs, database contents, and live provider calls out of
  tests and logs. Use the existing in-memory SQLite and mock seams; redact
  passwords with `hide_password=True` before rendering any URL.
- Every behavior change needs a focused test. Generated `specs/*/status.json`
  files come from `pipelines-hook spec-status`; never hand-edit delivery state.
- Use one logical change per commit with `Spec: <ID>` or an explicit
  `Spec: none (<reason>)` trailer and the assisting-agent trailer. Stage only
  reviewed paths.

## Setup and gates

Use the locked project environment and do not install database drivers or create
live connections for a local check:

```bash
uv sync --locked
uvx pre-commit install --hook-type pre-commit --hook-type pre-push
uvx pre-commit run --all-files
```

For focused feedback, run the smallest relevant existing tests:

```bash
uv run --locked pytest tests/test_safety.py tests/test_api_wrapper.py -q
uv run --locked pytest tests/test_startup.py tests/test_package_getattr.py -q
```

The canonical pre-commit configuration delegates connector-standard, secrets,
spec-status, spec-decomposition, spec-trailers, tests-fast, and dependency
readiness checks to `Knuckles-Team/pipelines` at `rev: main`. Keep those shared
hooks; do not copy their implementation into this repository or bypass a
failure.

## Spec delivery and Pages

`.github/workflows/pages.yml` calls
`Knuckles-Team/pipelines/.github/workflows/pages_pipeline.yml@main` with
`content_source: docs`, `spec_dashboard_enabled: true`, and
`.github/spec-dashboard.json`. The dashboard config is version 1 and reads only
`specs/*/status.json`. Keep the push paths for docs, specs, the dashboard
config, and the caller workflow so a source change publishes the page.

Do not claim a spec row from a YAML marker alone. Proof requires the generated
status records, a successful exact-source Pages run, and the public
`/spec-delivery/` page and snapshot serving the candidate revision. Inspect the
complete diff and live evidence before reporting delivery.

## Packaging and release

Skills and other connector resources are included by the existing
`sql_mcp` package-data globs. When a packaged skill or resource changes, bump
the project patch version using the repository's version tool and refresh
`uv.lock` in the same release slice. Confirm the wheel/sdist contains the new
path before publication. Publish the package first; let the central container
workflow consume that exact public version, and report a central workflow
failure with its exact run rather than adding a fake extra or bypassing a gate.

## Safety

Never commit `.env` files, credentials, raw DSNs, database dumps, live query
results, generated sites, caches, or temporary output. Work in a real Git
worktree based on current `origin/main`, inspect `git status --short` and the
complete candidate diff, and do not use `git stash`, `git add -A`, or
`git add .`.
