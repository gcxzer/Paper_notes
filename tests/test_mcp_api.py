from __future__ import annotations

import stat

from tools.mcp.settings import public_mcp_settings, read_mcp_settings
from ui.backend import mcp_api


def test_mcp_settings_api_saves_reads_and_redacts_secrets(tmp_path, monkeypatch):
    settings_path = tmp_path / ".paper-notes" / "mcp-servers.json"
    resets = []
    monkeypatch.setattr(mcp_api, "_reset_agent_service", lambda: resets.append(True))

    payload = mcp_api.update_mcp_settings({
        "servers": [{
            "id": "filesystem",
            "name": "Filesystem",
            "enabled": True,
            "transport": "stdio",
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-filesystem"],
            "env": [{"name": "API_KEY", "value": "super-secret"}],
            "headers": [{"name": "Authorization", "value": "Bearer super-secret"}],
            "includeTools": "read_*\nlist_resources,search",
            "excludeTools": ["write_*", "delete_file", "write_*"],
            "timeoutSeconds": 5,
            "connectTimeoutSeconds": 3,
        }]
    }, settings_path=settings_path)

    stored = read_mcp_settings(settings_path)
    server = stored["servers"][0]
    assert resets == [True]
    assert server["env"] == {"API_KEY": "super-secret"}
    assert server["headers"] == {"Authorization": "Bearer super-secret"}
    assert server["includeTools"] == ["read_*", "list_resources", "search"]
    assert server["excludeTools"] == ["write_*", "delete_file"]
    assert stat.S_IMODE(settings_path.stat().st_mode) == 0o600
    assert payload["servers"][0]["env"] == [{"name": "API_KEY", "configured": True}]
    assert payload["servers"][0]["headers"] == [{"name": "Authorization", "configured": True}]
    assert payload["servers"][0]["includeTools"] == ["read_*", "list_resources", "search"]
    assert payload["servers"][0]["excludeTools"] == ["write_*", "delete_file"]
    assert "super-secret" not in str(payload)


def test_mcp_settings_update_preserves_redacted_existing_secret(tmp_path, monkeypatch):
    settings_path = tmp_path / "mcp-servers.json"
    monkeypatch.setattr(mcp_api, "_reset_agent_service", lambda: None)
    mcp_api.update_mcp_settings({
        "servers": [{
            "id": "filesystem",
            "name": "Filesystem",
            "transport": "stdio",
            "command": "npx",
            "env": [{"name": "API_KEY", "value": "original-secret"}],
        }]
    }, settings_path=settings_path)

    mcp_api.update_mcp_settings({
        "servers": [{
            "id": "filesystem",
            "name": "Filesystem",
            "transport": "stdio",
            "command": "node",
            "env": [{"name": "API_KEY", "configured": True, "value": ""}],
        }]
    }, settings_path=settings_path)

    server = read_mcp_settings(settings_path)["servers"][0]
    assert server["command"] == "node"
    assert server["env"] == {"API_KEY": "original-secret"}


def test_mcp_test_endpoint_probes_without_persisting(tmp_path, monkeypatch):
    calls = []

    def fake_probe(server):
        calls.append(server)
        return {
            "success": True,
            "toolCount": 1,
            "tools": [{"name": "search", "generatedName": "mcp_test_search"}],
            "error": "",
        }

    monkeypatch.setattr(mcp_api, "probe_mcp_server", fake_probe)
    result = mcp_api.test_mcp_server({
        "id": "test",
        "name": "Test",
        "transport": "http",
        "url": "http://localhost:9999/mcp",
        "headers": [{"name": "Authorization", "value": "Bearer token"}],
        "include_tools": ["search", "list_*"],
        "exclude_tools": "delete_*, write_file",
    })

    assert result["success"] is True
    assert calls[0]["transport"] == "http"
    assert calls[0]["headers"] == {"Authorization": "Bearer token"}
    assert calls[0]["includeTools"] == ["search", "list_*"]
    assert calls[0]["excludeTools"] == ["delete_*", "write_file"]
    assert not (tmp_path / "mcp-servers.json").exists()


def test_public_mcp_settings_includes_status_and_never_plaintext():
    payload = public_mcp_settings(
        {
            "servers": [{
                "id": "filesystem",
                "name": "Filesystem",
                "enabled": False,
                "transport": "stdio",
                "command": "npx",
                "env": {"API_KEY": "secret"},
                "headers": {},
                "include_tools": ["read_*"],
                "exclude_tools": ["write_*"],
            }]
        },
        statuses={
            "filesystem": {
                "connected": False,
                "error": "not started",
                "toolCount": 0,
                "state": "circuit_open",
                "failureCount": 5,
                "nextRetryAt": 1779022200.0,
                "circuitOpen": True,
                "securityWarnings": [{
                    "code": "mcp_prompt_injection_suspected",
                    "surface": "tool_description",
                    "message": "External MCP metadata contains instruction-like text.",
                }],
                "tools": [{
                    "name": "search",
                    "generatedName": "mcp_filesystem_search",
                    "securityWarnings": [{"code": "mcp_prompt_injection_suspected"}],
                }],
            }
        },
    )

    server = payload["servers"][0]
    assert server["status"]["error"] == "not started"
    assert server["status"]["state"] == "circuit_open"
    assert server["status"]["failureCount"] == 5
    assert server["status"]["nextRetryAt"] == 1779022200.0
    assert server["status"]["circuitOpen"] is True
    assert server["status"]["securityWarnings"][0]["code"] == "mcp_prompt_injection_suspected"
    assert server["tools"][0]["securityWarnings"][0]["code"] == "mcp_prompt_injection_suspected"
    assert server["env"] == [{"name": "API_KEY", "configured": True}]
    assert server["includeTools"] == ["read_*"]
    assert server["excludeTools"] == ["write_*"]
    assert "secret" not in str(payload)
