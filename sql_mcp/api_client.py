"""Public client facade for sql_mcp."""

import functools
import inspect
from typing import Any

from sql_mcp.api.api_client_sql import SqlApi


class Api(SqlApi):
    """Multi-connection SQL client (SQLAlchemy 2.x Core) for the fleet."""

    pass


#: Plumbing on ``Api`` that is not a database operation: the SQLAlchemy engine
#: handle, pool teardown and the internal dialect record. They stay on ``Api``
#: for in-process callers but are never served as MCP tools.
_NOT_OPERATIONS = frozenset({"engine", "dispose", "dialect_spec"})


def _delegate(name: str):
    original = getattr(Api, name)

    @functools.wraps(original)
    def call(self: "OperationApi", *args: Any, **kwargs: Any) -> Any:
        return getattr(self._api, name)(*args, **kwargs)

    return call


class OperationApi:
    """The operations of ``Api`` that the MCP server serves, one tool each."""

    def __init__(self, api: Api) -> None:
        self._api = api


for _name, _member in inspect.getmembers(Api, inspect.isfunction):
    if not _name.startswith("_") and _name not in _NOT_OPERATIONS:
        setattr(OperationApi, _name, _delegate(_name))
