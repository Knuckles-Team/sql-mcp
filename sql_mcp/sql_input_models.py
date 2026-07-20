#!/usr/bin/python
"""Pydantic input models for sql-mcp tool parameters (CONCEPT:SQ-OS.governance.action-routing-through-fastmcp).

Typed contracts for the ``params_json`` payloads accepted by the four
action-dispatch MCP tools (``sql_query``, ``sql_execute``, ``sql_schema``,
``sql_admin``).
"""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class StrictInput(BaseModel):
    """Base contract that rejects misspelled or unsupported arguments."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True, strict=True)


class QueryInput(StrictInput):
    """Input model for ``sql_query`` actions (execute / explain)."""

    sql: str = Field(
        min_length=1,
        max_length=1_000_000,
        description="Single read-only statement with :name binds.",
    )
    params: dict[str, Any] | None = Field(
        default=None, description="Bound parameter values."
    )
    max_rows: int | None = Field(
        default=None, ge=1, description="Row cap (clamped to the server cap)."
    )
    timeout: float | None = Field(
        default=None,
        gt=0,
        allow_inf_nan=False,
        description="Statement timeout in seconds.",
    )


class ExecuteInput(StrictInput):
    """Input model for ``sql_execute`` action 'execute' (DML/DDL)."""

    sql: str = Field(
        min_length=1,
        max_length=1_000_000,
        description="Single DML/DDL statement with :name binds.",
    )
    params: dict[str, Any] | list[dict[str, Any]] | None = Field(
        default=None, description="Bound values; a list runs executemany."
    )
    timeout: float | None = Field(
        default=None,
        gt=0,
        allow_inf_nan=False,
        description="Statement timeout in seconds.",
    )
    max_rows: int | None = Field(
        default=None, ge=1, description="Bound for DML RETURNING rows."
    )


class ScriptStatement(StrictInput):
    """One parameterized statement in a managed transaction."""

    sql: str = Field(min_length=1, max_length=1_000_000)
    params: dict[str, Any] | list[dict[str, Any]] | None = None


class ScriptInput(StrictInput):
    """Input model for ``sql_execute`` action 'script'."""

    statements: list[str | ScriptStatement] = Field(
        min_length=1,
        max_length=100,
        description="Statements run in one all-or-nothing transaction.",
    )
    timeout: float | None = Field(
        default=None,
        gt=0,
        allow_inf_nan=False,
        description="Whole-script timeout in seconds.",
    )


class SchemaInput(StrictInput):
    """Input model for ``sql_schema`` actions."""

    table: str | None = Field(
        default=None,
        min_length=1,
        max_length=512,
        description="Table name for table-scoped reflection actions.",
    )
    view: str | None = Field(
        default=None,
        min_length=1,
        max_length=512,
        description="View name for view_definition.",
    )
    schema_name: str | None = Field(
        default=None,
        alias="schema",
        max_length=512,
        description="Schema/namespace to inspect.",
    )
    limit: int | None = Field(
        default=None, ge=1, description="Page or sample row limit."
    )
    offset: int = Field(default=0, ge=0, description="Metadata page offset.")
    max_objects: int | None = Field(
        default=None, ge=1, description="Schema catalog object cap."
    )
    include_views: bool = True
    timeout: float | None = Field(default=None, gt=0, allow_inf_nan=False)


class AdminInput(StrictInput):
    """Admin actions currently take no JSON arguments."""


class IngestInput(StrictInput):
    """Bounded Epistemic Graph schema-ingestion arguments."""

    schema_name: str | None = Field(default=None, alias="schema", max_length=512)
    include_views: bool = True
    include_indexes: bool = True
    max_objects: int = Field(default=5_000, ge=1, le=5_000)
