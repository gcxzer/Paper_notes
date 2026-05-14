from __future__ import annotations

from pathlib import Path

from app_config.ai_settings import CODEX_PROVIDER, OPENAI_PROVIDER, resolve_ai_settings, resolve_model_for_provider
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
    configured = _provider_configured(profile.name, settings)
    model = resolve_model_for_provider(profile.name, secrets_path=secrets_path)
    selected_model = model.value or profile.default_model
    return {
        **profile.to_public_dict(),
        "configured": configured,
        "ready": bool(configured and selected_model),
        "model": selected_model,
        "selectedModel": selected_model,
        "modelSource": model.source if model.value else "profile",
        "models": [
            option.to_public_dict()
            for option in model_options_for_provider(profile.name, selected_model)
        ],
    }


def _provider_configured(provider: str, settings) -> bool:
    if provider == CODEX_PROVIDER:
        return bool(settings.codex_auth.logged_in)
    if provider == OPENAI_PROVIDER:
        return bool(settings.api_key)
    return False
