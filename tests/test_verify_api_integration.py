"""Characterization tests for scripts/verify_api_integration.py.

Loaded by file path (the script is not part of the installed package) and
exercised through its public functions: parse_api_client, parse_mcp_server,
verify_agent, and main's --local mode.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_SCRIPT_PATH = (
    Path(__file__).resolve().parent.parent / "scripts" / "verify_api_integration.py"
)


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "verify_api_integration_under_test", _SCRIPT_PATH
    )
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def vai():
    return _load_module()


API_CLIENT_SOURCE = '''
class SomeApiClient:
    def __init__(self):
        pass

    def authenticate(self):
        pass

    def _private_helper(self):
        pass

    def get_repositories(self):
        pass

    def list_issues(self):
        pass


class Unrelated:
    def public_thing(self):
        pass
'''

MCP_SERVER_SOURCE = '''
class Registrar:
    def register(self, mcp):
        @mcp.tool()
        def github_list_repos(client):
            return client.get_repositories()

        @mcp.tool()
        def github_list_issues(client):
            return getattr(client, "list_issues")()

        def not_a_tool(client):
            return client.get_repositories()
'''


def test_parse_api_client_finds_public_non_authenticate_methods(vai, tmp_path):
    api_client = tmp_path / "api_client.py"
    api_client.write_text(API_CLIENT_SOURCE)

    methods = vai.parse_api_client(str(api_client))

    assert set(methods) == {"get_repositories", "list_issues"}
    assert methods["get_repositories"]["class"] == "SomeApiClient"


def test_parse_api_client_ignores_non_api_client_classes(vai, tmp_path):
    api_client = tmp_path / "api_client.py"
    api_client.write_text(
        """
class Plain:
    def public_thing(self):
        pass
"""
    )

    methods = vai.parse_api_client(str(api_client))

    assert methods == {}


def test_parse_mcp_server_maps_decorated_tool_to_api_methods(vai, tmp_path):
    api_client = tmp_path / "api_client.py"
    api_client.write_text(API_CLIENT_SOURCE)
    mcp_server = tmp_path / "mcp_server.py"
    mcp_server.write_text(MCP_SERVER_SOURCE)

    api_methods = vai.parse_api_client(str(api_client))
    tool_mappings, mapped = vai.parse_mcp_server(str(mcp_server), api_methods)

    assert "github_list_repos" in tool_mappings
    assert "not_a_tool" not in tool_mappings
    assert mapped == {"get_repositories", "list_issues"}
    assert set(tool_mappings["github_list_repos"]["methods"]) == {"get_repositories"}


def test_parse_mcp_server_matches_bare_prefixed_function_without_decorator(vai, tmp_path):
    api_client = tmp_path / "api_client.py"
    api_client.write_text(API_CLIENT_SOURCE)
    mcp_server = tmp_path / "mcp_server.py"
    mcp_server.write_text(
        """
def github_undecorated(client):
    return client.get_repositories()

def plain_helper(client):
    return client.get_repositories()
"""
    )

    api_methods = vai.parse_api_client(str(api_client))
    tool_mappings, mapped = vai.parse_mcp_server(str(mcp_server), api_methods)

    assert "github_undecorated" in tool_mappings
    assert "plain_helper" not in tool_mappings
    assert mapped == {"get_repositories"}


def test_verify_agent_returns_none_when_files_missing(vai, tmp_path):
    assert vai.verify_agent(str(tmp_path)) is None


def test_verify_agent_computes_full_coverage(vai, tmp_path):
    (tmp_path / "api_client.py").write_text(API_CLIENT_SOURCE)
    (tmp_path / "mcp_server.py").write_text(MCP_SERVER_SOURCE)

    result = vai.verify_agent(str(tmp_path))

    assert result["agent_name"] == tmp_path.name
    assert result["total_methods"] == 2
    assert result["covered_methods"] == 2
    assert result["coverage"] == pytest.approx(100.0)
    assert result["unmapped"] == []


def test_verify_agent_reports_unmapped_methods_for_partial_coverage(vai, tmp_path):
    (tmp_path / "api_client.py").write_text(API_CLIENT_SOURCE)
    (tmp_path / "mcp_server.py").write_text(
        """
class Registrar:
    def register(self, mcp):
        @mcp.tool()
        def github_list_repos(client):
            return client.get_repositories()
"""
    )

    result = vai.verify_agent(str(tmp_path))

    assert result["covered_methods"] == 1
    assert result["unmapped"] == ["list_issues"]
    assert result["coverage"] == pytest.approx(50.0)


def test_main_local_mode_skips_silently_when_no_files_found(vai, tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["verify_api_integration.py", "--local"])

    with pytest.raises(SystemExit) as exc:
        vai.main()

    assert exc.value.code == 0
    assert "Skipping integration parity verification" in capsys.readouterr().out


def test_main_local_mode_passes_when_coverage_meets_baseline(vai, tmp_path, monkeypatch, capsys):
    (tmp_path / "api_client.py").write_text(API_CLIENT_SOURCE)
    (tmp_path / "mcp_server.py").write_text(MCP_SERVER_SOURCE)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["verify_api_integration.py", "--local"])
    monkeypatch.setitem(vai.BASELINES, tmp_path.name, 100.0)

    with pytest.raises(SystemExit) as exc:
        vai.main()

    assert exc.value.code == 0
    assert "PASSED" in capsys.readouterr().out


def test_main_local_mode_fails_when_coverage_degrades_below_baseline(vai, tmp_path, monkeypatch, capsys):
    (tmp_path / "api_client.py").write_text(API_CLIENT_SOURCE)
    (tmp_path / "mcp_server.py").write_text(
        """
class Registrar:
    def register(self, mcp):
        @mcp.tool()
        def github_list_repos(client):
            return client.get_repositories()
"""
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["verify_api_integration.py", "--local"])
    monkeypatch.setitem(vai.BASELINES, tmp_path.name, 100.0)

    with pytest.raises(SystemExit) as exc:
        vai.main()

    out = capsys.readouterr().out
    assert exc.value.code == 1
    assert "FAILED" in out
    assert "list_issues" in out


def test_main_workspace_scan_reports_all_discovered_agents(vai, tmp_path, monkeypatch, capsys):
    agents_root = tmp_path / "agent-packages" / "agents"
    agent_ok = agents_root / "agent-ok"
    agent_gap = agents_root / "agent-gap"
    agent_ok.mkdir(parents=True)
    agent_gap.mkdir(parents=True)
    (agent_ok / "api_client.py").write_text(API_CLIENT_SOURCE)
    (agent_ok / "mcp_server.py").write_text(MCP_SERVER_SOURCE)
    (agent_gap / "api_client.py").write_text(API_CLIENT_SOURCE)
    (agent_gap / "mcp_server.py").write_text(
        """
class Registrar:
    def register(self, mcp):
        @mcp.tool()
        def github_list_repos(client):
            return client.get_repositories()
"""
    )
    # main() derives agents_dir from its own file location two levels up
    # from scripts/; simulate that by pointing __file__ inside the temp tree
    # at <agents_root>/some-agent/scripts/verify_api_integration.py so that
    # dirname(__file__)/../.. resolves back to agents_root.
    fake_script_dir = agents_root / "some-agent" / "scripts"
    fake_script_dir.mkdir(parents=True)
    fake_script = fake_script_dir / "verify_api_integration.py"
    fake_script.write_text(_SCRIPT_PATH.read_text())

    spec = importlib.util.spec_from_file_location(
        "verify_api_integration_workspace_scan", fake_script
    )
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    monkeypatch.setattr(sys, "argv", ["verify_api_integration.py"])

    module.main()

    out = capsys.readouterr().out
    assert "API to MCP Integration Parity Report" in out
    assert "agent-ok" in out
    assert "agent-gap" in out
    assert "list_issues" in out  # unmapped method surfaced in the gap detail
