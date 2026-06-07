from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from app_config.secrets import LOCAL_STATE_DIR, default_env_paths, default_secrets_path, parse_env_file, write_env_values


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
SUPPORTED_AI_PROVIDERS = frozenset({OPENAI_PROVIDER, ANTHROPIC_PROVIDER, CODEX_PROVIDER, DEEPSEEK_PROVIDER, GEMINI_PROVIDER})
DEFAULT_CODEX_AUTH_PATH = LOCAL_STATE_DIR / "auth" / "codex.json"


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
    auth_store_path: str = field(default_factory=lambda: _display_path(_default_codex_auth_path()))

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
    provider: str = "openai"
    provider_source: str = "default"
    model: str = ""
    model_source: str = "missing"
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
    codex_auth_path: str | Path | None = None,
) -> AISettings:
    path = Path(secrets_path) if secrets_path is not None else default_secrets_path()
    paths = env_paths if env_paths is not None else default_env_paths()
    provider_setting = resolve_ai_provider(secrets_path=path, env_paths=paths)
    openai_key = resolve_openai_api_key(secrets_path=path, env_paths=paths)
    anthropic_key = resolve_anthropic_api_key(secrets_path=path, env_paths=paths)
    deepseek_key = resolve_deepseek_api_key(secrets_path=path, env_paths=paths)
    gemini_key = resolve_gemini_api_key(secrets_path=path, env_paths=paths)
    codex_auth = _read_codex_auth_status(codex_auth_path)
    provider = _auto_selected_provider(
        provider_setting,
        openai_key_configured=bool(openai_key.value),
        anthropic_key_configured=bool(anthropic_key.value),
        deepseek_key_configured=bool(deepseek_key.value),
        gemini_key_configured=bool(gemini_key.value),
        codex_configured=codex_auth.logged_in,
    )
    key = resolve_api_key_for_provider(provider.value, secrets_path=path, env_paths=paths)
    model = resolve_model_for_provider(provider.value, secrets_path=path, env_paths=paths)
    local_values = parse_env_file(path)
    environment_key_configured = _environment_key_configured(provider.value)
    environment_model = _env_value(_model_env_name(provider.value))
    environment_provider = _env_value(AI_PROVIDER)
    return AISettings(
        provider=provider.value,
        provider_source=provider.source,
        model=model.value,
        model_source=model.source,
        key_source=key.source,
        api_key=key.value,
        codex_auth=codex_auth,
        local_key_configured=_local_key_configured(local_values, provider.value),
        environment_key_configured=environment_key_configured,
        local_model_configured=bool(local_values.get(_model_env_name(provider.value), "").strip()),
        environment_model_configured=bool(environment_model),
        local_provider_configured=bool(local_values.get(AI_PROVIDER, "").strip()),
        environment_provider_configured=bool(environment_provider),
        local_secrets_path=path,
        model_connection_configured=bool(key.value or codex_auth.logged_in),
    )


def resolve_ai_provider(
    *,
    secrets_path: str | Path | None = None,
    env_paths: tuple[Path, ...] | None = None,
) -> ResolvedValue:
    resolved = _resolve_value(
        AI_PROVIDER,
        secrets_path=secrets_path,
        env_paths=env_paths,
    )
    provider = _normalize_provider(resolved.value)
    if provider:
        return ResolvedValue(provider, resolved.source, resolved.path)
    return ResolvedValue(OPENAI_PROVIDER, "default")


def _auto_selected_provider(
    provider: ResolvedValue,
    *,
    openai_key_configured: bool,
    anthropic_key_configured: bool,
    deepseek_key_configured: bool,
    gemini_key_configured: bool,
    codex_configured: bool,
) -> ResolvedValue:
    if provider.source not in {"default", "auto"}:
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


def resolve_model_for_provider(
    provider: str,
    *,
    secrets_path: str | Path | None = None,
    env_paths: tuple[Path, ...] | None = None,
) -> ResolvedValue:
    return _resolve_value(
        _model_env_name(provider),
        secrets_path=secrets_path,
        env_paths=env_paths,
    )


def resolve_openai_api_key(
    *,
    secrets_path: str | Path | None = None,
    env_paths: tuple[Path, ...] | None = None,
) -> ResolvedValue:
    return _resolve_value(
        OPENAI_API_KEY,
        secrets_path=secrets_path,
        env_paths=env_paths,
    )


def resolve_anthropic_api_key(
    *,
    secrets_path: str | Path | None = None,
    env_paths: tuple[Path, ...] | None = None,
) -> ResolvedValue:
    return _resolve_value(
        ANTHROPIC_API_KEY,
        secrets_path=secrets_path,
        env_paths=env_paths,
    )


def resolve_deepseek_api_key(
    *,
    secrets_path: str | Path | None = None,
    env_paths: tuple[Path, ...] | None = None,
) -> ResolvedValue:
    return _resolve_value(
        DEEPSEEK_API_KEY,
        secrets_path=secrets_path,
        env_paths=env_paths,
    )


def resolve_gemini_api_key(
    *,
    secrets_path: str | Path | None = None,
    env_paths: tuple[Path, ...] | None = None,
) -> ResolvedValue:
    gemini = _resolve_value(
        GEMINI_API_KEY,
        secrets_path=secrets_path,
        env_paths=env_paths,
    )
    if gemini.value:
        return gemini
    return _resolve_value(
        GOOGLE_API_KEY,
        secrets_path=secrets_path,
        env_paths=env_paths,
    )


def resolve_api_key_for_provider(
    provider: str,
    *,
    secrets_path: str | Path | None = None,
    env_paths: tuple[Path, ...] | None = None,
) -> ResolvedValue:
    normalized = _normalize_provider(provider)
    if normalized == ANTHROPIC_PROVIDER:
        return resolve_anthropic_api_key(secrets_path=secrets_path, env_paths=env_paths)
    if normalized == DEEPSEEK_PROVIDER:
        return resolve_deepseek_api_key(secrets_path=secrets_path, env_paths=env_paths)
    if normalized == GEMINI_PROVIDER:
        return resolve_gemini_api_key(secrets_path=secrets_path, env_paths=env_paths)
    if normalized == CODEX_PROVIDER:
        return ResolvedValue()
    return resolve_openai_api_key(secrets_path=secrets_path, env_paths=env_paths)


def resolve_tavily_api_key(
    *,
    secrets_path: str | Path | None = None,
    env_paths: tuple[Path, ...] | None = None,
) -> ResolvedValue:
    return _resolve_value(
        TAVILY_API_KEY,
        secrets_path=secrets_path,
        env_paths=env_paths,
    )


def resolve_brave_search_api_key(
    *,
    secrets_path: str | Path | None = None,
    env_paths: tuple[Path, ...] | None = None,
) -> ResolvedValue:
    return _resolve_value(
        BRAVE_SEARCH_API_KEY,
        secrets_path=secrets_path,
        env_paths=env_paths,
    )


def resolve_openai_model(
    *,
    secrets_path: str | Path | None = None,
    env_paths: tuple[Path, ...] | None = None,
) -> ResolvedValue:
    return _resolve_value(
        OPENAI_MODEL,
        secrets_path=secrets_path,
        env_paths=env_paths,
    )


def resolve_anthropic_model(
    *,
    secrets_path: str | Path | None = None,
    env_paths: tuple[Path, ...] | None = None,
) -> ResolvedValue:
    return _resolve_value(
        ANTHROPIC_MODEL,
        secrets_path=secrets_path,
        env_paths=env_paths,
    )


def resolve_deepseek_model(
    *,
    secrets_path: str | Path | None = None,
    env_paths: tuple[Path, ...] | None = None,
) -> ResolvedValue:
    return _resolve_value(
        DEEPSEEK_MODEL,
        secrets_path=secrets_path,
        env_paths=env_paths,
    )


def resolve_gemini_model(
    *,
    secrets_path: str | Path | None = None,
    env_paths: tuple[Path, ...] | None = None,
) -> ResolvedValue:
    return _resolve_value(
        GEMINI_MODEL,
        secrets_path=secrets_path,
        env_paths=env_paths,
    )


def save_local_ai_settings(
    *,
    provider: str | None = None,
    model: str | None = None,
    api_key: str | None = None,
    api_key_provider: str | None = None,
    secrets_path: str | Path | None = None,
    codex_auth_path: str | Path | None = None,
) -> AISettings:
    path = Path(secrets_path) if secrets_path is not None else default_secrets_path()
    active_provider = _normalize_provider(provider) if provider is not None else resolve_ai_provider(secrets_path=path).value
    if not active_provider:
        raise ValueError("Unsupported AI provider.")
    updates: dict[str, str | None] = {}
    if provider is not None:
        updates[AI_PROVIDER] = active_provider
    if model is not None:
        updates[_model_env_name(active_provider)] = _clean_setting(model) or None
    if api_key is not None and _clean_setting(api_key):
        key_provider = _normalize_provider(api_key_provider) if api_key_provider is not None else active_provider
        if key_provider == CODEX_PROVIDER and api_key_provider is None:
            key_provider = OPENAI_PROVIDER
        if key_provider == CODEX_PROVIDER or not key_provider:
            raise ValueError("Unsupported API key provider.")
        updates[_api_key_env_name(key_provider)] = _clean_setting(api_key)
    if updates:
        write_env_values(path, updates)
    return resolve_ai_settings(secrets_path=path, codex_auth_path=codex_auth_path)


def delete_local_ai_api_key(
    provider: str = OPENAI_PROVIDER,
    *,
    secrets_path: str | Path | None = None,
    codex_auth_path: str | Path | None = None,
) -> AISettings:
    path = Path(secrets_path) if secrets_path is not None else default_secrets_path()
    normalized = _normalize_provider(provider) or OPENAI_PROVIDER
    if normalized == GEMINI_PROVIDER:
        write_env_values(path, {GEMINI_API_KEY: None, GOOGLE_API_KEY: None})
    elif normalized == ANTHROPIC_PROVIDER:
        write_env_values(path, {ANTHROPIC_API_KEY: None})
    elif normalized == DEEPSEEK_PROVIDER:
        write_env_values(path, {DEEPSEEK_API_KEY: None})
    elif normalized == OPENAI_PROVIDER:
        write_env_values(path, {OPENAI_API_KEY: None})
    else:
        raise ValueError("Unsupported API key provider.")
    return resolve_ai_settings(secrets_path=path, codex_auth_path=codex_auth_path)


def delete_local_openai_api_key(
    *,
    secrets_path: str | Path | None = None,
    codex_auth_path: str | Path | None = None,
) -> AISettings:
    return delete_local_ai_api_key(
        OPENAI_PROVIDER,
        secrets_path=secrets_path,
        codex_auth_path=codex_auth_path,
    )


def _resolve_value(
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


def _env_value(name: str) -> str:
    return os.environ.get(name, "").strip()


def _clean_setting(value: object) -> str:
    return str(value or "").strip()


def _normalize_provider(value: object) -> str:
    provider = str(value or "").strip().lower().replace("_", "-")
    aliases = {
        "": "",
        OPENAI_PROVIDER: OPENAI_PROVIDER,
        "codex": CODEX_PROVIDER,
        CODEX_PROVIDER: CODEX_PROVIDER,
        "openai-codex": CODEX_PROVIDER,
        "claude": ANTHROPIC_PROVIDER,
        ANTHROPIC_PROVIDER: ANTHROPIC_PROVIDER,
        DEEPSEEK_PROVIDER: DEEPSEEK_PROVIDER,
        "google": GEMINI_PROVIDER,
        "google-gemini": GEMINI_PROVIDER,
        "google-ai-studio": GEMINI_PROVIDER,
        GEMINI_PROVIDER: GEMINI_PROVIDER,
    }
    return aliases.get(provider, "")


def _model_env_name(provider: str) -> str:
    normalized = _normalize_provider(provider)
    if normalized == CODEX_PROVIDER:
        return CODEX_MODEL
    if normalized == ANTHROPIC_PROVIDER:
        return ANTHROPIC_MODEL
    if normalized == DEEPSEEK_PROVIDER:
        return DEEPSEEK_MODEL
    if normalized == GEMINI_PROVIDER:
        return GEMINI_MODEL
    return OPENAI_MODEL


def _api_key_env_name(provider: str) -> str:
    normalized = _normalize_provider(provider)
    if normalized == GEMINI_PROVIDER:
        return GEMINI_API_KEY
    if normalized == ANTHROPIC_PROVIDER:
        return ANTHROPIC_API_KEY
    if normalized == DEEPSEEK_PROVIDER:
        return DEEPSEEK_API_KEY
    return OPENAI_API_KEY


def _local_key_configured(local_values: dict[str, str], provider: str) -> bool:
    if _normalize_provider(provider) == GEMINI_PROVIDER:
        return bool(local_values.get(GEMINI_API_KEY, "").strip() or local_values.get(GOOGLE_API_KEY, "").strip())
    return bool(local_values.get(_api_key_env_name(provider), "").strip())


def _environment_key_configured(provider: str) -> bool:
    if _normalize_provider(provider) == GEMINI_PROVIDER:
        return bool(_env_value(GEMINI_API_KEY) or _env_value(GOOGLE_API_KEY))
    return bool(_env_value(_api_key_env_name(provider)))


def _default_codex_auth_path() -> Path:
    override = os.environ.get("PAPER_NOTES_CODEX_AUTH_PATH", "").strip()
    return Path(override).expanduser() if override else DEFAULT_CODEX_AUTH_PATH


def _read_codex_auth_status(path: str | Path | None = None) -> CodexAuthSettings:
    from model_providers.codex.auth import CodexAuthStore

    status = CodexAuthStore(path or _default_codex_auth_path()).status()
    return CodexAuthSettings(
        logged_in=status.logged_in,
        auth_mode=status.auth_mode,
        plan_type=status.plan_type,
        account_id=status.account_id,
        account_email=status.account_email,
        last_refresh=status.last_refresh,
        auth_store_path=status.auth_store_path,
    )


def _display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(Path.cwd().resolve()))
    except ValueError:
        return str(path)
