from __future__ import annotations

import json
import stat

import pytest

from app_config.secrets import parse_env_file
from tools.mcp.settings import mcp_runtime_config, mcp_secrets_path, public_mcp_settings, read_mcp_settings
from ui.backend import mcp_api


def test_mcp_settings_api_saves_reads_and_redacts_secrets(tmp_path, monkeypatch):
    settings_path = tmp_path / ".paper-notes" / "mcp-servers.json"
    resets = []
    monkeypatch.setattr(mcp_api, "reset_agent_service", lambda: resets.append(True))

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
            "bearer_token_env_var": "MCP_BEARER_TOKEN",
            "header_env_vars": [{"name": "X-API-Key", "value": "MCP_API_KEY"}],
            "includeTools": "read_*\nlist_resources,search",
            "excludeTools": ["write_*", "delete_file", "write_*"],
            "timeoutSeconds": 5,
            "connectTimeoutSeconds": 3,
        }]
    }, settings_path=settings_path)

    stored = read_mcp_settings(settings_path)
    server = stored["servers"][0]
    raw_settings = json.loads(settings_path.read_text(encoding="utf-8"))
    raw_server = raw_settings["servers"][0]
    secrets = parse_env_file(mcp_secrets_path(settings_path))

    assert resets == [True]
    assert server["env"] == {"API_KEY": "super-secret"}
    assert server["headers"] == {"Authorization": "Bearer super-secret"}
    assert server["bearerTokenEnvVar"] == "MCP_BEARER_TOKEN"
    assert server["headerEnvVars"] == {"X-API-Key": "MCP_API_KEY"}
    assert raw_server["env"]["API_KEY"].startswith("paper-notes-secret:")
    assert raw_server["headers"]["Authorization"].startswith("paper-notes-secret:")
    assert "super-secret" not in settings_path.read_text(encoding="utf-8")
    assert "super-secret" in "\n".join(secrets.values())
    assert server["includeTools"] == ["read_*", "list_resources", "search"]
    assert server["excludeTools"] == ["write_*", "delete_file"]
    assert stat.S_IMODE(settings_path.stat().st_mode) == 0o600
    assert payload["servers"][0]["env"] == [{"name": "API_KEY", "configured": True}]
    assert payload["servers"][0]["headers"] == [{"name": "Authorization", "configured": True}]
    assert payload["servers"][0]["bearerTokenEnvVar"] == "MCP_BEARER_TOKEN"
    assert payload["servers"][0]["headerEnvVars"] == [{"name": "X-API-Key", "value": "MCP_API_KEY"}]
    assert payload["servers"][0]["includeTools"] == ["read_*", "list_resources", "search"]
    assert payload["servers"][0]["excludeTools"] == ["write_*", "delete_file"]
    assert "super-secret" not in str(payload)


def test_mcp_settings_update_preserves_redacted_existing_secret(tmp_path, monkeypatch):
    settings_path = tmp_path / "mcp-servers.json"
    monkeypatch.setattr(mcp_api, "reset_agent_service", lambda: None)
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
        "bearerTokenEnvVar": "MCP_BEARER_TOKEN",
        "headerEnvVars": [{"name": "X-API-Key", "value": "MCP_API_KEY"}],
        "include_tools": ["search", "list_*"],
        "exclude_tools": "delete_*, write_file",
    })

    assert result["success"] is True
    assert calls[0]["transport"] == "http"
    assert calls[0]["headers"] == {"Authorization": "Bearer token"}
    assert calls[0]["bearerTokenEnvVar"] == "MCP_BEARER_TOKEN"
    assert calls[0]["headerEnvVars"] == {"X-API-Key": "MCP_API_KEY"}
    assert calls[0]["includeTools"] == ["search", "list_*"]
    assert calls[0]["excludeTools"] == ["delete_*", "write_file"]
    assert not (tmp_path / "mcp-servers.json").exists()


def test_mcp_connect_endpoint_saves_and_registers(tmp_path):
    settings_path = tmp_path / ".paper-notes" / "mcp-servers.json"
    registered = []

    class FakeManager:
        def register_servers(self, servers):
            registered.append(servers)
            return ["mcp_arxiv_search"]

        def statuses(self):
            return {
                "arxiv": {
                    "connected": True,
                    "error": "",
                    "state": "connected",
                    "toolCount": 1,
                    "tools": [{"name": "arxiv_search", "generatedName": "mcp_arxiv_arxiv_search"}],
                }
            }

    class FakeService:
        mcp_manager = FakeManager()

    payload = mcp_api.connect_mcp_server({
        "serverId": "arxiv",
        "servers": [{
            "id": "arxiv",
            "name": "arxiv",
            "enabled": True,
            "transport": "http",
            "url": "https://arxiv.caseyjhand.com/mcp",
            "timeoutSeconds": 120,
            "connectTimeoutSeconds": 10,
        }],
    }, settings_path=settings_path, service=FakeService())

    stored = read_mcp_settings(settings_path)["servers"][0]
    assert stored["id"] == "arxiv"
    assert stored["url"] == "https://arxiv.caseyjhand.com/mcp"
    assert registered[0][0]["id"] == "arxiv"
    assert payload["serverId"] == "arxiv"
    assert payload["servers"][0]["status"]["connected"] is True
    assert payload["servers"][0]["status"]["toolCount"] == 1
    assert payload["servers"][0]["tools"][0]["generatedName"] == "mcp_arxiv_arxiv_search"


def test_mcp_connect_endpoint_can_register_without_persisting(tmp_path):
    settings_path = tmp_path / ".paper-notes" / "mcp-servers.json"
    registered = []

    class FakeManager:
        def register_servers(self, servers):
            registered.append(servers)
            return ["mcp_arxiv_search"]

        def statuses(self):
            return {
                "arxiv": {
                    "connected": True,
                    "error": "",
                    "state": "connected",
                    "toolCount": 1,
                    "tools": [{"name": "arxiv_search", "generatedName": "mcp_arxiv_arxiv_search"}],
                }
            }

    class FakeService:
        mcp_manager = FakeManager()

    payload = mcp_api.connect_mcp_server({
        "serverId": "arxiv",
        "persist": False,
        "servers": [{
            "id": "arxiv",
            "name": "arxiv",
            "enabled": True,
            "transport": "http",
            "url": "https://arxiv.caseyjhand.com/mcp",
            "timeoutSeconds": 120,
            "connectTimeoutSeconds": 10,
        }],
    }, settings_path=settings_path, service=FakeService())

    assert not settings_path.exists()
    assert registered[0][0]["id"] == "arxiv"
    assert payload["serverId"] == "arxiv"
    assert payload["servers"][0]["status"]["connected"] is True


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
                "bearerTokenEnvVar": "MCP_BEARER_TOKEN",
                "headerEnvVars": {"X-API-Key": "MCP_API_KEY"},
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
    assert server["bearerTokenEnvVar"] == "MCP_BEARER_TOKEN"
    assert server["headerEnvVars"] == [{"name": "X-API-Key", "value": "MCP_API_KEY"}]
    assert server["includeTools"] == ["read_*"]
    assert server["excludeTools"] == ["write_*"]
    assert "secret" not in str(payload)


def test_mcp_runtime_config_resolves_http_headers_from_environment_files(tmp_path, monkeypatch):
    secrets_path = tmp_path / "secrets.env"
    secrets_path.write_text("MCP_BEARER_TOKEN=from-bearer\nMCP_API_KEY=from-header\n", encoding="utf-8")
    monkeypatch.setenv("PAPER_NOTES_SECRETS_PATH", str(secrets_path))
    monkeypatch.delenv("MCP_BEARER_TOKEN", raising=False)
    monkeypatch.delenv("MCP_API_KEY", raising=False)

    runtime = mcp_runtime_config({
        "transport": "http",
        "url": "https://mcp.example/mcp",
        "headers": {"X-Static": "static-value", "Authorization": "Bearer old"},
        "bearerTokenEnvVar": "MCP_BEARER_TOKEN",
        "headerEnvVars": {"X-API-Key": "MCP_API_KEY"},
    })

    assert runtime["headers"] == {
        "X-Static": "static-value",
        "X-API-Key": "from-header",
        "Authorization": "Bearer from-bearer",
    }


def test_mcp_runtime_config_missing_header_env_var_is_clear_error(tmp_path, monkeypatch):
    env_name = "PAPER_NOTES_TEST_MISSING_MCP_TOKEN"
    monkeypatch.setenv("PAPER_NOTES_SECRETS_PATH", str(tmp_path / "missing-secrets.env"))
    monkeypatch.delenv(env_name, raising=False)
    with pytest.raises(ValueError, match=env_name):
        mcp_runtime_config({
            "transport": "http",
            "url": "https://mcp.example/mcp",
            "bearerTokenEnvVar": env_name,
        })


def test_mcp_ops_endpoints_delegate_to_manager(monkeypatch):
    calls = []

    class FakeManager:
        def reset_server_circuit(self, server_id):
            calls.append(("reset", server_id))
            return {"success": True, "serverId": server_id, "status": {"circuitOpen": False}}

    class FakeService:
        mcp_manager = FakeManager()

    monkeypatch.setattr(mcp_api, "read_mcp_stderr_log", lambda max_chars=60000: {
        "success": True,
        "log": "stderr tail",
        "truncated": False,
        "max": max_chars,
    })

    assert mcp_api.reset_mcp_server_circuit({"serverId": "filesystem"}, service=FakeService())["status"]["circuitOpen"] is False
    assert mcp_api.get_mcp_stderr_log(max_chars=1234)["log"] == "stderr tail"
    assert calls == [("reset", "filesystem")]
