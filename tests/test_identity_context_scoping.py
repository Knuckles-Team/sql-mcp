"""Identity-scoped connection auto-load (CONCEPT:AU-OS.identity.identity-scoped-resource-autoload).

The caller's entitled SQL connections auto-load; a non-entitled named
connection is denied; the default falls to the first entitled when the
configured default is off-limits. Tests the resolution/enforcement logic with
the entitlement source mocked (the resolver itself is tested in
agent-utilities, per the container-manager-mcp/vector-mcp/documentdb-mcp
reference pattern: a fake ``agent_utilities.security.entitlements`` module
rather than reassigning ``SqlApi._entitled`` on the instance).
"""

import sys
import types

import pytest

from tests.conftest import build_api


def _install_fake_entitlements(entitled_names) -> None:
    """Install a fake ``agent_utilities.security.entitlements`` module."""
    module = types.ModuleType("agent_utilities.security.entitlements")
    module.identity_scoped_resources = lambda namespace, names: [
        n for n in names if n in entitled_names
    ]
    sys.modules["agent_utilities.security.entitlements"] = module


@pytest.fixture(autouse=True)
def _cleanup_fake_module():
    yield
    sys.modules.pop("agent_utilities.security.entitlements", None)


def _api(entitled):
    _install_fake_entitlements(entitled)
    return build_api()


def test_connection_names_filters_to_entitled():
    api = _api({"primary"})
    assert api.connection_names() == ["primary"]


def test_auto_selects_entitled_default():
    # default_connection() == "primary" (first configured)
    api = _api({"primary"})
    assert api.resolve_connection(None) == "primary"


def test_default_not_entitled_falls_to_first_entitled():
    api = _api({"analytics"})
    assert api.resolve_connection(None) == "analytics"


def test_named_connection_not_entitled_is_denied():
    api = _api({"primary"})
    with pytest.raises(PermissionError):
        api.resolve_connection("analytics")


def test_named_entitled_connection_allowed():
    api = _api({"primary", "analytics"})
    assert api.resolve_connection("analytics") == "analytics"


def test_no_entitled_connections_raises():
    api = _api(set())
    with pytest.raises(ValueError, match="available to your identity"):
        api.resolve_connection(None)


def test_unknown_connection_name_raises():
    api = _api({"primary"})
    with pytest.raises(ValueError, match="Unknown SQL connection"):
        api.resolve_connection("ghost")


def test_describe_connections_filters_to_entitled():
    api = _api({"primary"})
    names = {c["name"] for c in api.describe_connections()}
    assert names == {"primary"}
