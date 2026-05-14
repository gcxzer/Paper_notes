from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app_config.secrets import LOCAL_STATE_DIR, default_secrets_path, write_env_values
from app_config.ai_settings import (
    BRAVE_SEARCH_API_KEY,
    CODEX_PROVIDER,
    OPENAI_PROVIDER,
    TAVILY_API_KEY,
    delete_local_openai_api_key,
    resolve_ai_provider,
    resolve_brave_search_api_key,
    resolve_ai_settings,
    resolve_tavily_api_key,
    save_local_ai_settings,
)
from model_providers.codex.auth import CodexAuthStore, CodexDeviceAuthClient
from model_providers.profiles import get_provider_profile
from tools.catalog import ToolCatalog
from app_infra.storage import atomic_write_json


DEFAULT_TOOL_SETTINGS_PATH = LOCAL_STATE_DIR / "tool-settings.json"
TOOL_GLOBAL_DEFAULT = "default"
TOOL_GLOBAL_FULL_ACCESS = "full_access"
TOOL_ACCESS_VALUES = frozenset({"inherit", "ask", "auto", "warn", "readonly", "block", "halt", "disabled"})
NATIVE_WEB_SEARCH = "native_web_search"
LEGACY_NATIVE_WEB_SEARCH = "provider_native_web_search"
BUILT_IN_TOOL_SETTING_GROUPS = ("paper_notes", "code_execution", "persistent_memory", "session_search", "todo", "skills")
CUSTOM_TOOL_SETTING_GROUPS = ("web_search",)
VIRTUAL_TOOL_SETTING_GROUPS = (NATIVE_WEB_SEARCH,)
TOOL_SETTING_GROUPS = (*BUILT_IN_TOOL_SETTING_GROUPS, *CUSTOM_TOOL_SETTING_GROUPS)


def get_ai_settings(*, secrets_path: str | Path | None = None) -> dict[str, object]:
    return _public_ai_settings(resolve_ai_settings(secrets_path=secrets_path))


def update_ai_settings(body: Any, *, secrets_path: str | Path | None = None) -> dict[str, object]:
    if not isinstance(body, dict):
        raise ValueError("Request body must be a JSON object.")

    provider = _optional_string(body.get("provider"), "provider") if "provider" in body else None
    model = _optional_string(body.get("model"), "model") if "model" in body else None
    api_key_value = body.get("apiKey", body.get("api_key"))
    api_key = _optional_string(api_key_value, "apiKey") if api_key_value is not None else None
    settings = save_local_ai_settings(provider=provider, model=model, api_key=api_key, secrets_path=secrets_path)
    _reset_agent_service()
    return _public_ai_settings(settings)


def delete_ai_api_key(*, secrets_path: str | Path | None = None) -> dict[str, object]:
    settings = delete_local_openai_api_key(secrets_path=secrets_path)
    _reset_agent_service()
    return _public_ai_settings(settings)


def _public_ai_settings(settings: Any) -> dict[str, object]:
    payload = settings.to_public_dict()
    effective_model = str(payload.get("model") or "").strip()
    if not effective_model:
        profile = get_provider_profile(str(payload.get("provider") or ""))
        if profile is not None:
            effective_model = profile.default_model
            payload["model"] = effective_model
            payload["modelSource"] = "profile"
    payload["modelConfigured"] = bool(effective_model)
    payload["ready"] = bool(payload.get("configured") and effective_model)
    return payload


def get_tool_settings(
    *,
    settings_path: str | Path | None = None,
    service: Any = None,
) -> dict[str, object]:
    catalog = _tool_catalog(service)
    stored = _read_tool_settings(settings_path)
    return _tool_settings_payload(catalog, stored, settings_path=settings_path)


def update_tool_settings(
    body: Any,
    *,
    settings_path: str | Path | None = None,
    service: Any = None,
) -> dict[str, object]:
    if not isinstance(body, dict):
        raise ValueError("Request body must be a JSON object.")

    catalog = _tool_catalog(service)
    current = _read_tool_settings(settings_path)
    next_settings = _normalize_tool_settings_update(body, catalog, current)
    _save_tool_secret_updates(body)
    _write_tool_settings(settings_path, next_settings)
    catalog.invalidate()
    _reset_agent_service()
    return _tool_settings_payload(catalog, next_settings, settings_path=settings_path)


def get_codex_auth_status(*, auth_path: str | Path | None = None) -> dict[str, object]:
    return CodexAuthStore(auth_path).status().to_public_dict()


def start_codex_auth(client: CodexDeviceAuthClient | None = None) -> dict[str, object]:
    return (client or CodexDeviceAuthClient()).start().to_public_dict()


def poll_codex_auth(
    body: Any,
    *,
    auth_path: str | Path | None = None,
    client: CodexDeviceAuthClient | None = None,
) -> dict[str, object]:
    if not isinstance(body, dict):
        raise ValueError("Request body must be a JSON object.")
    device_auth_id = _required_string(body.get("deviceAuthId", body.get("device_auth_id")), "deviceAuthId")
    user_code = _required_string(body.get("userCode", body.get("user_code")), "userCode")

    result = (client or CodexDeviceAuthClient()).poll(device_auth_id=device_auth_id, user_code=user_code)
    payload = result.to_public_dict()
    if result.credentials is not None:
        store = CodexAuthStore(auth_path)
        store.write_credentials(result.credentials)
        _reset_agent_service()
        payload["auth"] = store.status().to_public_dict()
    return payload


def logout_codex_auth(*, auth_path: str | Path | None = None) -> dict[str, object]:
    store = CodexAuthStore(auth_path)
    store.clear()
    _reset_agent_service()
    return store.status().to_public_dict()


def _optional_string(value: Any, field_name: str) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string.")
    return value.strip()


def _required_string(value: Any, field_name: str) -> str:
    text = _optional_string(value, field_name)
    if not text:
        raise ValueError(f"{field_name} is required.")
    return text


def _reset_agent_service() -> None:
    from ui.backend.agent_api import set_agent_service

    set_agent_service(None)


def _tool_catalog(service: Any = None) -> ToolCatalog:
    if service is not None:
        catalog = getattr(service, "tool_catalog", None)
        if catalog is not None:
            return catalog
        return ToolCatalog(service.tool_registry)
    from ui.backend.agent_api import get_agent_service

    agent_service = get_agent_service()
    catalog = getattr(agent_service, "tool_catalog", None)
    if catalog is not None:
        return catalog
    return ToolCatalog(agent_service.tool_registry)


def _tool_settings_path(settings_path: str | Path | None = None) -> Path:
    return Path(settings_path) if settings_path is not None else DEFAULT_TOOL_SETTINGS_PATH


def _read_tool_settings(settings_path: str | Path | None = None) -> dict[str, Any]:
    path = _tool_settings_path(settings_path)
    if not path.exists():
        return _default_tool_settings()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return _default_tool_settings()
    if not isinstance(payload, dict):
        return _default_tool_settings()
    return _normalize_stored_tool_settings(payload)


def _write_tool_settings(settings_path: str | Path | None, payload: dict[str, Any]) -> None:
    atomic_write_json(_tool_settings_path(settings_path), payload)


def _tool_settings_payload(
    catalog: ToolCatalog,
    stored: dict[str, Any],
    *,
    settings_path: str | Path | None = None,
) -> dict[str, object]:
    global_access = _normalize_global_access(stored.get("globalAccess", stored.get("global_access")))
    default_write_mode = "auto" if global_access == TOOL_GLOBAL_FULL_ACCESS else "ask"
    built_in_tools: list[dict[str, object]] = []
    custom_tools: list[dict[str, object]] = []
    disabled_tools: list[str] = []
    disabled_toolsets: list[str] = []
    enabled_toolsets: list[str] = []
    tool_write_modes: dict[str, str] = {}
    native_web_search_enabled = _native_web_search_enabled(stored)
    native_web_search = _native_web_search_item(stored, enabled=native_web_search_enabled)

    for group in _settings_tool_groups(catalog):
        definitions = _group_tool_definitions(catalog, group)
        if not definitions:
            continue
        raw_tool = _stored_group_settings(group, stored)
        mutating = any(definition.mutating for definition in definitions)
        read_only = all(definition.read_only for definition in definitions) and not mutating
        risk = _group_risk(definitions)
        access = _normalize_tool_access(raw_tool.get("access"), mutating=mutating)
        enabled = _stored_group_enabled(group, stored)
        runtime_enabled = _runtime_group_enabled(group, stored, native_web_search_enabled)
        runtime_disabled_tools = _runtime_disabled_tools(group, definitions, stored, native_web_search_enabled)
        if access == "disabled":
            enabled = False
            runtime_enabled = False
            runtime_disabled_tools = [definition.name for definition in definitions]
        effective_mode = "readonly" if read_only else (
            access if access != "inherit" else default_write_mode
        )
        if not runtime_enabled:
            disabled_toolsets.append(group)
            disabled_tools.extend(definition.name for definition in definitions)
            effective_mode = "disabled"
        else:
            if runtime_disabled_tools:
                disabled_tools.extend(runtime_disabled_tools)
            if group in CUSTOM_TOOL_SETTING_GROUPS:
                enabled_toolsets.append(group)
        if runtime_enabled and group not in CUSTOM_TOOL_SETTING_GROUPS and mutating and access != "inherit":
            for definition in definitions:
                if definition.mutating:
                    tool_write_modes[definition.name] = access

        item = {
            "name": group,
            "label": _tool_label(group),
            "description": _group_description(catalog, group),
            "toolset": "custom" if group in CUSTOM_TOOL_SETTING_GROUPS else "tool_group",
            "readOnly": read_only,
            "mutating": mutating,
            "risk": risk,
            "enabled": runtime_enabled if group == "web_search" else enabled,
            "access": "readonly" if read_only and access == "inherit" else access,
            "effectiveAccess": effective_mode,
            "childCount": len(definitions),
            "availability": {},
            "metadata": {
                "toolNames": [definition.name for definition in definitions],
            },
        }
        if group in CUSTOM_TOOL_SETTING_GROUPS:
            custom_tools.append(item)
        else:
            built_in_tools.append(item)

    visible_built_in_tools = _built_in_tools_with_virtuals(built_in_tools, native_web_search)
    return {
        "globalAccess": global_access,
        "defaultWriteMode": default_write_mode,
        "builtInTools": visible_built_in_tools,
        "customTools": custom_tools,
        "tools": [*built_in_tools, *custom_tools],
        "nativeWebSearchEnabled": bool(native_web_search["enabled"]),
        "providerNativeWebSearchEnabled": bool(native_web_search["enabled"]),
        "webSearchProviders": _web_search_providers_payload(stored),
        "enabledToolsets": enabled_toolsets,
        "disabledToolsets": disabled_toolsets,
        "disabledTools": disabled_tools,
        "toolWriteModes": tool_write_modes,
        "settingsPath": str(_tool_settings_path(settings_path)),
    }


def _built_in_tools_with_virtuals(
    built_in_tools: list[dict[str, object]],
    native_web_search: dict[str, object],
) -> list[dict[str, object]]:
    ordered: list[dict[str, object]] = []
    native_inserted = False
    for item in built_in_tools:
        ordered.append(item)
        if item.get("name") == "paper_notes":
            ordered.append(native_web_search)
            native_inserted = True
    if not native_inserted:
        return [native_web_search, *built_in_tools]
    return ordered


def _default_tool_settings() -> dict[str, Any]:
    return {
        "globalAccess": TOOL_GLOBAL_FULL_ACCESS,
        "toolsets": {
            "web_search": {
                "enabled": True,
                "access": "inherit",
                "native_provider": _native_web_search_provider_config(True),
                "custom_provider": _custom_web_search_provider_config(True),
            },
        },
    }


def _normalize_stored_tool_settings(payload: dict[str, Any]) -> dict[str, Any]:
    if isinstance(payload.get("toolsets"), dict):
        return {
            "globalAccess": _normalize_global_access(payload.get("globalAccess", payload.get("global_access"))),
            "toolsets": _normalize_stored_toolsets(payload.get("toolsets"), payload),
        }
    if _has_openclaw_web_search_config(payload):
        migrated = _default_tool_settings()
        migrated["globalAccess"] = _normalize_global_access(payload.get("globalAccess", payload.get("global_access")))
        migrated["toolsets"]["web_search"].update(_provider_config_from_openclaw_tools(payload.get("tools")))
        return migrated
    if isinstance(payload.get("tools"), dict):
        return _migrate_legacy_tool_settings(payload)
    return _default_tool_settings() | {
        "globalAccess": _normalize_global_access(payload.get("globalAccess", payload.get("global_access"))),
    }


def _normalize_tool_settings_update(body: dict[str, Any], catalog: ToolCatalog, current: dict[str, Any]) -> dict[str, Any]:
    raw_tools = body.get("tools")
    provider_updates = body.get("webSearchProviders", body.get("web_search_providers"))
    if raw_tools is None:
        next_toolsets = dict(current.get("toolsets") if isinstance(current.get("toolsets"), dict) else {})
        if isinstance(provider_updates, dict):
            web_entry = dict(next_toolsets.get("web_search") if isinstance(next_toolsets.get("web_search"), dict) else {})
            existing_enabled = _bool_or_default(web_entry.get("enabled"), False)
            web_entry.update(_web_search_provider_settings_from_ui(provider_updates))
            web_entry["enabled"] = existing_enabled
            web_entry["access"] = _normalize_tool_access(web_entry.get("access"), mutating=True)
            next_toolsets["web_search"] = web_entry
        return {
            "globalAccess": _normalize_global_access(body.get("globalAccess", body.get("global_access", current["globalAccess"]))),
            "toolsets": next_toolsets,
        }

    raw_by_name = _tool_entries_by_name(raw_tools)
    toolsets: dict[str, dict[str, object]] = {}
    for group in _settings_tool_groups(catalog):
        definitions = _group_tool_definitions(catalog, group)
        if not definitions:
            continue
        raw = _raw_group_settings(group, definitions, raw_by_name)
        mutating = any(definition.mutating for definition in definitions)
        read_only = all(definition.read_only for definition in definitions) and not mutating
        access = _normalize_tool_access(raw.get("access"), mutating=mutating)
        enabled = _bool_or_default(raw.get("enabled"), group not in CUSTOM_TOOL_SETTING_GROUPS)
        if access == "disabled":
            enabled = False
        toolset_entry: dict[str, object] = {
            "enabled": enabled,
            "access": "inherit" if read_only and access == "readonly" else access,
        }
        if group == "web_search":
            toolset_entry["native_provider"] = _default_native_web_search_provider_config()
            toolset_entry["custom_provider"] = _custom_web_search_provider_config(enabled)
        toolsets[group] = toolset_entry

    provider_native_raw = raw_by_name.get(NATIVE_WEB_SEARCH, raw_by_name.get(LEGACY_NATIVE_WEB_SEARCH))
    provider_native_enabled = _bool_or_default(
        provider_native_raw.get("enabled") if isinstance(provider_native_raw, dict) else None,
        _native_web_search_enabled(current),
    )
    web_search_entry = toolsets.setdefault("web_search", {"enabled": False, "access": "inherit"})
    if isinstance(web_search_entry, dict):
        web_search_enabled = _bool_or_default(web_search_entry.get("enabled"), False) or provider_native_enabled
        web_search_entry["enabled"] = web_search_enabled
        web_search_entry["native_provider"] = _native_web_search_provider_config(provider_native_enabled)
        web_search_entry["custom_provider"] = _custom_web_search_provider_config(
            _bool_or_default(web_search_entry.get("enabled"), False) and not provider_native_enabled
        )
        if isinstance(provider_updates, dict):
            requested_enabled = _bool_or_default(web_search_entry.get("enabled"), False)
            web_search_entry.update(_web_search_provider_settings_from_ui(provider_updates))
            web_search_entry["enabled"] = requested_enabled
    return {
        "globalAccess": _normalize_global_access(body.get("globalAccess", body.get("global_access", current["globalAccess"]))),
        "toolsets": toolsets,
    }


def _tool_entries_by_name(raw_tools: Any) -> dict[str, Any]:
    raw_by_name: dict[str, Any] = {}
    if isinstance(raw_tools, dict):
        raw_by_name = raw_tools
    elif isinstance(raw_tools, list):
        for item in raw_tools:
            if isinstance(item, dict):
                name = _optional_string(item.get("name"), "name")
                if name:
                    raw_by_name[name] = item
    return raw_by_name


def _save_tool_secret_updates(body: dict[str, Any]) -> None:
    web_search = body.get("webSearchProviders", body.get("web_search_providers"))
    if not isinstance(web_search, dict):
        return
    tavily_key = _optional_string(web_search.get("tavilyApiKey", web_search.get("tavily_api_key")), "tavilyApiKey")
    brave_key = _optional_string(
        web_search.get("braveSearchApiKey", web_search.get("brave_search_api_key")),
        "braveSearchApiKey",
    )
    updates: dict[str, str] = {}
    if tavily_key:
        updates[TAVILY_API_KEY] = tavily_key
    if brave_key:
        updates[BRAVE_SEARCH_API_KEY] = brave_key
    if updates:
        write_env_values(default_secrets_path(), updates)


def _web_search_provider_settings_from_ui(raw: dict[str, Any]) -> dict[str, Any]:
    mode = _optional_string(raw.get("mode"), "mode").lower().replace("-", "_")
    if mode not in {"native", "tavily", "native_tavily"}:
        mode = ""
    native_enabled = mode in {"native", "native_tavily"}
    tavily_enabled = mode in {"tavily", "native_tavily"}
    native_raw = raw.get("native_provider", raw.get("nativeProvider"))
    custom_raw = raw.get("custom_provider", raw.get("customProvider"))
    if not mode:
        native = _normalize_native_web_search_provider_config(native_raw)
        custom = _normalize_custom_web_search_provider_config(custom_raw)
    else:
        native = _native_web_search_provider_config(native_enabled)
        custom = _custom_web_search_provider_config(tavily_enabled)
    return {
        "enabled": bool(native_enabled or tavily_enabled or _any_provider_enabled(native, custom)),
        "native_provider": native,
        "custom_provider": custom,
    }


def _normalize_stored_toolsets(raw: Any, payload: dict[str, Any] | None = None) -> dict[str, dict[str, object]]:
    if not isinstance(raw, dict):
        return {}
    normalized: dict[str, dict[str, object]] = {}
    for name, entry in raw.items():
        if not isinstance(name, str) or not isinstance(entry, dict):
            continue
        normalized_entry: dict[str, object] = {
            "enabled": _bool_or_default(entry.get("enabled"), name not in CUSTOM_TOOL_SETTING_GROUPS),
            "access": _normalize_tool_access(entry.get("access"), mutating=True),
        }
        if name == "web_search":
            normalized_entry.update(_normalize_web_search_provider_configs(entry))
        normalized[name] = normalized_entry
    if "web_search" not in normalized:
        provider = _provider_config_from_openclaw_tools(payload.get("tools")) if payload is not None else {}
        normalized["web_search"] = {
            "enabled": True,
            "access": "inherit",
            "native_provider": provider.get("native_provider", _native_web_search_provider_config(True)),
            "custom_provider": provider.get("custom_provider", _custom_web_search_provider_config(True)),
        }
    return normalized


def _default_native_web_search_provider_config() -> dict[str, dict[str, object]]:
    return _native_web_search_provider_config(False)


def _default_custom_web_search_provider_config() -> dict[str, dict[str, object]]:
    return _custom_web_search_provider_config(False)


def _native_web_search_provider_config(enabled: bool) -> dict[str, dict[str, object]]:
    return {
        "openaiCodex": {"enabled": enabled},
        "openaiAPIKey": {"enabled": enabled},
    }


def _custom_web_search_provider_config(enabled: bool) -> dict[str, dict[str, object]]:
    return {
        "Tavily": {"enabled": enabled},
        "Brave": {"enabled": False},
    }


def _normalize_web_search_provider_configs(entry: dict[str, Any]) -> dict[str, dict[str, dict[str, object]]]:
    native_raw = entry.get("native_provider", entry.get("nativeProvider"))
    custom_raw = entry.get("custom_provider", entry.get("customProvider"))
    legacy_raw = entry.get("provider")
    if native_raw is None and isinstance(legacy_raw, dict):
        native_raw = legacy_raw
    return {
        "native_provider": _normalize_native_web_search_provider_config(native_raw),
        "custom_provider": _normalize_custom_web_search_provider_config(custom_raw),
    }


def _normalize_native_web_search_provider_config(raw: Any) -> dict[str, dict[str, object]]:
    default = _default_native_web_search_provider_config()
    if not isinstance(raw, dict):
        return default
    openai_codex = raw.get("openaiCodex", raw.get("openai_codex"))
    openai_api_key = raw.get("openaiAPIKey", raw.get("openai_api_key"))
    if not isinstance(openai_codex, dict):
        openai_codex = {}
    if not isinstance(openai_api_key, dict):
        openai_api_key = {}
    return {
        "openaiCodex": {
            "enabled": _bool_or_default(openai_codex.get("enabled"), False),
            **_optional_openai_codex_search_fields(openai_codex),
        },
        "openaiAPIKey": {
            "enabled": _bool_or_default(openai_api_key.get("enabled"), False),
        },
    }


def _normalize_custom_web_search_provider_config(raw: Any) -> dict[str, dict[str, object]]:
    default = _default_custom_web_search_provider_config()
    if not isinstance(raw, dict):
        return default
    tavily = raw.get("Tavily", raw.get("tavily"))
    if not isinstance(tavily, dict):
        tavily = {}
    brave = raw.get("Brave", raw.get("brave"))
    if not isinstance(brave, dict):
        brave = {}
    return {
        "Tavily": {"enabled": _bool_or_default(tavily.get("enabled"), False)},
        "Brave": {"enabled": _bool_or_default(brave.get("enabled"), False)},
    }


def _any_provider_enabled(native: dict[str, Any], custom: dict[str, Any]) -> bool:
    for provider_group in (native, custom):
        for value in provider_group.values():
            if isinstance(value, dict) and _bool_or_default(value.get("enabled"), False):
                return True
    return False


def _web_search_provider_mode(stored: dict[str, Any]) -> str:
    web_search = _stored_group_settings("web_search", stored)
    native = web_search.get("native_provider")
    custom = web_search.get("custom_provider")
    native_enabled = _any_provider_enabled(native if isinstance(native, dict) else {}, {})
    custom_enabled = _any_provider_enabled({}, custom if isinstance(custom, dict) else {})
    if native_enabled and custom_enabled:
        return "native_tavily"
    if native_enabled:
        return "native"
    if custom_enabled:
        return "tavily"
    return ""


def _custom_web_search_provider_name(custom: dict[str, Any]) -> str:
    tavily = custom.get("Tavily", custom.get("tavily"))
    if isinstance(tavily, dict) and _bool_or_default(tavily.get("enabled"), False):
        return "Tavily"
    brave = custom.get("Brave", custom.get("brave"))
    if isinstance(brave, dict) and _bool_or_default(brave.get("enabled"), False):
        return "Brave"
    return "Tavily"


def _web_search_providers_payload(stored: dict[str, Any]) -> dict[str, Any]:
    web_search = _stored_group_settings("web_search", stored)
    native = web_search.get("native_provider")
    custom = web_search.get("custom_provider")
    tavily_key = resolve_tavily_api_key()
    brave_key = resolve_brave_search_api_key()
    return {
        "mode": _web_search_provider_mode(stored),
        "native_provider": native if isinstance(native, dict) else _default_native_web_search_provider_config(),
        "custom_provider": custom if isinstance(custom, dict) else _default_custom_web_search_provider_config(),
        "customProviderName": _custom_web_search_provider_name(custom if isinstance(custom, dict) else {}),
        "tavilyKeyConfigured": tavily_key.configured,
        "tavilyKeySource": tavily_key.source,
        "braveSearchKeyConfigured": brave_key.configured,
        "braveSearchKeySource": brave_key.source,
    }


def _provider_config_from_openclaw_tools(raw: Any) -> dict[str, dict[str, dict[str, object]]]:
    default = {
        "native_provider": _default_native_web_search_provider_config(),
        "custom_provider": _default_custom_web_search_provider_config(),
    }
    if not isinstance(raw, dict):
        return default
    web = raw.get("web")
    if not isinstance(web, dict):
        return default
    search = web.get("search")
    if not isinstance(search, dict):
        return default
    openai_codex = search.get("openaiCodex", search.get("openai_codex"))
    if not isinstance(openai_codex, dict):
        openai_codex = {}
    native_enabled = _bool_or_default(openai_codex.get("enabled"), False)
    return {
        "native_provider": {
            "openaiCodex": {
                "enabled": native_enabled,
                **_optional_openai_codex_search_fields(openai_codex),
            },
            "openaiAPIKey": {"enabled": native_enabled},
        },
        "custom_provider": _default_custom_web_search_provider_config(),
    }


def _optional_openai_codex_search_fields(raw: dict[str, Any]) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    if isinstance(raw.get("allowedDomains"), list):
        fields["allowedDomains"] = [str(value) for value in raw["allowedDomains"] if str(value).strip()]
    if isinstance(raw.get("contextSize"), str) and raw["contextSize"].strip():
        fields["contextSize"] = raw["contextSize"].strip()
    if isinstance(raw.get("userLocation"), dict):
        fields["userLocation"] = raw["userLocation"]
    return fields


def _has_openclaw_web_search_config(payload: dict[str, Any]) -> bool:
    tools = payload.get("tools")
    if not isinstance(tools, dict):
        return False
    web = tools.get("web")
    return isinstance(web, dict) and isinstance(web.get("search"), dict)


def _migrate_legacy_tool_settings(payload: dict[str, Any]) -> dict[str, Any]:
    raw_tools = payload.get("tools") if isinstance(payload.get("tools"), dict) else {}
    toolsets: dict[str, dict[str, object]] = {}
    for group in TOOL_SETTING_GROUPS:
        raw = raw_tools.get(group)
        if isinstance(raw, dict):
            toolsets[group] = {
                "enabled": _bool_or_default(raw.get("enabled"), group not in CUSTOM_TOOL_SETTING_GROUPS),
                "access": _normalize_tool_access(raw.get("access"), mutating=True),
            }
    provider_raw = raw_tools.get(NATIVE_WEB_SEARCH, raw_tools.get(LEGACY_NATIVE_WEB_SEARCH))
    provider_native_enabled = _bool_or_default(
        provider_raw.get("enabled") if isinstance(provider_raw, dict) else None,
        False,
    )
    local_search_enabled = _bool_or_default(
        toolsets.get("web_search", {}).get("enabled") if isinstance(toolsets.get("web_search"), dict) else None,
        False,
    )
    native_provider = _native_web_search_provider_config(provider_native_enabled)
    return {
        "globalAccess": _normalize_global_access(payload.get("globalAccess", payload.get("global_access"))),
        "toolsets": {
            **toolsets,
            "web_search": {
                "enabled": bool(local_search_enabled or provider_native_enabled),
                "access": toolsets.get("web_search", {}).get("access", "inherit") if isinstance(toolsets.get("web_search"), dict) else "inherit",
                "native_provider": native_provider,
                "custom_provider": _custom_web_search_provider_config(local_search_enabled and not provider_native_enabled),
            },
        },
    }


def _int_or_default(value: Any, default: int) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return default
    return default


def _settings_tool_groups(catalog: ToolCatalog) -> list[str]:
    groups: list[str] = []
    described = {group.name for group in catalog.describe_groups()}
    for group in TOOL_SETTING_GROUPS:
        if group in described and _group_tool_definitions(catalog, group):
            groups.append(group)
    return groups


def _group_tool_definitions(catalog: ToolCatalog, group: str) -> list[Any]:
    registry = catalog.registry
    groups = {definition.name: definition for definition in catalog.describe_groups()}
    definition = groups.get(group)
    candidate_names = definition.tools if definition is not None else tuple(registry.tool_names_for_toolset(group))
    definitions = [
        tool_definition
        for name in candidate_names
        if (tool_definition := registry.get(name)) is not None
    ]
    if definitions:
        return definitions
    return [
        tool_definition
        for name in registry.tool_names_for_toolset(group)
        if (tool_definition := registry.get(name)) is not None
    ]


def _raw_group_settings(group: str, definitions: list[Any], stored_tools: dict[str, Any]) -> dict[str, Any]:
    direct = stored_tools.get(group)
    if isinstance(direct, dict):
        return direct

    child_entries = [
        entry
        for definition in definitions
        if isinstance((entry := stored_tools.get(definition.name)), dict)
    ]
    if not child_entries:
        return {}

    enabled = any(_bool_or_default(entry.get("enabled"), True) for entry in child_entries)
    access = "inherit"
    for entry in child_entries:
        candidate = _normalize_tool_access(entry.get("access"), mutating=True)
        if candidate != "inherit":
            access = candidate
            break
    return {"enabled": enabled, "access": access}


def _stored_group_settings(group: str, stored: dict[str, Any]) -> dict[str, Any]:
    toolsets = stored.get("toolsets")
    if isinstance(toolsets, dict) and isinstance(toolsets.get(group), dict):
        return dict(toolsets[group])
    return {"enabled": group not in CUSTOM_TOOL_SETTING_GROUPS, "access": "inherit"}


def _stored_group_enabled(group: str, stored: dict[str, Any]) -> bool:
    return _bool_or_default(_stored_group_settings(group, stored).get("enabled"), group not in CUSTOM_TOOL_SETTING_GROUPS)


def _runtime_group_enabled(group: str, stored: dict[str, Any], native_web_search_enabled: bool) -> bool:
    return _stored_group_enabled(group, stored)


def _runtime_disabled_tools(
    group: str,
    definitions: list[Any],
    stored: dict[str, Any],
    native_web_search_enabled: bool,
) -> list[str]:
    if group != "web_search":
        return []
    if not _stored_group_enabled(group, stored):
        return [definition.name for definition in definitions]
    if not _custom_web_search_enabled(stored):
        return [definition.name for definition in definitions if definition.name == "web_search"]
    return []


def _group_description(catalog: ToolCatalog, group: str) -> str:
    descriptions = {
        "paper_notes": (
            "Allow the agent to search your library, read PDF text, render PDF pages, extract PDF images, inspect note HTML "
            "and annotations, preview changes, and write safe note sections, metadata, "
            "or annotation comments."
        ),
        "persistent_memory": (
            "Allow the agent to read and update long-term user or project facts that should "
            "carry across chat sessions."
        ),
        "session_search": (
            "Allow the agent to search previous chat transcripts for earlier decisions, "
            "task history, and context."
        ),
        "todo": (
            "Allow the agent to maintain a session task list while it works through "
            "multi-step note-writing requests."
        ),
        "skills": (
            "Allow the agent to discover local task skills and load their instructions, "
            "references, templates, and scripts only when needed."
        ),
        "code_execution": (
            "Allow the agent to run local Python in a temporary directory with light process guardrails "
            "and read-only Paper Notes tool callbacks. Approval follows the current tool permission mode; "
            "this is not a strong isolation sandbox."
        ),
        "web_search": (
            "Allow the agent to call configured custom web search providers, fetch specific public URLs, "
            "and return answers with sources. If more than one provider is enabled, Tavily is used before Brave Search."
        ),
    }
    groups = {definition.name: definition for definition in catalog.describe_groups()}
    group_definition = groups.get(group)
    return descriptions.get(group) or (
        group_definition.description if group_definition is not None else f"{_tool_label(group)} tools."
    )


def _group_risk(definitions: list[Any]) -> str:
    risks = {definition.risk for definition in definitions}
    if "destructive" in risks:
        return "destructive"
    if "write" in risks or any(definition.mutating for definition in definitions):
        return "write"
    return "read"


def _normalize_global_access(value: Any) -> str:
    normalized = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if normalized in {"full_access", "full", "auto"}:
        return TOOL_GLOBAL_FULL_ACCESS
    return TOOL_GLOBAL_DEFAULT


def _normalize_tool_access(value: Any, *, mutating: bool) -> str:
    normalized = str(value or "inherit").strip().lower().replace("-", "_").replace(" ", "_")
    if normalized == "default":
        normalized = "inherit"
    if normalized not in TOOL_ACCESS_VALUES:
        normalized = "inherit"
    if not mutating and normalized not in {"inherit", "readonly", "disabled"}:
        return "inherit"
    return normalized


def _bool_or_default(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return default


def _tool_label(name: str) -> str:
    labels = {
        NATIVE_WEB_SEARCH: "Native Web Search",
        LEGACY_NATIVE_WEB_SEARCH: "Native Web Search",
        "code_execution": "Code Execution",
        "execute_code": "Execute Code",
        "web_search": "Custom Web Search",
        "web_fetch": "Web Fetch",
    }
    if name in labels:
        return labels[name]
    words = str(name or "").replace(".", "_").split("_")
    return " ".join(word.capitalize() for word in words if word)


def _native_web_search_enabled(stored: dict[str, Any]) -> bool:
    if not _stored_group_enabled("web_search", stored):
        return False
    toolsets = stored.get("toolsets")
    if not isinstance(toolsets, dict):
        return False
    web_search = toolsets.get("web_search")
    if not isinstance(web_search, dict):
        return False
    native_provider = web_search.get("native_provider", web_search.get("nativeProvider"))
    if not isinstance(native_provider, dict):
        return False
    active_provider = _active_ai_provider()
    profile = get_provider_profile(active_provider)
    if profile is not None and not profile.default_capabilities.supports_web_search:
        return False
    openai_codex = native_provider.get("openaiCodex", native_provider.get("openai_codex"))
    openai_api_key = native_provider.get("openaiAPIKey", native_provider.get("openai_api_key"))
    if not isinstance(openai_codex, dict):
        openai_codex = {}
    if not isinstance(openai_api_key, dict):
        openai_api_key = {}
    if active_provider == CODEX_PROVIDER:
        return _bool_or_default(openai_codex.get("enabled"), False)
    if active_provider == OPENAI_PROVIDER:
        return _bool_or_default(openai_api_key.get("enabled"), False)
    return False


def _custom_web_search_enabled(stored: dict[str, Any]) -> bool:
    toolsets = stored.get("toolsets")
    if not isinstance(toolsets, dict):
        return False
    web_search = toolsets.get("web_search")
    if not isinstance(web_search, dict):
        return False
    custom_provider = web_search.get("custom_provider", web_search.get("customProvider"))
    if not isinstance(custom_provider, dict):
        return False
    return _any_provider_enabled({}, custom_provider)


def _active_ai_provider() -> str:
    try:
        return resolve_ai_provider().value
    except Exception:
        return OPENAI_PROVIDER


def _native_web_search_item(stored: dict[str, Any], *, enabled: bool | None = None) -> dict[str, object]:
    if enabled is None:
        enabled = _native_web_search_enabled(stored)
    return {
        "name": NATIVE_WEB_SEARCH,
        "label": _tool_label(NATIVE_WEB_SEARCH),
        "description": (
            "Allow supported model providers to use their native web_search tool "
            "with provider citations and sources."
        ),
        "toolset": "built_in",
        "readOnly": True,
        "mutating": False,
        "risk": "read",
        "enabled": enabled,
        "access": "readonly",
        "effectiveAccess": "readonly" if enabled else "disabled",
        "childCount": 1,
        "availability": {},
        "metadata": {"toolNames": ["native_web_search"], "providerNative": True},
    }
