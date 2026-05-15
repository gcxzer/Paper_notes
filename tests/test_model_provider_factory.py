from __future__ import annotations

from types import SimpleNamespace

import pytest

from model_providers import (
    AnthropicModelProvider,
    CodexModelProvider,
    DeepSeekModelProvider,
    GeminiModelProvider,
    get_provider_profile,
    list_provider_profiles,
    ModelProviderConfigError,
    ModelProviderProfile,
    OpenAIModelProvider,
    create_model_provider,
    normalize_model_provider_name,
    register_provider_profile,
    resolve_model_provider,
)


def test_model_provider_factory_routes_openai() -> None:
    provider = create_model_provider("openai", client=object(), default_model="gpt-test")

    assert isinstance(provider, OpenAIModelProvider)


def test_model_provider_factory_routes_codex_aliases() -> None:
    assert isinstance(create_model_provider("codex", client=object()), CodexModelProvider)
    assert isinstance(create_model_provider("codex-oauth", client=object()), CodexModelProvider)
    assert isinstance(create_model_provider("openai-codex", client=object()), CodexModelProvider)


def test_model_provider_factory_routes_gemini_aliases() -> None:
    assert isinstance(create_model_provider("gemini", api_key="test-key"), GeminiModelProvider)
    assert isinstance(create_model_provider("google", api_key="test-key"), GeminiModelProvider)
    assert isinstance(create_model_provider("google-gemini", api_key="test-key"), GeminiModelProvider)


def test_model_provider_factory_routes_anthropic_aliases() -> None:
    assert isinstance(create_model_provider("anthropic", api_key="test-key"), AnthropicModelProvider)
    assert isinstance(create_model_provider("claude", api_key="test-key"), AnthropicModelProvider)


def test_model_provider_factory_routes_deepseek() -> None:
    assert isinstance(create_model_provider("deepseek", api_key="test-key"), DeepSeekModelProvider)


def test_codex_provider_requires_oauth_without_client(tmp_path) -> None:
    from model_providers.codex.auth import CodexAuthStore

    with pytest.raises(ModelProviderConfigError, match="not connected"):
        CodexModelProvider(auth_store=CodexAuthStore(tmp_path / "codex.json"))


def test_normalize_model_provider_name_accepts_codex_aliases() -> None:
    assert normalize_model_provider_name("openai") == "openai"
    assert normalize_model_provider_name("codex") == "codex-oauth"
    assert normalize_model_provider_name("openai_codex") == "codex-oauth"
    assert normalize_model_provider_name("claude") == "anthropic"
    assert normalize_model_provider_name("deepseek") == "deepseek"
    assert normalize_model_provider_name("google") == "gemini"


def test_resolve_model_provider_uses_current_settings(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeProvider:
        name = "fake"

    def fake_create_model_provider(name: str, **kwargs):
        captured["name"] = name
        captured["kwargs"] = kwargs
        return FakeProvider()

    monkeypatch.setattr(
        "model_providers.resolver.resolve_ai_settings",
        lambda: SimpleNamespace(provider="openai", model="gpt-settings", api_key="sk-test"),
    )
    monkeypatch.setattr("model_providers.resolver.create_model_provider", fake_create_model_provider)

    resolved = resolve_model_provider()

    assert resolved.provider_name == "openai"
    assert resolved.model == "gpt-settings"
    assert captured["name"] == "openai"
    assert captured["kwargs"] == {"default_model": "gpt-settings", "api_key": "sk-test"}


def test_builtin_provider_profiles_are_registered() -> None:
    profiles = {profile.name: profile for profile in list_provider_profiles()}

    assert "openai" in profiles
    assert "codex-oauth" in profiles
    assert "anthropic" in profiles
    assert "deepseek" in profiles
    assert "gemini" in profiles
    assert get_provider_profile("codex").name == "codex-oauth"
    assert get_provider_profile("claude").name == "anthropic"
    assert get_provider_profile("google").name == "gemini"
    assert profiles["openai"].default_model == "gpt-5.5"
    assert profiles["codex-oauth"].models[0].value == "gpt-5.5"
    assert "gpt-5.3-codex-spark" in [model.value for model in profiles["codex-oauth"].models]
    assert profiles["anthropic"].default_model == "claude-sonnet-4-6"
    assert profiles["deepseek"].default_model == "deepseek-v4-flash"
    assert profiles["gemini"].default_model == "gemini-3-flash-preview"
    assert [model.value for model in profiles["gemini"].models] == [
        "gemini-3-flash-preview",
        "gemini-3-pro-preview",
    ]


def test_provider_profile_registry_accepts_registered_profile_names() -> None:
    profile = ModelProviderProfile(
        name="local-test-provider",
        display_name="Local Test",
        auth_type="none",
    )

    register_provider_profile(profile)

    assert get_provider_profile("local_test_provider") is profile
