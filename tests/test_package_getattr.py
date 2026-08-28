"""Characterization tests for sql_mcp/__init__.py's PEP 562 __getattr__.

Exercises the optional-module availability flags, lazy member exposure from
OPTIONAL_MODULES, and the not-found fallback -- ahead of decomposing
__getattr__ down to complexity caps.
"""

import pytest

import sql_mcp


def test_getattr_reports_mcp_available_when_module_imports():
    assert sql_mcp.__getattr__("_MCP_AVAILABLE") is True


def test_getattr_reports_agent_available_when_module_imports():
    assert sql_mcp.__getattr__("_AGENT_AVAILABLE") is True


def test_getattr_mcp_available_false_when_no_mcp_server_key(monkeypatch):
    monkeypatch.setattr(sql_mcp, "OPTIONAL_MODULES", {"sql_mcp.agent_server": "agent"})
    assert sql_mcp.__getattr__("_MCP_AVAILABLE") is False


def test_getattr_agent_available_false_when_no_agent_server_key(monkeypatch):
    monkeypatch.setattr(sql_mcp, "OPTIONAL_MODULES", {"sql_mcp.mcp_server": "mcp"})
    assert sql_mcp.__getattr__("_AGENT_AVAILABLE") is False


def test_getattr_mcp_available_false_when_import_fails(monkeypatch):
    monkeypatch.setattr(sql_mcp, "_import_module_safely", lambda name: None)
    assert sql_mcp.__getattr__("_MCP_AVAILABLE") is False


def test_getattr_exposes_optional_module_member():
    fn = sql_mcp.__getattr__("agent_server")
    assert callable(fn)


def test_getattr_raises_attribute_error_for_unknown_name():
    with pytest.raises(AttributeError, match="definitely_not_a_real_attribute_xyz"):
        sql_mcp.__getattr__("definitely_not_a_real_attribute_xyz")


def test_getattr_skips_modules_that_fail_to_import(monkeypatch):
    monkeypatch.setattr(sql_mcp, "_import_module_safely", lambda name: None)
    with pytest.raises(AttributeError):
        sql_mcp.__getattr__("some_attr_that_would_only_exist_on_optional_module")
