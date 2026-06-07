from __future__ import annotations

from app_config.ai_settings import ANTHROPIC_PROVIDER, CODEX_PROVIDER, DEEPSEEK_PROVIDER, OPENAI_PROVIDER
from model_providers.profiles.builtin import BUILTIN_PROFILES
from model_providers.profiles.types import ModelCapabilities, ModelOption, ModelProviderProfile


_REGISTRY: dict[str, ModelProviderProfile] = {}
_ALIASES: dict[str, str] = {}


def register_provider_profile(profile: ModelProviderProfile) -> None:
    _REGISTRY[profile.name] = profile
    _ALIASES[_normalize_provider_alias(profile.name)] = profile.name
    for alias in profile.aliases:
        _ALIASES[_normalize_provider_alias(alias)] = profile.name


def get_provider_profile(name: object) -> ModelProviderProfile | None:
    normalized = normalize_provider_profile_name(name)
    return _REGISTRY.get(normalized) if normalized else None


def list_provider_profiles() -> list[ModelProviderProfile]:
    return list(_REGISTRY.values())


def normalize_provider_profile_name(name: object) -> str:
    normalized = _normalize_provider_alias(name)
    aliases = {
        "": "",
        OPENAI_PROVIDER: OPENAI_PROVIDER,
        "codex": CODEX_PROVIDER,
        CODEX_PROVIDER: CODEX_PROVIDER,
        "openai-codex": CODEX_PROVIDER,
        "claude": ANTHROPIC_PROVIDER,
        ANTHROPIC_PROVIDER: ANTHROPIC_PROVIDER,
        DEEPSEEK_PROVIDER: DEEPSEEK_PROVIDER,
    }
    return _ALIASES.get(normalized, aliases.get(normalized, normalized if normalized in _REGISTRY else ""))


def model_options_for_provider(provider: object, selected_model: object = "") -> list[ModelOption]:
    profile = get_provider_profile(provider)
    options = list(profile.models if profile else ())
    selected = str(selected_model or "").strip()
    if selected and all(option.value != selected for option in options):
        options.append(ModelOption(selected, selected, selected, "Current saved model"))
    return options


def capabilities_for_provider_model(provider: object, model: object = "") -> ModelCapabilities:
    profile = get_provider_profile(provider)
    if profile is None:
        return ModelCapabilities()
    return profile.capabilities_for_model(model)


def _normalize_provider_alias(name: object) -> str:
    return str(name or "").strip().lower().replace("_", "-")


for _profile in BUILTIN_PROFILES:
    register_provider_profile(_profile)
