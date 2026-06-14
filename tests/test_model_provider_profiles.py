from __future__ import annotations

from model_providers import (
    DEFAULT_FALLBACK_CONTEXT_LENGTH,
    ModelProviderProfile,
    capabilities_for_provider_model,
    get_provider_profile,
    list_provider_profiles,
    model_options_for_provider,
    normalize_provider_profile_name,
    register_provider_profile,
    resolve_context_length_for_model,
)


def test_builtin_provider_profiles_are_registered() -> None:
    profiles = {profile.name: profile for profile in list_provider_profiles()}

    assert {"openai", "codex-oauth", "anthropic", "gemini", "deepseek"} <= set(profiles)
    assert get_provider_profile("codex").name == "codex-oauth"
    assert get_provider_profile("claude").name == "anthropic"
    assert get_provider_profile("google-ai-studio").name == "gemini"
    assert profiles["openai"].default_model == "gpt-5.5"
    assert profiles["codex-oauth"].models[0].value == "gpt-5.5"
    assert profiles["anthropic"].default_model == "claude-sonnet-4-6"
    assert profiles["deepseek"].default_model == "deepseek-v4-flash"
    assert [model.value for model in profiles["gemini"].models] == [
        "gemini-3-flash-preview",
        "gemini-3-pro-preview",
    ]


def test_model_capabilities_include_model_specific_context_windows() -> None:
    assert capabilities_for_provider_model("openai", "gpt-5.5").context_window == 1_050_000
    assert capabilities_for_provider_model("openai", "gpt-5.4-mini").context_window == 400_000
    assert capabilities_for_provider_model("codex-oauth", "gpt-5.5").context_window == 258_000
    spark = capabilities_for_provider_model("codex", "gpt-5.3-codex-spark")
    assert spark.context_window == 128_000
    assert spark.supports_vision is False
    assert spark.supports_image_artifact_generation is False
    assert spark.supports_web_search is True
    assert spark.supports_reasoning_off is False
    assert capabilities_for_provider_model("anthropic", "claude-haiku-4-5-20251001").context_length == 200_000
    assert capabilities_for_provider_model("gemini", "gemini-3-pro-preview").context_window == 1_048_576
    assert capabilities_for_provider_model("deepseek", "deepseek-v4-pro").supports_vision is False


def test_context_length_resolution_uses_current_model_profiles() -> None:
    assert resolve_context_length_for_model("codex-oauth", "gpt-5.4") == 258_000
    assert resolve_context_length_for_model("openai", "gpt-5.5") == 1_050_000
    assert resolve_context_length_for_model("anthropic", "claude-opus-4-7") == 1_000_000
    assert resolve_context_length_for_model("anthropic", "claude-haiku-4-5-20251001") == 200_000
    assert resolve_context_length_for_model("gemini", "gemini-3-flash-preview") == 1_048_576
    assert resolve_context_length_for_model("deepseek", "deepseek-v4-flash") == 1_000_000
    assert resolve_context_length_for_model("gemini", "gemini-2.5-flash-lite") == DEFAULT_FALLBACK_CONTEXT_LENGTH
    assert resolve_context_length_for_model("openai", "unknown-model") == DEFAULT_FALLBACK_CONTEXT_LENGTH
    assert capabilities_for_provider_model("openai", "unknown-model").context_window == DEFAULT_FALLBACK_CONTEXT_LENGTH


def test_public_profile_payload_includes_capabilities() -> None:
    profile = get_provider_profile("openai")
    payload = profile.to_public_dict()

    assert payload["capabilities"]["supportsVision"] is True
    assert payload["capabilities"]["contextWindow"] == 1_050_000
    mini = next(model for model in payload["models"] if model["value"] == "gpt-5.4-mini")
    assert mini["capabilities"]["contextWindow"] == 400_000
    assert mini["capabilities"]["contextLength"] == 400_000


def test_provider_profile_registry_accepts_registered_profile_names() -> None:
    profile = ModelProviderProfile(
        name="local-test-provider",
        display_name="Local Test",
        auth_type="none",
    )

    register_provider_profile(profile)

    assert normalize_provider_profile_name("local_test_provider") == "local-test-provider"
    assert get_provider_profile("local_test_provider") is profile
    assert model_options_for_provider("openai", "saved-custom-model")[-1].description == "Current saved model"
    assert all(option.value != "gpt-5.3-codex" for option in model_options_for_provider("codex", "gpt-5.3-codex"))
    assert any(option.value == "gpt-5.3-codex-spark" for option in model_options_for_provider("codex"))
