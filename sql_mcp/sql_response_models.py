#!/usr/bin/python
"""Pydantic response models for sql-mcp result envelopes (CONCEPT:SQL-1.4).

Typed contracts for the bounded envelopes returned by the
:class:`~sql_mcp.api_client.Api` facade and surfaced through the MCP tools.
"""

from typing import Any

from pydantic import BaseModel, Field


class QueryResponse(BaseModel):
    """Bounded result envelope for read-only queries."""

    columns: list[str] | None = Field(
        default=None, description="Result column names, in select order."
    )
    rows: list[list[Any]] | None = Field(
        default=None, description="Row values (JSON-safe), capped at max_rows."
    )
    row_count: int | None = Field(default=None, description="Number of rows returned.")
    truncated: bool | None = Field(
        default=None, description="True when the row cap cut the result short."
    )
    elapsed_seconds: float | None = Field(
        default=None, description="Wall-clock execution time."
    )


class ExecuteResponse(BaseModel):
    """Result envelope for DML/DDL statements."""

    affected_rows: int | None = Field(
        default=None, description="Rows affected by the statement."
    )
    elapsed_seconds: float | None = Field(
        default=None, description="Wall-clock execution time."
    )


class PingResponse(BaseModel):
    """Connection health envelope for ``sql_admin`` action 'ping'."""

    ok: bool | None = Field(default=None, description="Connection succeeded.")
    latency_seconds: float | None = Field(
        default=None, description="Round-trip latency of SELECT 1."
    )
    raw: dict[str, Any] | None = Field(
        default=None, description="Raw response payload."
    )
