#!/usr/bin/python
"""Pydantic input models for sql-mcp tool parameters (CONCEPT:SQL-1.5).

Typed contracts for the ``params_json`` payloads accepted by the four
action-dispatch MCP tools (``sql_query``, ``sql_execute``, ``sql_schema``,
``sql_admin``).
"""

from typing import Any

from pydantic import BaseModel, Field


class QueryInput(BaseModel):
    """Input model for ``sql_query`` actions (execute / explain)."""

    sql: str = Field(description="Single read-only statement with :name binds.")
    params: dict[str, Any] | None = Field(
        default=None, description="Bound parameter values."
    )
    max_rows: int | None = Field(
        default=None, description="Row cap (clamped to the server cap)."
    )
    timeout: float | None = Field(
        default=None, description="Statement timeout in seconds."
    )


class ExecuteInput(BaseModel):
    """Input model for ``sql_execute`` action 'execute' (DML/DDL)."""

    sql: str = Field(description="Single DML/DDL statement with :name binds.")
    params: dict[str, Any] | list[dict[str, Any]] | None = Field(
        default=None, description="Bound values; a list runs executemany."
    )
    timeout: float | None = Field(
        default=None, description="Statement timeout in seconds."
    )


class ScriptInput(BaseModel):
    """Input model for ``sql_execute`` action 'script'."""

    statements: list[str] = Field(
        description="Statements run in one all-or-nothing transaction."
    )
    timeout: float | None = Field(
        default=None, description="Per-statement timeout in seconds."
    )


class SchemaInput(BaseModel):
    """Input model for ``sql_schema`` actions."""

    table: str | None = Field(
        default=None, description="Table name (columns/indexes/foreign_keys/ddl)."
    )
    schema_name: str | None = Field(
        default=None, alias="schema", description="Schema/namespace to inspect."
    )
    limit: int | None = Field(
        default=10, description="Row preview limit for the 'sample' action."
    )
