"""Main FastMCP server and tool registration for sql-mcp."""

from agent_connector_sdk.connector_hooks import Readiness

from sql_mcp.auth import get_api
from sql_mcp.mcp.mcp_sql import register_sql_tools

# SDK discovery registers the register_<tag>_tools functions bound in this module.
__all__ = ["register_sql_tools"]


async def readiness() -> Readiness:
    try:
        get_api()
    except Exception:
        return Readiness(False)
    return Readiness(True)
