from __future__ import annotations

from model_providers.profiles.builtin import (
    CODEX_PROVIDER,
    CONTEXT_WINDOW_TABLES_BY_PROVIDER,
    DEEPSEEK_PROVIDER,
    DEFAULT_FALLBACK_CONTEXT_LENGTH,
    OPENAI_PROVIDER,
    BUILTIN_PROFILES,
    OPENAI_CONTEXT_WINDOWS,
)
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
        "api-key": OPENAI_PROVIDER,
        "openai-api-key": OPENAI_PROVIDER,
        "codex": CODEX_PROVIDER,
        CODEX_PROVIDER: CODEX_PROVIDER,
        "openai-codex": CODEX_PROVIDER,
        "deep-seek": DEEPSEEK_PROVIDER,
        DEEPSEEK_PROVIDER: DEEPSEEK_PROVIDER,
    }
    return _ALIASES.get(normalized, aliases.get(normalized, normalized if normalized in _REGISTRY else ""))


def model_options_for_provider(provider: object, selected_model: object = "") -> list[ModelOption]:
    profile = get_provider_profile(provider)
    options = list(profile.models if profile else ())
    selected = str(selected_model or "").strip()
    if selected and _provider_allows_custom_model(provider) and all(option.value != selected for option in options):
        options.append(ModelOption(selected, selected, selected, "Current saved model"))
    return options


def capabilities_for_provider_model(provider: object, model: object = "") -> ModelCapabilities:
    profile = get_provider_profile(provider)
    if profile is None:
        return ModelCapabilities(context_window=resolve_context_length_for_model(provider, model))
    capabilities = profile.capabilities_for_model(model)
    resolved_model = model or profile.default_model
    resolved_context_window = resolve_context_length_for_model(provider, resolved_model)
    if resolved_context_window != capabilities.context_window:
        return capabilities.with_context_window(resolved_context_window)
    return capabilities


def resolve_context_length_for_model(provider: object, model: object) -> int:
    provider_name = normalize_provider_profile_name(provider)
    model_name = str(model or "").strip().lower()

    profile = get_provider_profile(provider_name)
    option = profile.option_for_model(model_name) if profile is not None else None
    if option is not None and option.capabilities is not None and option.capabilities.context_window > 0:
        return option.capabilities.context_window

    tables = CONTEXT_WINDOW_TABLES_BY_PROVIDER.get(provider_name)
    if tables is None:
        tables = OPENAI_CONTEXT_WINDOWS
    return _lookup_context_length(model_name, tables)


def _lookup_context_length(model_name: str, table: dict[str, int]) -> int:
    for key, value in sorted(table.items(), key=lambda item: len(item[0]), reverse=True):
        if key in model_name:
            return value
    return DEFAULT_FALLBACK_CONTEXT_LENGTH


def _normalize_provider_alias(name: object) -> str:
    return str(name or "").strip().lower().replace("_", "-")


def _provider_allows_custom_model(provider: object) -> bool:
    return normalize_provider_profile_name(provider) != CODEX_PROVIDER


for _profile in BUILTIN_PROFILES:
    register_provider_profile(_profile)
