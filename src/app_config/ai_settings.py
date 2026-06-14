from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from app_config.secrets import default_env_paths, default_secrets_path, parse_env_file, write_env_values


AI_PROVIDER = "PAPER_NOTES_AI_PROVIDER"
ANTHROPIC_API_KEY = "ANTHROPIC_API_KEY"
ANTHROPIC_MODEL = "ANTHROPIC_MODEL"
CODEX_MODEL = "CODEX_MODEL"
DEEPSEEK_API_KEY = "DEEPSEEK_API_KEY"
DEEPSEEK_MODEL = "DEEPSEEK_MODEL"
GEMINI_API_KEY = "GEMINI_API_KEY"
GEMINI_MODEL = "GEMINI_MODEL"
GOOGLE_API_KEY = "GOOGLE_API_KEY"
OPENAI_API_KEY = "OPENAI_API_KEY"
OPENAI_MODEL = "OPENAI_MODEL"
TAVILY_API_KEY = "TAVILY_API_KEY"
BRAVE_SEARCH_API_KEY = "BRAVE_SEARCH_API_KEY"

OPENAI_PROVIDER = "openai"
ANTHROPIC_PROVIDER = "anthropic"
CODEX_PROVIDER = "codex-oauth"
DEEPSEEK_PROVIDER = "deepseek"
GEMINI_PROVIDER = "gemini"
SUPPORTED_AI_PROVIDERS = frozenset({
    OPENAI_PROVIDER,
    ANTHROPIC_PROVIDER,
    CODEX_PROVIDER,
    DEEPSEEK_PROVIDER,
    GEMINI_PROVIDER,
})
AI_PROVIDER_ALIASES = {
    "": "",
    "api-key": OPENAI_PROVIDER,
    "openai-api-key": OPENAI_PROVIDER,
    OPENAI_PROVIDER: OPENAI_PROVIDER,
    "claude": ANTHROPIC_PROVIDER,
    ANTHROPIC_PROVIDER: ANTHROPIC_PROVIDER,
    "codex": CODEX_PROVIDER,
    CODEX_PROVIDER: CODEX_PROVIDER,
    "openai-codex": CODEX_PROVIDER,
    "deep-seek": DEEPSEEK_PROVIDER,
    DEEPSEEK_PROVIDER: DEEPSEEK_PROVIDER,
    "google": GEMINI_PROVIDER,
    "google-ai-studio": GEMINI_PROVIDER,
    "google-gemini": GEMINI_PROVIDER,
    "google-genai": GEMINI_PROVIDER,
    GEMINI_PROVIDER: GEMINI_PROVIDER,
}


@dataclass(frozen=True, slots=True)
class ResolvedValue:
    value: str = ""
    source: str = "missing"
    path: Path | None = None

    @property
    def configured(self) -> bool:
        return bool(self.value)


@dataclass(frozen=True, slots=True)
class CodexAuthSettings:
    logged_in: bool = False
    auth_mode: str = ""
    plan_type: str = ""
    account_id: str = ""
    account_email: str = ""
    last_refresh: str = ""
    auth_store_path: str = ""

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any] | None = None) -> CodexAuthSettings:
        data = dict(payload or {})
        return cls(
            logged_in=_bool(data.get("loggedIn", data.get("logged_in"))),
            auth_mode=_text(data.get("authMode", data.get("auth_mode"))),
            plan_type=_text(data.get("planType", data.get("plan_type"))),
            account_id=_text(data.get("accountId", data.get("account_id"))),
            account_email=_text(data.get("accountEmail", data.get("account_email"))),
            last_refresh=_text(data.get("lastRefresh", data.get("last_refresh"))),
            auth_store_path=_text(data.get("authStorePath", data.get("auth_store_path"))),
        )

    def to_public_dict(self) -> dict[str, object]:
        return {
            "provider": CODEX_PROVIDER,
            "loggedIn": self.logged_in,
            "authMode": self.auth_mode,
            "planType": self.plan_type,
            "accountId": self.account_id,
            "accountEmail": self.account_email,
            "lastRefresh": self.last_refresh,
            "authStorePath": self.auth_store_path,
        }


@dataclass(frozen=True, slots=True)
class AISettings:
    provider: str = OPENAI_PROVIDER
    provider_source: str = "default"
    model: str = ""
    model_source: str = "profile"
    key_source: str = "missing"
    api_key: str = field(default="", repr=False)
    codex_auth: CodexAuthSettings = field(default_factory=CodexAuthSettings)
    local_key_configured: bool = False
    environment_key_configured: bool = False
    local_model_configured: bool = False
    environment_model_configured: bool = False
    local_provider_configured: bool = False
    environment_provider_configured: bool = False
    local_secrets_path: Path = field(default_factory=default_secrets_path)
    model_connection_configured: bool = False

    @property
    def configured(self) -> bool:
        if self.provider == CODEX_PROVIDER:
            return self.codex_auth.logged_in
        return bool(self.api_key)

    @property
    def ready(self) -> bool:
        return bool(self.configured and self.model)

    def to_public_dict(self) -> dict[str, object]:
        return {
            "provider": self.provider,
            "providerSource": self.provider_source,
            "supportedProviders": sorted(SUPPORTED_AI_PROVIDERS),
            "configured": self.configured,
            "ready": self.ready,
            "model": self.model,
            "modelConfigured": bool(self.model),
            "modelSource": self.model_source,
            "keySource": self.key_source,
            "localKeyConfigured": self.local_key_configured,
            "environmentKeyConfigured": self.environment_key_configured,
            "localModelConfigured": self.local_model_configured,
            "environmentModelConfigured": self.environment_model_configured,
            "localProviderConfigured": self.local_provider_configured,
            "environmentProviderConfigured": self.environment_provider_configured,
            "localSecretsPath": _display_path(self.local_secrets_path),
            "codexAuth": self.codex_auth.to_public_dict(),
            "modelConnectionConfigured": self.model_connection_configured,
        }


def resolve_ai_settings(
    *,
    secrets_path: str | Path | None = None,
    env_paths: tuple[Path, ...] | None = None,
    codex_auth: Mapping[str, Any] | CodexAuthSettings | None = None,
) -> AISettings:
    path = Path(secrets_path) if secrets_path is not None else default_secrets_path()
    paths = env_paths if env_paths is not None else default_env_paths()
    auth = codex_auth if isinstance(codex_auth, CodexAuthSettings) else (
        CodexAuthSettings.from_mapping(codex_auth) if codex_auth is not None else _current_codex_auth_settings()
    )
    local_values = parse_env_file(path)
    provider = _auto_selected_provider(
        resolve_ai_provider(secrets_path=path, env_paths=paths),
        openai_key_configured=resolve_openai_api_key(secrets_path=path, env_paths=paths).configured,
        anthropic_key_configured=resolve_anthropic_api_key(secrets_path=path, env_paths=paths).configured,
        deepseek_key_configured=resolve_deepseek_api_key(secrets_path=path, env_paths=paths).configured,
        gemini_key_configured=resolve_gemini_api_key(secrets_path=path, env_paths=paths).configured,
        codex_configured=auth.logged_in,
    )
    key = resolve_api_key_for_provider(provider.value, secrets_path=path, env_paths=paths)
    model = _model_or_profile_default(provider.value, resolve_model_for_provider(provider.value, secrets_path=path, env_paths=paths))
    return AISettings(
        provider=provider.value,
        provider_source=provider.source,
        model=model.value,
        model_source=model.source,
        key_source=key.source,
        api_key=key.value,
        codex_auth=auth,
        local_key_configured=local_key_configured(local_values, provider.value),
        environment_key_configured=environment_key_configured(provider.value),
        local_model_configured=bool(local_values.get(model_env_name(provider.value), "").strip()),
        environment_model_configured=bool(_env_value(model_env_name(provider.value))),
        local_provider_configured=bool(local_values.get(AI_PROVIDER, "").strip()),
        environment_provider_configured=bool(_env_value(AI_PROVIDER)),
        local_secrets_path=path,
        model_connection_configured=bool(auth.logged_in if provider.value == CODEX_PROVIDER else key.value),
    )


def resolve_ai_provider(
    *,
    secrets_path: str | Path | None = None,
    env_paths: tuple[Path, ...] | None = None,
) -> ResolvedValue:
    resolved = resolve_setting_value(AI_PROVIDER, secrets_path=secrets_path, env_paths=env_paths)
    provider = normalize_ai_provider(resolved.value)
    if provider:
        return ResolvedValue(provider, resolved.source, resolved.path)
    return ResolvedValue(OPENAI_PROVIDER, "default")


def resolve_model_for_provider(
    provider: str,
    *,
    secrets_path: str | Path | None = None,
    env_paths: tuple[Path, ...] | None = None,
) -> ResolvedValue:
    return resolve_setting_value(model_env_name(provider), secrets_path=secrets_path, env_paths=env_paths)


def resolve_api_key_for_provider(
    provider: str,
    *,
    secrets_path: str | Path | None = None,
    env_paths: tuple[Path, ...] | None = None,
) -> ResolvedValue:
    normalized = normalize_ai_provider(provider)
    if normalized == ANTHROPIC_PROVIDER:
        return resolve_anthropic_api_key(secrets_path=secrets_path, env_paths=env_paths)
    if normalized == DEEPSEEK_PROVIDER:
        return resolve_deepseek_api_key(secrets_path=secrets_path, env_paths=env_paths)
    if normalized == GEMINI_PROVIDER:
        return resolve_gemini_api_key(secrets_path=secrets_path, env_paths=env_paths)
    if normalized == CODEX_PROVIDER:
        return ResolvedValue()
    return resolve_openai_api_key(secrets_path=secrets_path, env_paths=env_paths)


def resolve_openai_api_key(
    *,
    secrets_path: str | Path | None = None,
    env_paths: tuple[Path, ...] | None = None,
) -> ResolvedValue:
    return resolve_setting_value(OPENAI_API_KEY, secrets_path=secrets_path, env_paths=env_paths)


def resolve_anthropic_api_key(
    *,
    secrets_path: str | Path | None = None,
    env_paths: tuple[Path, ...] | None = None,
) -> ResolvedValue:
    return resolve_setting_value(ANTHROPIC_API_KEY, secrets_path=secrets_path, env_paths=env_paths)


def resolve_deepseek_api_key(
    *,
    secrets_path: str | Path | None = None,
    env_paths: tuple[Path, ...] | None = None,
) -> ResolvedValue:
    return resolve_setting_value(DEEPSEEK_API_KEY, secrets_path=secrets_path, env_paths=env_paths)


def resolve_gemini_api_key(
    *,
    secrets_path: str | Path | None = None,
    env_paths: tuple[Path, ...] | None = None,
) -> ResolvedValue:
    gemini = resolve_setting_value(GEMINI_API_KEY, secrets_path=secrets_path, env_paths=env_paths)
    return gemini if gemini.value else resolve_setting_value(GOOGLE_API_KEY, secrets_path=secrets_path, env_paths=env_paths)


def resolve_tavily_api_key(
    *,
    secrets_path: str | Path | None = None,
    env_paths: tuple[Path, ...] | None = None,
) -> ResolvedValue:
    return resolve_setting_value(TAVILY_API_KEY, secrets_path=secrets_path, env_paths=env_paths)


def resolve_brave_search_api_key(
    *,
    secrets_path: str | Path | None = None,
    env_paths: tuple[Path, ...] | None = None,
) -> ResolvedValue:
    return resolve_setting_value(BRAVE_SEARCH_API_KEY, secrets_path=secrets_path, env_paths=env_paths)


def resolve_setting_value(
    name: str,
    *,
    secrets_path: str | Path | None = None,
    env_paths: tuple[Path, ...] | None = None,
) -> ResolvedValue:
    env_value = _env_value(name)
    if env_value:
        return ResolvedValue(env_value, "environment")

    local_path = Path(secrets_path) if secrets_path is not None else default_secrets_path()
    local_value = parse_env_file(local_path).get(name, "").strip()
    if local_value:
        return ResolvedValue(local_value, "local", local_path)

    for path in env_paths if env_paths is not None else default_env_paths():
        value = parse_env_file(path).get(name, "").strip()
        if value:
            return ResolvedValue(value, path.name, path)

    return ResolvedValue()


def save_local_ai_settings(
    *,
    provider: str | None = None,
    model: str | None = None,
    api_key: str | None = None,
    api_key_provider: str | None = None,
    secrets_path: str | Path | None = None,
    codex_auth: Mapping[str, Any] | CodexAuthSettings | None = None,
) -> AISettings:
    path = Path(secrets_path) if secrets_path is not None else default_secrets_path()
    active_provider = normalize_ai_provider(provider) if provider is not None else resolve_ai_provider(secrets_path=path).value
    if not active_provider:
        raise ValueError("Unsupported AI provider.")

    updates: dict[str, str | None] = {}
    if provider is not None:
        updates[AI_PROVIDER] = active_provider
    if model is not None:
        updates[model_env_name(active_provider)] = _clean_setting(model) or None
    if api_key is not None and _clean_setting(api_key):
        key_provider = normalize_ai_provider(api_key_provider) if api_key_provider is not None else active_provider
        if key_provider == CODEX_PROVIDER and api_key_provider is None:
            key_provider = OPENAI_PROVIDER
        if key_provider == CODEX_PROVIDER or not key_provider:
            raise ValueError("Unsupported API key provider.")
        updates[api_key_env_name(key_provider)] = _clean_setting(api_key)

    if updates:
        write_env_values(path, updates)
    return resolve_ai_settings(secrets_path=path, codex_auth=codex_auth)


def delete_local_ai_api_key(
    provider: str = OPENAI_PROVIDER,
    *,
    secrets_path: str | Path | None = None,
    codex_auth: Mapping[str, Any] | CodexAuthSettings | None = None,
) -> AISettings:
    path = Path(secrets_path) if secrets_path is not None else default_secrets_path()
    normalized = normalize_ai_provider(provider) or OPENAI_PROVIDER
    if normalized == GEMINI_PROVIDER:
        updates = {GEMINI_API_KEY: None, GOOGLE_API_KEY: None}
    elif normalized == ANTHROPIC_PROVIDER:
        updates = {ANTHROPIC_API_KEY: None}
    elif normalized == DEEPSEEK_PROVIDER:
        updates = {DEEPSEEK_API_KEY: None}
    elif normalized == OPENAI_PROVIDER:
        updates = {OPENAI_API_KEY: None}
    else:
        raise ValueError("Unsupported API key provider.")
    write_env_values(path, updates)
    return resolve_ai_settings(secrets_path=path, codex_auth=codex_auth)


def normalize_ai_provider(value: object) -> str:
    provider = str(value or "").strip().lower().replace("_", "-")
    return AI_PROVIDER_ALIASES.get(provider, provider if provider in SUPPORTED_AI_PROVIDERS else "")


def model_env_name(provider: str) -> str:
    normalized = normalize_ai_provider(provider)
    if normalized == CODEX_PROVIDER:
        return CODEX_MODEL
    if normalized == ANTHROPIC_PROVIDER:
        return ANTHROPIC_MODEL
    if normalized == DEEPSEEK_PROVIDER:
        return DEEPSEEK_MODEL
    if normalized == GEMINI_PROVIDER:
        return GEMINI_MODEL
    return OPENAI_MODEL


def api_key_env_name(provider: str) -> str:
    normalized = normalize_ai_provider(provider)
    if normalized == GEMINI_PROVIDER:
        return GEMINI_API_KEY
    if normalized == ANTHROPIC_PROVIDER:
        return ANTHROPIC_API_KEY
    if normalized == DEEPSEEK_PROVIDER:
        return DEEPSEEK_API_KEY
    return OPENAI_API_KEY


def local_key_configured(local_values: Mapping[str, str], provider: str) -> bool:
    normalized = normalize_ai_provider(provider)
    if normalized == GEMINI_PROVIDER:
        return bool(local_values.get(GEMINI_API_KEY, "").strip() or local_values.get(GOOGLE_API_KEY, "").strip())
    if normalized == CODEX_PROVIDER:
        return False
    return bool(local_values.get(api_key_env_name(normalized), "").strip())


def environment_key_configured(provider: str) -> bool:
    normalized = normalize_ai_provider(provider)
    if normalized == GEMINI_PROVIDER:
        return bool(_env_value(GEMINI_API_KEY) or _env_value(GOOGLE_API_KEY))
    if normalized == CODEX_PROVIDER:
        return False
    return bool(_env_value(api_key_env_name(normalized)))


def _auto_selected_provider(
    provider: ResolvedValue,
    *,
    openai_key_configured: bool,
    anthropic_key_configured: bool,
    deepseek_key_configured: bool,
    gemini_key_configured: bool,
    codex_configured: bool,
) -> ResolvedValue:
    if provider.source not in {"default", "auto", "missing"}:
        return provider
    available = []
    if openai_key_configured:
        available.append(OPENAI_PROVIDER)
    if anthropic_key_configured:
        available.append(ANTHROPIC_PROVIDER)
    if deepseek_key_configured:
        available.append(DEEPSEEK_PROVIDER)
    if gemini_key_configured:
        available.append(GEMINI_PROVIDER)
    if codex_configured:
        available.append(CODEX_PROVIDER)
    if len(available) == 1 and provider.value != available[0]:
        return ResolvedValue(available[0], "auto")
    return provider


def _model_or_profile_default(provider: str, resolved: ResolvedValue) -> ResolvedValue:
    if resolved.value:
        return resolved
    from model_providers.profiles.registry import get_provider_profile

    profile = get_provider_profile(provider)
    if profile is not None and profile.default_model:
        return ResolvedValue(profile.default_model, "profile")
    return resolved


def _current_codex_auth_settings() -> CodexAuthSettings:
    try:
        from openai_codex import Codex

        with Codex() as codex:
            response = codex.account(refresh_token=True)
    except Exception:
        return CodexAuthSettings()
    account = getattr(response, "account", None)
    if account is None:
        return CodexAuthSettings()
    root = getattr(account, "root", account)
    account_type = _enum_value(getattr(root, "type", "")) or type(root).__name__
    return CodexAuthSettings(
        logged_in=True,
        auth_mode="chatgpt" if account_type == "chatgpt" else account_type,
        account_email=_text(getattr(root, "email", "")),
        plan_type=_enum_value(getattr(root, "plan_type", "")),
    )


def _env_value(name: str) -> str:
    return os.environ.get(name, "").strip()


def _clean_setting(value: object) -> str:
    return str(value or "").strip()


def _text(value: object) -> str:
    return str(value or "").strip()


def _bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _enum_value(value: Any) -> str:
    return str(getattr(value, "value", value) or "").strip()


def _display_path(path: Path) -> str:
    try:
        return str(path.expanduser().resolve().relative_to(Path.cwd().resolve()))
    except ValueError:
        return str(path)
