"""sql-mcp: Generic SQL database API + MCP Server + A2A Server (SQLAlchemy 2.x Core)."""

import importlib
import inspect
from typing import Any

__version__ = "0.1.0"
__all__: list[str] = []

CORE_MODULES = ["sql_mcp.api_client"]
OPTIONAL_MODULES = {
    "sql_mcp.agent_server": "agent",
    "sql_mcp.mcp_server": "mcp",
}


def _expose_members(module):
    for name, obj in inspect.getmembers(module):
        if (inspect.isclass(obj) or inspect.isfunction(obj)) and not name.startswith(
            "_"
        ):
            globals()[name] = obj
            if name not in __all__:
                __all__.append(name)


for module_name in CORE_MODULES:
    module = importlib.import_module(module_name)
    _expose_members(module)

_loaded_optional_modules: dict = {}


def _import_module_safely(module_name: str):
    try:
        return importlib.import_module(module_name)
    except ImportError:
        return None


def _optional_module_available(name_fragment: str) -> bool:
    key = next((k for k in OPTIONAL_MODULES if name_fragment in k), None)
    return _import_module_safely(key) is not None if key else False


def _ensure_optional_module_loaded(module_name: str):
    if module_name not in _loaded_optional_modules:
        module = _import_module_safely(module_name)
        if module is not None:
            _loaded_optional_modules[module_name] = module
            _expose_members(module)
    return _loaded_optional_modules.get(module_name)


def _resolve_optional_attribute(name: str) -> Any:
    for module_name in OPTIONAL_MODULES:
        module = _ensure_optional_module_loaded(module_name)
        if module is not None and hasattr(module, name):
            return getattr(module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __getattr__(name: str) -> Any:
    if name == "_MCP_AVAILABLE":
        return _optional_module_available("mcp_server")
    if name == "_AGENT_AVAILABLE":
        return _optional_module_available("agent_server")
    return _resolve_optional_attribute(name)


def __dir__() -> list[str]:
    return sorted(list(globals().keys()) + __all__)
