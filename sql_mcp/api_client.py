"""Public client facade for sql_mcp."""

from sql_mcp.api.api_client_sql import SqlApi


class Api(SqlApi):
    """Multi-connection SQL client (SQLAlchemy 2.x Core) for the fleet."""

    pass
