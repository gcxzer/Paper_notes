from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app_config.ai_settings import (
    CODEX_PROVIDER,
    environment_key_configured,
    local_key_configured,
    resolve_api_key_for_provider,
    resolve_model_for_provider,
    resolve_ai_settings,
)
from app_config.secrets import default_secrets_path, parse_env_file
from model_providers.profiles import ModelOption, ModelProviderProfile, list_provider_profiles, model_options_for_provider
from ui.backend.codex_auth_api import get_codex_auth_status


def register_model_provider_routes(app: FastAPI) -> None:
    @app.get("/api/model/providers")
    async def api_get_model_providers() -> JSONResponse:
        return JSONResponse(get_model_providers())


def get_model_providers(*, secrets_path: str | Path | None = None) -> dict[str, object]:
    codex_auth = get_codex_auth_status()
    settings = resolve_ai_settings(secrets_path=secrets_path, codex_auth=codex_auth)
    resolved_secrets_path = Path(secrets_path) if secrets_path is not None else default_secrets_path()
    local_values = parse_env_file(resolved_secrets_path)
    return {
        "defaultProvider": settings.provider,
        "defaultModel": settings.model,
        "modelConnectionConfigured": settings.model_connection_configured,
        "providers": [
            _profile_payload(
                profile,
                secrets_path=resolved_secrets_path,
                local_values=local_values,
                codex_logged_in=settings.codex_auth.logged_in,
            )
            for profile in list_provider_profiles()
        ],
    }


def _profile_payload(
    profile: ModelProviderProfile,
    *,
    secrets_path: str | Path | None,
    local_values: dict[str, str],
    codex_logged_in: bool,
) -> dict[str, object]:
    model = resolve_model_for_provider(profile.name, secrets_path=secrets_path)
    key = resolve_api_key_for_provider(profile.name, secrets_path=secrets_path)
    selected_model = model.value or profile.default_model
    configured = codex_logged_in if profile.name == CODEX_PROVIDER else key.configured
    return {
        **profile.to_public_dict(),
        "configured": configured,
        "ready": bool(configured and selected_model),
        "keySource": key.source,
        "localKeyConfigured": local_key_configured(local_values, profile.name),
        "environmentKeyConfigured": environment_key_configured(profile.name),
        "model": selected_model,
        "selectedModel": selected_model,
        "modelSource": model.source if model.value else "profile",
        "models": [_model_option_payload(option) for option in model_options_for_provider(profile.name, selected_model)],
    }


def _model_option_payload(option: ModelOption) -> dict[str, object]:
    return option.to_public_dict()
