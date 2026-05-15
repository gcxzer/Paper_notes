from __future__ import annotations

import json

from app_config.secrets import parse_env_file
from app_config.ai_settings import resolve_ai_settings
from backend.settings_api import (
    delete_ai_api_key,
    get_ai_settings,
    get_codex_auth_status,
    get_tool_settings,
    logout_codex_auth,
    poll_codex_auth,
    start_codex_auth,
    update_ai_settings,
    update_tool_settings,
)
from agent_runtime.service import AgentService
from agent_sessions import AgentSessionStore
from ui.backend.model_providers_api import get_model_providers
from model_providers.codex.auth import CodexAuthStore, CodexDeviceAuthPoll, CodexDeviceAuthStart
from model_providers.codex.types import CodexCredentials
from tools.registry import ToolDefinition, ToolRegistry


def _isolate_ai_env(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("PAPER_NOTES_AI_PROVIDER", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_MODEL", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.delenv("CODEX_MODEL", raising=False)
    monkeypatch.setenv("PAPER_NOTES_ENV_PATHS", str(tmp_path / "missing.env"))
    monkeypatch.setenv("PAPER_NOTES_CODEX_AUTH_PATH", str(tmp_path / "auth" / "codex.json"))


def test_get_ai_settings_returns_redacted_missing_status(monkeypatch, tmp_path):
    _isolate_ai_env(monkeypatch, tmp_path)
    payload = get_ai_settings(secrets_path=tmp_path / "secrets.env")

    assert payload["provider"] == "openai"
    assert payload["configured"] is False
    assert payload["ready"] is False
    assert payload["modelConnectionConfigured"] is False
    assert "apiKey" not in payload
    assert "OPENAI_API_KEY" not in str(payload)


def test_update_ai_settings_saves_local_model_and_key_without_returning_key(monkeypatch, tmp_path):
    _isolate_ai_env(monkeypatch, tmp_path)
    secrets_path = tmp_path / "secrets.env"

    payload = update_ai_settings({"model": "gpt-test", "apiKey": "sk-test-secret"}, secrets_path=secrets_path)

    assert payload["configured"] is True
    assert payload["ready"] is True
    assert payload["modelConnectionConfigured"] is True
    assert payload["model"] == "gpt-test"
    assert payload["keySource"] == "local"
    assert payload["localKeyConfigured"] is True
    assert "sk-test-secret" not in str(payload)
    assert parse_env_file(secrets_path)["OPENAI_API_KEY"] == "sk-test-secret"


def test_delete_ai_api_key_removes_only_local_key(monkeypatch, tmp_path):
    _isolate_ai_env(monkeypatch, tmp_path)
    secrets_path = tmp_path / "secrets.env"
    update_ai_settings({"model": "gpt-test", "apiKey": "sk-test-secret"}, secrets_path=secrets_path)

    payload = delete_ai_api_key(secrets_path=secrets_path)

    assert payload["configured"] is False
    assert payload["model"] == "gpt-test"
    assert payload["modelConnectionConfigured"] is False
    values = parse_env_file(secrets_path)
    assert "OPENAI_API_KEY" not in values
    assert values["OPENAI_MODEL"] == "gpt-test"


def test_update_ai_settings_can_save_gemini_key_without_changing_default_provider(monkeypatch, tmp_path):
    _isolate_ai_env(monkeypatch, tmp_path)
    secrets_path = tmp_path / "secrets.env"
    update_ai_settings({"provider": "openai", "model": "gpt-test"}, secrets_path=secrets_path)

    payload = update_ai_settings(
        {"provider": "openai", "apiKeyProvider": "gemini", "apiKey": "gemini-secret"},
        secrets_path=secrets_path,
    )

    assert payload["provider"] == "openai"
    values = parse_env_file(secrets_path)
    assert values["PAPER_NOTES_AI_PROVIDER"] == "openai"
    assert values["GEMINI_API_KEY"] == "gemini-secret"
    assert "OPENAI_API_KEY" not in values


def test_update_ai_settings_can_save_anthropic_key_without_changing_default_provider(monkeypatch, tmp_path):
    _isolate_ai_env(monkeypatch, tmp_path)
    secrets_path = tmp_path / "secrets.env"
    update_ai_settings({"provider": "openai", "model": "gpt-test"}, secrets_path=secrets_path)

    payload = update_ai_settings(
        {"provider": "openai", "apiKeyProvider": "anthropic", "apiKey": "anthropic-secret"},
        secrets_path=secrets_path,
    )

    assert payload["provider"] == "openai"
    values = parse_env_file(secrets_path)
    assert values["PAPER_NOTES_AI_PROVIDER"] == "openai"
    assert values["ANTHROPIC_API_KEY"] == "anthropic-secret"
    assert "OPENAI_API_KEY" not in values


def test_update_ai_settings_can_save_deepseek_key_without_changing_default_provider(monkeypatch, tmp_path):
    _isolate_ai_env(monkeypatch, tmp_path)
    secrets_path = tmp_path / "secrets.env"
    update_ai_settings({"provider": "openai", "model": "gpt-test"}, secrets_path=secrets_path)

    payload = update_ai_settings(
        {"provider": "openai", "apiKeyProvider": "deepseek", "apiKey": "deepseek-secret"},
        secrets_path=secrets_path,
    )

    assert payload["provider"] == "openai"
    values = parse_env_file(secrets_path)
    assert values["PAPER_NOTES_AI_PROVIDER"] == "openai"
    assert values["DEEPSEEK_API_KEY"] == "deepseek-secret"
    assert "OPENAI_API_KEY" not in values


def test_delete_ai_api_key_removes_gemini_local_keys(monkeypatch, tmp_path):
    _isolate_ai_env(monkeypatch, tmp_path)
    secrets_path = tmp_path / "secrets.env"
    update_ai_settings({"provider": "gemini", "apiKey": "gemini-secret"}, secrets_path=secrets_path)

    payload = delete_ai_api_key("gemini", secrets_path=secrets_path)

    assert payload["provider"] == "gemini"
    values = parse_env_file(secrets_path)
    assert "GEMINI_API_KEY" not in values
    assert "GOOGLE_API_KEY" not in values


def test_delete_ai_api_key_removes_anthropic_local_key(monkeypatch, tmp_path):
    _isolate_ai_env(monkeypatch, tmp_path)
    secrets_path = tmp_path / "secrets.env"
    update_ai_settings({"provider": "anthropic", "apiKey": "anthropic-secret"}, secrets_path=secrets_path)

    payload = delete_ai_api_key("anthropic", secrets_path=secrets_path)

    assert payload["provider"] == "anthropic"
    values = parse_env_file(secrets_path)
    assert "ANTHROPIC_API_KEY" not in values


def test_delete_ai_api_key_removes_deepseek_local_key(monkeypatch, tmp_path):
    _isolate_ai_env(monkeypatch, tmp_path)
    secrets_path = tmp_path / "secrets.env"
    update_ai_settings({"provider": "deepseek", "apiKey": "deepseek-secret"}, secrets_path=secrets_path)

    payload = delete_ai_api_key("deepseek", secrets_path=secrets_path)

    assert payload["provider"] == "deepseek"
    values = parse_env_file(secrets_path)
    assert "DEEPSEEK_API_KEY" not in values


def test_update_ai_settings_saves_codex_provider_and_model(monkeypatch, tmp_path):
    _isolate_ai_env(monkeypatch, tmp_path)
    secrets_path = tmp_path / "secrets.env"

    payload = update_ai_settings({"provider": "codex", "model": "gpt-5.4"}, secrets_path=secrets_path)

    assert payload["provider"] == "codex-oauth"
    assert payload["configured"] is False
    assert payload["ready"] is False
    assert payload["modelConnectionConfigured"] is False
    assert payload["model"] == "gpt-5.4"
    assert payload["modelSource"] == "local"
    assert payload["localProviderConfigured"] is True
    assert payload["codexAuth"]["loggedIn"] is False
    values = parse_env_file(secrets_path)
    assert values["PAPER_NOTES_AI_PROVIDER"] == "codex-oauth"
    assert values["CODEX_MODEL"] == "gpt-5.4"
    assert "OPENAI_API_KEY" not in values


def test_model_connection_configured_accepts_codex_model_and_login(monkeypatch, tmp_path):
    _isolate_ai_env(monkeypatch, tmp_path)
    secrets_path = tmp_path / "secrets.env"
    auth_path = tmp_path / "auth" / "codex.json"
    update_ai_settings({"provider": "codex", "model": "gpt-5.4"}, secrets_path=secrets_path)
    CodexAuthStore(auth_path).write_credentials(
        CodexCredentials(
            access_token="access-secret",
            refresh_token="refresh-secret",
            account_email="user@example.test",
        )
    )

    payload = get_ai_settings(secrets_path=secrets_path)

    assert payload["provider"] == "codex-oauth"
    assert payload["configured"] is True
    assert payload["ready"] is True
    assert payload["modelConnectionConfigured"] is True


def test_codex_login_without_saved_model_counts_as_configured_and_auto_default(monkeypatch, tmp_path):
    _isolate_ai_env(monkeypatch, tmp_path)
    secrets_path = tmp_path / "secrets.env"
    auth_path = tmp_path / "auth" / "codex.json"
    CodexAuthStore(auth_path).write_credentials(
        CodexCredentials(
            access_token="access-secret",
            refresh_token="refresh-secret",
            account_email="user@example.test",
        )
    )

    payload = get_ai_settings(secrets_path=secrets_path)
    catalog = get_model_providers(secrets_path=secrets_path, codex_auth_path=auth_path)

    assert payload["provider"] == "codex-oauth"
    assert payload["providerSource"] == "auto"
    assert payload["configured"] is True
    assert payload["ready"] is True
    assert payload["model"] == "gpt-5.5"
    assert payload["modelConfigured"] is True
    assert payload["modelSource"] == "profile"
    assert payload["modelConnectionConfigured"] is True
    assert catalog["defaultProvider"] == "codex-oauth"
    assert catalog["modelConnectionConfigured"] is True


def test_explicit_provider_is_not_auto_replaced_by_another_key(monkeypatch, tmp_path):
    _isolate_ai_env(monkeypatch, tmp_path)
    secrets_path = tmp_path / "secrets.env"
    update_ai_settings({"provider": "codex", "apiKey": "sk-test-secret"}, secrets_path=secrets_path)

    payload = get_ai_settings(secrets_path=secrets_path)

    assert payload["provider"] == "codex-oauth"
    assert payload["providerSource"] == "local"
    assert payload["configured"] is False
    assert payload["modelConnectionConfigured"] is False


def test_update_ai_settings_saves_gemini_provider_model_and_key(monkeypatch, tmp_path):
    _isolate_ai_env(monkeypatch, tmp_path)
    secrets_path = tmp_path / "secrets.env"

    payload = update_ai_settings(
        {"provider": "google", "model": "gemini-test", "apiKey": "gemini-secret"},
        secrets_path=secrets_path,
    )

    assert payload["provider"] == "gemini"
    assert payload["configured"] is True
    assert payload["ready"] is True
    assert payload["model"] == "gemini-test"
    assert payload["localKeyConfigured"] is True
    assert payload["modelConnectionConfigured"] is True
    values = parse_env_file(secrets_path)
    assert values["PAPER_NOTES_AI_PROVIDER"] == "gemini"
    assert values["GEMINI_MODEL"] == "gemini-test"
    assert values["GEMINI_API_KEY"] == "gemini-secret"
    assert "OPENAI_API_KEY" not in values


def test_update_ai_settings_saves_anthropic_provider_model_and_key(monkeypatch, tmp_path):
    _isolate_ai_env(monkeypatch, tmp_path)
    secrets_path = tmp_path / "secrets.env"

    payload = update_ai_settings(
        {"provider": "claude", "model": "claude-test", "apiKey": "anthropic-secret"},
        secrets_path=secrets_path,
    )

    assert payload["provider"] == "anthropic"
    assert payload["configured"] is True
    assert payload["ready"] is True
    assert payload["model"] == "claude-test"
    assert payload["localKeyConfigured"] is True
    assert payload["modelConnectionConfigured"] is True
    values = parse_env_file(secrets_path)
    assert values["PAPER_NOTES_AI_PROVIDER"] == "anthropic"
    assert values["ANTHROPIC_MODEL"] == "claude-test"
    assert values["ANTHROPIC_API_KEY"] == "anthropic-secret"
    assert "OPENAI_API_KEY" not in values


def test_update_ai_settings_saves_deepseek_provider_model_and_key(monkeypatch, tmp_path):
    _isolate_ai_env(monkeypatch, tmp_path)
    secrets_path = tmp_path / "secrets.env"

    payload = update_ai_settings(
        {"provider": "deepseek", "model": "deepseek-test", "apiKey": "deepseek-secret"},
        secrets_path=secrets_path,
    )

    assert payload["provider"] == "deepseek"
    assert payload["configured"] is True
    assert payload["ready"] is True
    assert payload["model"] == "deepseek-test"
    assert payload["localKeyConfigured"] is True
    assert payload["modelConnectionConfigured"] is True
    values = parse_env_file(secrets_path)
    assert values["PAPER_NOTES_AI_PROVIDER"] == "deepseek"
    assert values["DEEPSEEK_MODEL"] == "deepseek-test"
    assert values["DEEPSEEK_API_KEY"] == "deepseek-secret"
    assert "OPENAI_API_KEY" not in values


def test_get_model_providers_returns_catalog_and_configured_status(monkeypatch, tmp_path):
    _isolate_ai_env(monkeypatch, tmp_path)
    secrets_path = tmp_path / "secrets.env"
    update_ai_settings({"provider": "openai", "model": "gpt-test", "apiKey": "sk-test-secret"}, secrets_path=secrets_path)

    payload = get_model_providers(secrets_path=secrets_path, codex_auth_path=tmp_path / "auth" / "codex.json")

    assert payload["defaultProvider"] == "openai"
    providers = {provider["name"]: provider for provider in payload["providers"]}
    assert providers["openai"]["configured"] is True
    assert providers["openai"]["model"] == "gpt-test"
    assert providers["openai"]["models"][-1]["value"] == "gpt-test"
    assert providers["codex-oauth"]["configured"] is False
    assert providers["codex-oauth"]["model"] == "gpt-5.5"
    assert providers["anthropic"]["configured"] is False
    assert providers["anthropic"]["model"] == "claude-sonnet-4-6"
    assert providers["deepseek"]["configured"] is False
    assert providers["deepseek"]["model"] == "deepseek-v4-flash"
    assert providers["gemini"]["configured"] is False
    assert providers["gemini"]["model"] == "gemini-3-flash-preview"


def test_tool_settings_default_to_ask_and_list_registered_tools(tmp_path):
    service = _tool_settings_service(tmp_path)

    payload = get_tool_settings(settings_path=tmp_path / "tool-settings.json", service=service)
    tools = {tool["name"]: tool for tool in payload["tools"]}

    assert payload["globalAccess"] == "full_access"
    assert payload["defaultWriteMode"] == "auto"
    assert payload["disabledTools"] == []
    assert payload["disabledToolsets"] == []
    assert payload["enabledToolsets"] == ["web_search"]
    assert payload["nativeWebSearchEnabled"] is True
    assert set(tools) == {
        "paper_notes",
        "persistent_memory",
        "session_search",
        "todo",
        "skills",
        "code_execution",
        "web_search",
    }
    assert [tool["name"] for tool in payload["builtInTools"]] == [
        "paper_notes",
        "native_web_search",
        "code_execution",
        "persistent_memory",
        "session_search",
        "todo",
        "skills",
    ]
    assert all(tool["enabled"] is True for tool in payload["builtInTools"])
    assert [tool["name"] for tool in payload["customTools"]] == ["web_search"]
    assert payload["customTools"][0]["enabled"] is True
    assert tools["code_execution"]["enabled"] is True
    assert tools["code_execution"]["label"] == "Code Execution"
    assert tools["code_execution"]["mutating"] is True
    assert tools["code_execution"]["effectiveAccess"] == "auto"
    assert tools["paper_notes"]["mutating"] is True
    assert tools["paper_notes"]["childCount"] == 2
    assert tools["session_search"]["readOnly"] is True


def test_update_tool_settings_persists_group_access_and_expands_runtime_overrides(tmp_path):
    service = _tool_settings_service(tmp_path)
    settings_path = tmp_path / "tool-settings.json"

    payload = update_tool_settings({
        "globalAccess": "full_access",
        "tools": [
            {"name": "session_search", "enabled": False, "access": "inherit"},
            {"name": "native_web_search", "enabled": True, "access": "inherit"},
            {"name": "web_search", "enabled": True, "access": "inherit"},
            {"name": "paper_notes", "enabled": True, "access": "ask"},
        ],
    }, settings_path=settings_path, service=service)
    reloaded = get_tool_settings(settings_path=settings_path, service=service)
    saved = json.loads(settings_path.read_text(encoding="utf-8"))

    assert payload["globalAccess"] == "full_access"
    assert payload["defaultWriteMode"] == "auto"
    assert payload["disabledToolsets"] == ["session_search"]
    assert payload["disabledTools"] == ["session_search", "web_search"]
    assert payload["nativeWebSearchEnabled"] is True
    assert payload["customTools"][0]["name"] == "web_search"
    assert payload["customTools"][0]["enabled"] is True
    assert payload["enabledToolsets"] == ["web_search"]
    assert payload["toolWriteModes"] == {"write_note_section": "ask"}
    assert reloaded["disabledTools"] == ["session_search", "web_search"]
    assert reloaded["toolWriteModes"] == {"write_note_section": "ask"}
    assert "native_web_search" not in str(saved)
    assert set(saved["toolsets"]) == {
        "paper_notes",
        "code_execution",
        "persistent_memory",
        "session_search",
        "todo",
        "skills",
        "web_search",
    }
    assert saved["toolsets"]["paper_notes"] == {"enabled": True, "access": "ask"}
    assert saved["toolsets"]["session_search"] == {"enabled": False, "access": "inherit"}
    assert saved["toolsets"]["web_search"] == {
        "enabled": True,
        "access": "inherit",
        "native_provider": {
            "openaiCodex": {"enabled": True},
            "openaiAPIKey": {"enabled": True},
            "anthropic": {"enabled": True},
            "gemini": {"enabled": True},
        },
        "custom_provider": {
            "Tavily": {"enabled": False},
            "Brave": {"enabled": False},
        },
    }
    assert "tools" not in saved


def test_tool_settings_migrates_legacy_flat_tools_shape(tmp_path):
    service = _tool_settings_service(tmp_path)
    settings_path = tmp_path / "tool-settings.json"
    settings_path.write_text(json.dumps({
        "globalAccess": "full_access",
        "tools": {
            "provider_native_web_search": {"enabled": True, "access": "inherit"},
            "paper_notes": {"enabled": True, "access": "ask"},
            "session_search": {"enabled": False, "access": "inherit"},
            "web_search": {"enabled": False, "access": "inherit"},
        },
    }), encoding="utf-8")

    payload = get_tool_settings(settings_path=settings_path, service=service)

    assert payload["globalAccess"] == "full_access"
    assert payload["nativeWebSearchEnabled"] is True
    assert payload["disabledToolsets"] == ["session_search"]
    assert payload["enabledToolsets"] == ["web_search"]
    assert payload["disabledTools"] == ["session_search", "web_search"]
    assert payload["toolWriteModes"] == {"write_note_section": "ask"}


def test_tool_settings_uses_custom_tavily_when_native_disabled(monkeypatch, tmp_path):
    _isolate_ai_env(monkeypatch, tmp_path)
    service = _tool_settings_service(tmp_path)
    settings_path = tmp_path / "tool-settings.json"
    settings_path.write_text(json.dumps({
        "globalAccess": "full_access",
        "toolsets": {
            "web_search": {
                "enabled": True,
                "access": "inherit",
                "native_provider": {
                    "openaiCodex": {"enabled": False},
                    "openaiAPIKey": {"enabled": False},
                },
                "custom_provider": {
                    "Tavily": {"enabled": True},
                    "Brave": {"enabled": False},
                },
            },
        },
    }), encoding="utf-8")

    payload = get_tool_settings(settings_path=settings_path, service=service)

    assert payload["nativeWebSearchEnabled"] is False
    assert payload["enabledToolsets"] == ["web_search"]
    assert payload["disabledTools"] == []
    assert payload["customTools"][0]["enabled"] is True


def test_tool_settings_prefers_matching_native_provider_over_tavily(monkeypatch, tmp_path):
    _isolate_ai_env(monkeypatch, tmp_path)
    monkeypatch.setenv("PAPER_NOTES_AI_PROVIDER", "openai")
    service = _tool_settings_service(tmp_path)
    settings_path = tmp_path / "tool-settings.json"
    settings_path.write_text(json.dumps({
        "globalAccess": "full_access",
        "toolsets": {
            "web_search": {
                "enabled": True,
                "access": "inherit",
                "native_provider": {
                    "openaiCodex": {"enabled": False},
                    "openaiAPIKey": {"enabled": True},
                },
                "custom_provider": {
                    "Tavily": {"enabled": True},
                    "Brave": {"enabled": False},
                },
            },
        },
    }), encoding="utf-8")

    payload = get_tool_settings(settings_path=settings_path, service=service)

    assert payload["nativeWebSearchEnabled"] is True
    assert payload["enabledToolsets"] == ["web_search"]
    assert payload["disabledTools"] == []
    assert payload["customTools"][0]["enabled"] is True
    assert set(payload["customTools"][0]["metadata"]["toolNames"]) == {"web_fetch", "web_search"}


def test_update_tool_settings_saves_web_search_provider_and_tavily_key(monkeypatch, tmp_path):
    _isolate_ai_env(monkeypatch, tmp_path)
    monkeypatch.setenv("PAPER_NOTES_SECRETS_PATH", str(tmp_path / "secrets.env"))
    service = _tool_settings_service(tmp_path)
    settings_path = tmp_path / "tool-settings.json"

    payload = update_tool_settings({
        "globalAccess": "full_access",
        "tools": [
            {"name": "web_search", "enabled": True, "access": "inherit"},
            {"name": "native_web_search", "enabled": False, "access": "inherit"},
        ],
        "webSearchProviders": {
            "custom_provider": {
                "Tavily": {"enabled": True},
                "Brave": {"enabled": False},
            },
            "tavilyApiKey": "tvly-test-secret",
        },
    }, settings_path=settings_path, service=service)
    saved = json.loads(settings_path.read_text(encoding="utf-8"))
    secrets = parse_env_file(tmp_path / "secrets.env")

    assert payload["webSearchProviders"]["mode"] == "tavily"
    assert payload["webSearchProviders"]["tavilyKeyConfigured"] is True
    assert "tvly-test-secret" not in str(payload)
    assert secrets["TAVILY_API_KEY"] == "tvly-test-secret"
    assert saved["toolsets"]["web_search"] == {
        "enabled": True,
        "access": "inherit",
        "native_provider": {
            "openaiCodex": {"enabled": False},
            "openaiAPIKey": {"enabled": False},
            "anthropic": {"enabled": False},
            "gemini": {"enabled": False},
        },
        "custom_provider": {
            "Tavily": {"enabled": True},
            "Brave": {"enabled": False},
        },
    }


def test_update_tool_settings_saves_brave_search_provider_and_key(monkeypatch, tmp_path):
    _isolate_ai_env(monkeypatch, tmp_path)
    monkeypatch.setenv("PAPER_NOTES_SECRETS_PATH", str(tmp_path / "secrets.env"))
    service = _tool_settings_service(tmp_path)
    settings_path = tmp_path / "tool-settings.json"

    payload = update_tool_settings({
        "globalAccess": "full_access",
        "tools": [
            {"name": "web_search", "enabled": True, "access": "inherit"},
            {"name": "native_web_search", "enabled": False, "access": "inherit"},
        ],
        "webSearchProviders": {
            "custom_provider": {
                "Tavily": {"enabled": False},
                "Brave": {"enabled": True},
            },
            "customProviderName": "Brave",
            "braveSearchApiKey": "brave-test-secret",
        },
    }, settings_path=settings_path, service=service)
    saved = json.loads(settings_path.read_text(encoding="utf-8"))
    secrets = parse_env_file(tmp_path / "secrets.env")

    assert payload["webSearchProviders"]["customProviderName"] == "Brave"
    assert payload["webSearchProviders"]["braveSearchKeyConfigured"] is True
    assert "brave-test-secret" not in str(payload)
    assert secrets["BRAVE_SEARCH_API_KEY"] == "brave-test-secret"
    assert saved["toolsets"]["web_search"]["custom_provider"] == {
        "Tavily": {"enabled": False},
        "Brave": {"enabled": True},
    }


def test_tool_settings_uses_codex_native_provider_when_active(monkeypatch, tmp_path):
    _isolate_ai_env(monkeypatch, tmp_path)
    monkeypatch.setenv("PAPER_NOTES_AI_PROVIDER", "codex-oauth")
    service = _tool_settings_service(tmp_path)
    settings_path = tmp_path / "tool-settings.json"
    settings_path.write_text(json.dumps({
        "globalAccess": "full_access",
        "toolsets": {
            "web_search": {
                "enabled": True,
                "access": "inherit",
                "native_provider": {
                    "openaiCodex": {"enabled": True},
                    "openaiAPIKey": {"enabled": False},
                },
                "custom_provider": {
                    "Tavily": {"enabled": True},
                    "Brave": {"enabled": False},
                },
            },
        },
    }), encoding="utf-8")

    payload = get_tool_settings(settings_path=settings_path, service=service)

    assert payload["nativeWebSearchEnabled"] is True
    assert payload["enabledToolsets"] == ["web_search"]
    assert payload["disabledTools"] == []


def test_tool_settings_uses_gemini_native_provider_when_active(monkeypatch, tmp_path):
    _isolate_ai_env(monkeypatch, tmp_path)
    monkeypatch.setenv("PAPER_NOTES_AI_PROVIDER", "gemini")
    service = _tool_settings_service(tmp_path)
    settings_path = tmp_path / "tool-settings.json"
    settings_path.write_text(json.dumps({
        "globalAccess": "full_access",
        "toolsets": {
            "web_search": {
                "enabled": True,
                "access": "inherit",
                "native_provider": {
                    "gemini": {"enabled": True},
                    "openaiCodex": {"enabled": False},
                    "openaiAPIKey": {"enabled": False},
                },
                "custom_provider": {
                    "Tavily": {"enabled": False},
                    "Brave": {"enabled": False},
                },
            },
        },
    }), encoding="utf-8")

    payload = get_tool_settings(settings_path=settings_path, service=service)

    assert payload["nativeWebSearchEnabled"] is True
    assert payload["enabledToolsets"] == ["web_search"]


def test_tool_settings_blocks_deepseek_native_provider_when_active(monkeypatch, tmp_path):
    _isolate_ai_env(monkeypatch, tmp_path)
    monkeypatch.setenv("PAPER_NOTES_AI_PROVIDER", "deepseek")
    service = _tool_settings_service(tmp_path)
    settings_path = tmp_path / "tool-settings.json"
    settings_path.write_text(json.dumps({
        "globalAccess": "full_access",
        "toolsets": {
            "web_search": {
                "enabled": True,
                "access": "inherit",
                "native_provider": {
                    "openaiCodex": {"enabled": True},
                    "openaiAPIKey": {"enabled": True},
                    "anthropic": {"enabled": True},
                    "gemini": {"enabled": True},
                },
                "custom_provider": {
                    "Tavily": {"enabled": False},
                    "Brave": {"enabled": False},
                },
            },
        },
    }), encoding="utf-8")

    payload = get_tool_settings(settings_path=settings_path, service=service)

    assert payload["nativeWebSearchEnabled"] is False
    assert payload["enabledToolsets"] == ["web_search"]
    assert payload["disabledTools"] == ["web_search"]


def test_environment_key_wins_over_local_key(monkeypatch, tmp_path):
    _isolate_ai_env(monkeypatch, tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env-secret")
    secrets_path = tmp_path / "secrets.env"
    update_ai_settings({"model": "gpt-test", "apiKey": "sk-local-secret"}, secrets_path=secrets_path)

    settings = resolve_ai_settings(secrets_path=secrets_path)

    assert settings.api_key == "sk-env-secret"
    assert settings.key_source == "environment"
    assert settings.local_key_configured is True


def _tool_settings_service(tmp_path):
    registry = ToolRegistry()
    registry.register(ToolDefinition(
        name="search_library",
        description="Search local notes.",
        parameters={"type": "object", "properties": {}},
        handler=lambda args: {"success": True},
        toolset="paper_notes",
        read_only=True,
    ))
    registry.register(ToolDefinition(
        name="write_note_section",
        description="Write note HTML.",
        parameters={"type": "object", "properties": {}},
        handler=lambda args: {"success": True},
        toolset="paper_notes",
        mutating=True,
        risk="write",
    ))
    registry.register(ToolDefinition(
        name="persistent_memory",
        description="Manage persistent memory.",
        parameters={"type": "object", "properties": {}},
        handler=lambda args: {"success": True},
        toolset="persistent_memory",
        mutating=True,
        risk="write",
    ))
    registry.register(ToolDefinition(
        name="session_search",
        description="Search sessions.",
        parameters={"type": "object", "properties": {}},
        handler=lambda args: {"success": True},
        toolset="session_search",
        read_only=True,
    ))
    registry.register(ToolDefinition(
        name="todo",
        description="Manage session todos.",
        parameters={"type": "object", "properties": {}},
        handler=lambda args: {"success": True},
        toolset="todo",
        mutating=True,
        risk="write",
    ))
    registry.register(ToolDefinition(
        name="skills_list",
        description="List skills.",
        parameters={"type": "object", "properties": {}},
        handler=lambda args: {"success": True},
        toolset="skills",
        read_only=True,
    ))
    registry.register(ToolDefinition(
        name="skill_view",
        description="View skill.",
        parameters={"type": "object", "properties": {}},
        handler=lambda args: {"success": True},
        toolset="skills",
        read_only=True,
    ))
    registry.register(ToolDefinition(
        name="execute_code",
        description="Run Python.",
        parameters={"type": "object", "properties": {"code": {"type": "string"}}},
        handler=lambda args: {"success": True},
        toolset="code_execution",
        mutating=True,
        risk="write",
        kind="external",
    ))
    registry.register(ToolDefinition(
        name="web_search",
        description="Search the web.",
        parameters={"type": "object", "properties": {}},
        handler=lambda args: {"success": True},
        toolset="web_search",
        read_only=True,
        kind="search",
    ))
    registry.register(ToolDefinition(
        name="web_fetch",
        description="Fetch a URL.",
        parameters={"type": "object", "properties": {}},
        handler=lambda args: {"success": True},
        toolset="web_search",
        read_only=True,
        kind="read",
    ))
    return AgentService(
        session_store=AgentSessionStore(tmp_path / ".paper-notes" / "sessions"),
        tool_registry=registry,
        use_memory=False,
        use_session_search=False,
        use_compression=False,
        tool_approval_manager=None,
        tool_result_store=None,
    )


def test_codex_auth_status_redacts_tokens_and_logout(monkeypatch, tmp_path):
    _isolate_ai_env(monkeypatch, tmp_path)
    auth_path = tmp_path / "auth" / "codex.json"
    store = CodexAuthStore(auth_path)
    store.write_credentials(
        CodexCredentials(
            access_token="access-secret",
            refresh_token="refresh-secret",
            account_id="acct_123",
            account_email="user@example.test",
            plan_type="plus",
            last_refresh="2026-05-10T12:00:00Z",
        )
    )

    payload = get_codex_auth_status(auth_path=auth_path)

    assert payload["loggedIn"] is True
    assert payload["authMode"] == "chatgpt"
    assert payload["accountEmail"] == "user@example.test"
    assert payload["planType"] == "plus"
    assert "access-secret" not in str(payload)
    assert "refresh-secret" not in str(payload)

    logged_out = logout_codex_auth(auth_path=auth_path)

    assert logged_out["loggedIn"] is False
    assert not auth_path.exists()


class FakeCodexStartClient:
    def start(self) -> CodexDeviceAuthStart:
        return CodexDeviceAuthStart(
            user_code="ABCD-EFGH",
            device_auth_id="device_123",
            verification_uri="https://auth.openai.com/codex/device",
            interval=3,
        )


class FakeCodexPendingClient:
    def poll(self, *, device_auth_id: str, user_code: str) -> CodexDeviceAuthPoll:
        assert device_auth_id == "device_123"
        assert user_code == "ABCD-EFGH"
        return CodexDeviceAuthPoll(status="pending")


class FakeCodexCompleteClient:
    def poll(self, *, device_auth_id: str, user_code: str) -> CodexDeviceAuthPoll:
        assert device_auth_id == "device_123"
        assert user_code == "ABCD-EFGH"
        return CodexDeviceAuthPoll(
            status="connected",
            credentials=CodexCredentials(
                access_token="access-secret",
                refresh_token="refresh-secret",
                account_email="user@example.test",
                source="device-code",
            ),
        )


def test_start_codex_auth_returns_device_flow_payload(monkeypatch, tmp_path):
    _isolate_ai_env(monkeypatch, tmp_path)

    payload = start_codex_auth(client=FakeCodexStartClient())

    assert payload == {
        "status": "started",
        "userCode": "ABCD-EFGH",
        "deviceAuthId": "device_123",
        "verificationUri": "https://auth.openai.com/codex/device",
        "interval": 3,
    }


def test_poll_codex_auth_handles_pending(monkeypatch, tmp_path):
    _isolate_ai_env(monkeypatch, tmp_path)

    payload = poll_codex_auth(
        {"deviceAuthId": "device_123", "userCode": "ABCD-EFGH"},
        auth_path=tmp_path / "auth" / "codex.json",
        client=FakeCodexPendingClient(),
    )

    assert payload == {"status": "pending"}


def test_poll_codex_auth_saves_tokens_without_returning_them(monkeypatch, tmp_path):
    _isolate_ai_env(monkeypatch, tmp_path)
    auth_path = tmp_path / "auth" / "codex.json"

    payload = poll_codex_auth(
        {"deviceAuthId": "device_123", "userCode": "ABCD-EFGH"},
        auth_path=auth_path,
        client=FakeCodexCompleteClient(),
    )

    assert payload["status"] == "connected"
    assert payload["auth"]["loggedIn"] is True
    assert payload["auth"]["accountEmail"] == "user@example.test"
    assert "access-secret" not in str(payload)
    assert "refresh-secret" not in str(payload)
    values = CodexAuthStore(auth_path).read_credentials()
    assert values.access_token == "access-secret"
