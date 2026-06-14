from __future__ import annotations

from fastapi.testclient import TestClient

from app_config.ai_settings import resolve_brave_search_api_key, resolve_tavily_api_key
from app_config.secrets import parse_env_file
from ui.backend import model_providers_api, settings_api
from ui.backend.model_providers_api import get_model_providers
from ui.backend.server import create_app
from ui.backend.settings_api import delete_ai_api_key, get_ai_settings, update_ai_settings


def _logged_out_codex_status() -> dict[str, object]:
    return {
        "loggedIn": False,
        "authMode": "",
        "planType": "",
        "accountId": "",
        "accountEmail": "",
        "lastRefresh": "",
        "authStorePath": "",
    }


def _logged_in_codex_status() -> dict[str, object]:
    return {
        "loggedIn": True,
        "authMode": "chatgpt",
        "planType": "prolite",
        "accountId": "",
        "accountEmail": "reader@example.test",
        "lastRefresh": "",
        "authStorePath": "",
    }


def _isolate_ai_env(monkeypatch, tmp_path) -> None:
    for name in (
        "PAPER_NOTES_AI_PROVIDER",
        "CODEX_MODEL",
        "DEEPSEEK_API_KEY",
        "DEEPSEEK_MODEL",
        "OPENAI_API_KEY",
        "OPENAI_MODEL",
        "TAVILY_API_KEY",
        "BRAVE_SEARCH_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("PAPER_NOTES_ENV_PATHS", str(tmp_path / "missing.env"))
    monkeypatch.setenv("PAPER_NOTES_SECRETS_PATH", str(tmp_path / "secrets.env"))
    monkeypatch.setattr(settings_api, "get_codex_auth_status", _logged_out_codex_status)
    monkeypatch.setattr(model_providers_api, "get_codex_auth_status", _logged_out_codex_status)


def test_get_ai_settings_returns_redacted_default_status(monkeypatch, tmp_path):
    _isolate_ai_env(monkeypatch, tmp_path)

    payload = get_ai_settings(secrets_path=tmp_path / "secrets.env")

    assert payload["provider"] == "openai"
    assert payload["configured"] is False
    assert payload["ready"] is False
    assert payload["model"] == "gpt-5.5"
    assert payload["modelSource"] == "profile"
    assert payload["modelConnectionConfigured"] is False
    assert "apiKey" not in payload


def test_update_ai_settings_saves_local_model_and_key_without_returning_key(monkeypatch, tmp_path):
    _isolate_ai_env(monkeypatch, tmp_path)
    secrets_path = tmp_path / "secrets.env"

    payload = update_ai_settings(
        {"provider": "openai", "model": "gpt-test", "apiKey": "sk-test-secret"},
        secrets_path=secrets_path,
    )

    assert payload["configured"] is True
    assert payload["ready"] is True
    assert payload["modelConnectionConfigured"] is True
    assert payload["model"] == "gpt-test"
    assert payload["keySource"] == "local"
    assert payload["localKeyConfigured"] is True
    assert "sk-test-secret" not in str(payload)
    values = parse_env_file(secrets_path)
    assert values["PAPER_NOTES_AI_PROVIDER"] == "openai"
    assert values["OPENAI_MODEL"] == "gpt-test"
    assert values["OPENAI_API_KEY"] == "sk-test-secret"


def test_update_ai_settings_can_save_deepseek_key_without_changing_default(monkeypatch, tmp_path):
    _isolate_ai_env(monkeypatch, tmp_path)
    secrets_path = tmp_path / "secrets.env"
    update_ai_settings({"provider": "openai"}, secrets_path=secrets_path)

    payload = update_ai_settings(
        {"provider": "openai", "apiKeyProvider": "deepseek", "apiKey": "deepseek-secret"},
        secrets_path=secrets_path,
    )

    assert payload["provider"] == "openai"
    values = parse_env_file(secrets_path)
    assert values["PAPER_NOTES_AI_PROVIDER"] == "openai"
    assert values["DEEPSEEK_API_KEY"] == "deepseek-secret"
    assert "OPENAI_API_KEY" not in values


def test_web_search_api_keys_resolve_from_local_secrets(monkeypatch, tmp_path):
    _isolate_ai_env(monkeypatch, tmp_path)
    secrets_path = tmp_path / "secrets.env"
    secrets_path.write_text("TAVILY_API_KEY=tavily-secret\nBRAVE_SEARCH_API_KEY=brave-secret\n", encoding="utf-8")

    assert resolve_tavily_api_key(secrets_path=secrets_path).value == "tavily-secret"
    assert resolve_brave_search_api_key(secrets_path=secrets_path).value == "brave-secret"


def test_delete_ai_key_removes_only_requested_local_key(monkeypatch, tmp_path):
    _isolate_ai_env(monkeypatch, tmp_path)
    secrets_path = tmp_path / "secrets.env"
    update_ai_settings(
        {"provider": "deepseek", "model": "deepseek-test", "apiKey": "deepseek-secret"},
        secrets_path=secrets_path,
    )

    payload = delete_ai_api_key("deepseek", secrets_path=secrets_path)

    assert payload["provider"] == "deepseek"
    assert payload["configured"] is False
    assert payload["model"] == "deepseek-test"
    values = parse_env_file(secrets_path)
    assert values["PAPER_NOTES_AI_PROVIDER"] == "deepseek"
    assert values["DEEPSEEK_MODEL"] == "deepseek-test"
    assert "DEEPSEEK_API_KEY" not in values


def test_model_providers_returns_catalog_and_configured_status(monkeypatch, tmp_path):
    _isolate_ai_env(monkeypatch, tmp_path)
    secrets_path = tmp_path / "secrets.env"
    update_ai_settings(
        {"provider": "openai", "model": "gpt-test", "apiKey": "sk-test-secret"},
        secrets_path=secrets_path,
    )

    payload = get_model_providers(secrets_path=secrets_path)

    assert payload["defaultProvider"] == "openai"
    assert payload["defaultModel"] == "gpt-test"
    assert payload["modelConnectionConfigured"] is True
    providers = {provider["name"]: provider for provider in payload["providers"]}
    assert providers["openai"]["configured"] is True
    assert providers["openai"]["model"] == "gpt-test"
    assert providers["openai"]["models"][-1]["value"] == "gpt-test"
    assert providers["codex-oauth"]["configured"] is False
    assert providers["deepseek"]["model"] == "deepseek-v4-flash"


def test_model_providers_includes_codex_auth_status(monkeypatch, tmp_path):
    _isolate_ai_env(monkeypatch, tmp_path)
    monkeypatch.setattr(model_providers_api, "get_codex_auth_status", _logged_in_codex_status)
    secrets_path = tmp_path / "secrets.env"
    update_ai_settings({"provider": "codex-oauth", "model": "gpt-5.5"}, secrets_path=secrets_path)

    payload = get_model_providers(secrets_path=secrets_path)

    assert payload["defaultProvider"] == "codex-oauth"
    assert payload["modelConnectionConfigured"] is True
    assert payload["codexAuth"]["loggedIn"] is True
    assert payload["codexAuth"]["accountEmail"] == "reader@example.test"
    providers = {provider["name"]: provider for provider in payload["providers"]}
    assert providers["codex-oauth"]["configured"] is True


def test_ai_settings_routes_are_registered_and_redact_keys(monkeypatch, tmp_path):
    _isolate_ai_env(monkeypatch, tmp_path)
    client = TestClient(create_app())

    saved = client.post(
        "/api/settings/ai",
        json={"provider": "deepseek", "model": "deepseek-test", "apiKey": "deepseek-secret"},
    )
    catalog = client.get("/api/model/providers")
    deleted = client.delete("/api/settings/ai/key", params={"provider": "deepseek"})

    assert saved.status_code == 200
    assert saved.json()["provider"] == "deepseek"
    assert "deepseek-secret" not in str(saved.json())
    assert catalog.status_code == 200
    assert {provider["name"] for provider in catalog.json()["providers"]} >= {
        "openai",
        "codex-oauth",
        "deepseek",
    }
    assert deleted.status_code == 200
    assert deleted.json()["provider"] == "deepseek"
