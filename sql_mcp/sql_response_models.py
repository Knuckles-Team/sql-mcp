#!/usr/bin/python
"""Pydantic response models for sql-mcp result envelopes (CONCEPT:SQ-OS.governance.sql-3).

Typed contracts for the bounded envelopes returned by the
:class:`~sql_mcp.api_client.Api` facade and surfaced through the MCP tools.
"""

from typing import Any

from pydantic import BaseModel, Field


class QueryResponse(BaseModel):
    """Bounded result envelope for read-only queries."""

    columns: list[dict[str, Any]] = Field(
        default_factory=list, description="Column metadata in select order."
    )
    rows: list[dict[str, Any]] = Field(
        default_factory=list, description="JSON-safe rows capped by count and bytes."
    )
    row_count: int = Field(default=0, ge=0, description="Number of rows returned.")
    truncated: bool = Field(
        default=False, description="True when a count or byte cap cut the result."
    )
    bytes_returned: int = Field(
        default=0, ge=0, description="Approximate encoded row bytes returned."
    )


class ExecuteResponse(BaseModel):
    """Result envelope for DML/DDL statements."""

    rowcount: int = Field(description="Driver-reported affected-row count.")
    columns: list[dict[str, Any]] | None = None
    rows: list[dict[str, Any]] | None = None
    row_count: int | None = Field(default=None, ge=0)
    truncated: bool | None = None
    bytes_returned: int | None = Field(default=None, ge=0)


class PingResponse(BaseModel):
    """Connection health envelope for ``sql_admin`` action 'ping'."""

    ok: bool | None = Field(default=None, description="Connection succeeded.")
    connection: str | None = None
    latency_ms: float | None = Field(
        default=None, ge=0, description="Round-trip latency in milliseconds."
    )
