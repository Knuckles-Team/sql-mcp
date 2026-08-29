"""Characterization tests for sql_mcp/__init__.py's PEP 562 __getattr__.

Exercises the optional-module availability flags, lazy member exposure from
OPTIONAL_MODULES, and the not-found fallback -- ahead of decomposing
__getattr__ down to complexity caps.

NOTE: deliberately does NOT ``import sql_mcp`` at module level. Doing so
binds the package object as a name in this test module's own namespace;
pytest's collector then probes every such name with
``getattr(obj, "__test__", False)`` (its nose-test compatibility check,
``_pytest.python.PyCollector.isnosetest``) while merely COLLECTING this
file -- before any test body runs. Because ``__getattr__`` treats
``__test__`` like any other unknown attribute, that probe alone imports
every OPTIONAL_MODULES entry and calls ``_expose_members`` on it, which
overwrites ``sql_mcp.mcp_server`` (the submodule) with the identically
named ``mcp_server`` function defined inside it (BUG-CX-SQLMCP-01,
reported in the lane report). ``tests/test_startup.py`` then fails because
``sql_mcp.mcp_server`` no longer resolves to the module it expects to
monkeypatch. Importing the package lazily, inside a fixture, keeps it out
of this module's collected namespace and avoids tripping the probe.
"""

import pytest


@pytest.fixture()
def sql_mcp():
    import sql_mcp as _sql_mcp

    return _sql_mcp


@pytest.fixture(autouse=True)
def _restore_sql_mcp_module_state():
    """Undo any lazy-exposure mutation a test below makes to the sql_mcp
    package namespace, so exercising these branches here cannot bleed into
    a test elsewhere in the suite that expects e.g. ``sql_mcp.mcp_server``
    to still be the submodule.
    """
    import sql_mcp as _sql_mcp

    snapshot = dict(_sql_mcp.__dict__)
    loaded_snapshot = dict(_sql_mcp._loaded_optional_modules)
    yield
    _sql_mcp.__dict__.clear()
    _sql_mcp.__dict__.update(snapshot)
    _sql_mcp._loaded_optional_modules.clear()
    _sql_mcp._loaded_optional_modules.update(loaded_snapshot)


def test_getattr_reports_mcp_available_when_module_imports(sql_mcp):
    assert sql_mcp.__getattr__("_MCP_AVAILABLE") is True


def test_getattr_reports_agent_available_when_module_imports(sql_mcp):
    assert sql_mcp.__getattr__("_AGENT_AVAILABLE") is True


def test_getattr_mcp_available_false_when_no_mcp_server_key(sql_mcp, monkeypatch):
    monkeypatch.setattr(sql_mcp, "OPTIONAL_MODULES", {"sql_mcp.agent_server": "agent"})
    assert sql_mcp.__getattr__("_MCP_AVAILABLE") is False


def test_getattr_agent_available_false_when_no_agent_server_key(sql_mcp, monkeypatch):
    monkeypatch.setattr(sql_mcp, "OPTIONAL_MODULES", {"sql_mcp.mcp_server": "mcp"})
    assert sql_mcp.__getattr__("_AGENT_AVAILABLE") is False


def test_getattr_mcp_available_false_when_import_fails(sql_mcp, monkeypatch):
    monkeypatch.setattr(sql_mcp, "_import_module_safely", lambda name: None)
    assert sql_mcp.__getattr__("_MCP_AVAILABLE") is False


def test_getattr_exposes_optional_module_member(sql_mcp):
    fn = sql_mcp.__getattr__("agent_server")
    assert callable(fn)


def test_getattr_raises_attribute_error_for_unknown_name(sql_mcp):
    with pytest.raises(AttributeError, match="definitely_not_a_real_attribute_xyz"):
        sql_mcp.__getattr__("definitely_not_a_real_attribute_xyz")


def test_getattr_skips_modules_that_fail_to_import(sql_mcp, monkeypatch):
    monkeypatch.setattr(sql_mcp, "_import_module_safely", lambda name: None)
    with pytest.raises(AttributeError):
        sql_mcp.__getattr__("some_attr_that_would_only_exist_on_optional_module")
