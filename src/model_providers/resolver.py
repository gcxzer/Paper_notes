from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app_config.ai_settings import (
    CODEX_PROVIDER,
    OPENAI_PROVIDER,
    SUPPORTED_AI_PROVIDERS,
    resolve_ai_settings,
    resolve_model_for_provider,
)
from model_providers.base import ModelProvider
from model_providers.factory import create_model_provider
from model_providers.profiles import get_provider_profile


@dataclass(frozen=True, slots=True)
class ResolvedModelProvider:
    provider: ModelProvider
    provider_name: str
    model: str


def normalize_model_provider_name(value: object) -> str:
    provider = str(value or "").strip().lower().replace("_", "-")
    aliases = {
        "": "",
        OPENAI_PROVIDER: OPENAI_PROVIDER,
        "codex": CODEX_PROVIDER,
        CODEX_PROVIDER: CODEX_PROVIDER,
        "openai-codex": CODEX_PROVIDER,
    }
    normalized = aliases.get(provider, "")
    if normalized and normalized in SUPPORTED_AI_PROVIDERS:
        return normalized
    if provider:
        raise ValueError(f"Unsupported model provider: {value}")
    return ""


def resolve_model_provider(
    provider_name: object = "",
    model: object = "",
    *,
    provider_kwargs: dict[str, Any] | None = None,
) -> ResolvedModelProvider:
    settings = resolve_ai_settings()
    normalized_provider = normalize_model_provider_name(provider_name) or settings.provider
    selected_model = str(model or "").strip() or _default_model_for_provider(
        normalized_provider,
        active_provider=settings.provider,
        active_model=settings.model,
    )

    kwargs = dict(provider_kwargs or {})
    if selected_model and "default_model" not in kwargs:
        kwargs["default_model"] = selected_model
    if normalized_provider == OPENAI_PROVIDER and settings.api_key and "api_key" not in kwargs:
        kwargs["api_key"] = settings.api_key

    return ResolvedModelProvider(
        provider=create_model_provider(normalized_provider, **kwargs),
        provider_name=normalized_provider,
        model=selected_model,
    )


def _default_model_for_provider(provider: str, *, active_provider: str, active_model: str) -> str:
    if provider == active_provider:
        return active_model or _profile_default_model(provider)
    return resolve_model_for_provider(provider).value or _profile_default_model(provider)


def _profile_default_model(provider: str) -> str:
    profile = get_provider_profile(provider)
    return profile.default_model if profile else ""
