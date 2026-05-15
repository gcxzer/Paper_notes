from __future__ import annotations

from pathlib import Path

from app_config.ai_settings import (
    ANTHROPIC_PROVIDER,
    CODEX_PROVIDER,
    DEEPSEEK_PROVIDER,
    GEMINI_PROVIDER,
    OPENAI_PROVIDER,
    resolve_anthropic_api_key,
    resolve_ai_settings,
    resolve_api_key_for_provider,
    resolve_deepseek_api_key,
    resolve_gemini_api_key,
    resolve_model_for_provider,
    resolve_openai_api_key,
)
from context_compression.model_context import resolve_context_length_for_model
from model_providers.profiles import ModelProviderProfile, list_provider_profiles, model_options_for_provider


def get_model_providers(
    *,
    secrets_path: str | Path | None = None,
    codex_auth_path: str | Path | None = None,
) -> dict[str, object]:
    settings = resolve_ai_settings(secrets_path=secrets_path, codex_auth_path=codex_auth_path)
    providers = [
        _profile_payload(profile, settings=settings, secrets_path=secrets_path)
        for profile in list_provider_profiles()
    ]
    return {
        "defaultProvider": settings.provider,
        "defaultModel": settings.model,
        "modelConnectionConfigured": settings.model_connection_configured,
        "providers": providers,
    }


def _profile_payload(
    profile: ModelProviderProfile,
    *,
    settings,
    secrets_path: str | Path | None,
) -> dict[str, object]:
    configured = _provider_configured(profile.name, settings, secrets_path=secrets_path)
    model = resolve_model_for_provider(profile.name, secrets_path=secrets_path)
    key = resolve_api_key_for_provider(profile.name, secrets_path=secrets_path)
    selected_model = model.value or profile.default_model
    return {
        **profile.to_public_dict(),
        "configured": configured,
        "ready": bool(configured and selected_model),
        "keySource": key.source,
        "localKeyConfigured": key.source == "local",
        "environmentKeyConfigured": key.source == "environment",
        "model": selected_model,
        "selectedModel": selected_model,
        "modelSource": model.source if model.value else "profile",
        "models": [
            _model_option_payload(profile, option)
            for option in model_options_for_provider(profile.name, selected_model)
        ],
    }


def _model_option_payload(profile: ModelProviderProfile, option) -> dict[str, object]:
    payload = option.to_public_dict()
    capabilities = dict(payload.get("capabilities") or profile.default_capabilities.to_public_dict())
    capabilities["contextWindow"] = resolve_context_length_for_model(profile.name, option.value)
    payload["capabilities"] = capabilities
    return payload


def _provider_configured(provider: str, settings, *, secrets_path: str | Path | None = None) -> bool:
    if provider == CODEX_PROVIDER:
        return bool(settings.codex_auth.logged_in)
    if provider == OPENAI_PROVIDER:
        return bool(resolve_openai_api_key(secrets_path=secrets_path).value)
    if provider == ANTHROPIC_PROVIDER:
        return bool(resolve_anthropic_api_key(secrets_path=secrets_path).value)
    if provider == DEEPSEEK_PROVIDER:
        return bool(resolve_deepseek_api_key(secrets_path=secrets_path).value)
    if provider == GEMINI_PROVIDER:
        return bool(resolve_gemini_api_key(secrets_path=secrets_path).value)
    return False
