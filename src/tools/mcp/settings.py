from __future__ import annotations

import json
import os
import re
import shlex
import hashlib
from pathlib import Path
from typing import Any
from uuid import uuid4

from app_config.secrets import LOCAL_STATE_DIR, default_env_paths, default_secrets_path, parse_env_file, write_env_values
from app_infra.storage import atomic_write_json

__all__ = [
    "mcp_runtime_config",
    "mcp_secrets_path",
    "normalize_mcp_server_config",
    "normalize_mcp_settings_update",
    "public_mcp_settings",
    "read_mcp_settings",
    "write_mcp_settings",
]

DEFAULT_MCP_SETTINGS_PATH = LOCAL_STATE_DIR / "mcp-servers.json"
DEFAULT_TOOL_TIMEOUT_SECONDS = 120
DEFAULT_CONNECT_TIMEOUT_SECONDS = 10
MCP_TRANSPORTS = frozenset({"stdio", "http"})
_SERVER_ID_RE = re.compile(r"[^A-Za-z0-9_]+")
_ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SECRET_REF_PREFIX = "paper-notes-secret:"


def mcp_settings_path(settings_path: str | Path | None = None) -> Path:
    return Path(settings_path).expanduser() if settings_path is not None else DEFAULT_MCP_SETTINGS_PATH


def mcp_secrets_path(settings_path: str | Path | None = None) -> Path:
    if settings_path is None:
        return default_secrets_path()
    return mcp_settings_path(settings_path).with_name("secrets.env")


def read_mcp_settings(settings_path: str | Path | None = None) -> dict[str, Any]:
    path = mcp_settings_path(settings_path)
    if not path.exists():
        return {"servers": []}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"servers": []}
    if not isinstance(payload, dict):
        return {"servers": []}
    servers = normalize_mcp_servers(payload.get("servers"))
    return {"servers": _resolve_mcp_secret_refs(servers, settings_path=settings_path)}


def write_mcp_settings(payload: dict[str, Any], settings_path: str | Path | None = None) -> None:
    path = mcp_settings_path(settings_path)
    servers = normalize_mcp_servers(payload.get("servers"))
    atomic_write_json(path, {"servers": _externalize_mcp_secrets(servers, settings_path=settings_path)})
    _secure_settings_path(path)


def normalize_mcp_settings_update(
    body: Any,
    *,
    current: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not isinstance(body, dict):
        raise ValueError("Request body must be a JSON object.")
    existing = {
        str(server.get("id") or ""): server
        for server in normalize_mcp_servers((current or {}).get("servers"))
        if str(server.get("id") or "")
    }
    return {"servers": normalize_mcp_servers(body.get("servers"), existing_by_id=existing, strict=True)}


def normalize_mcp_server_config(
    body: Any,
    *,
    existing: dict[str, Any] | None = None,
    strict: bool = True,
) -> dict[str, Any]:
    if not isinstance(body, dict):
        raise ValueError("MCP server config must be an object.")

    server_id = _optional_text(body.get("id"))
    name = _optional_text(body.get("name")) or server_id
    if not name:
        raise ValueError("MCP server name is required.")
    if not server_id:
        server_id = _server_id_from_name(name)

    transport = _optional_text(body.get("transport")).lower() or _infer_transport(body)
    if transport not in MCP_TRANSPORTS:
        raise ValueError("MCP transport must be 'stdio' or 'http'.")

    existing = existing or {}
    env = _secret_mapping(body.get("env"), existing.get("env"))
    headers = _secret_mapping(body.get("headers"), existing.get("headers"), validate_env_names=False)
    bearer_token_env_var = _env_var_name(body.get("bearerTokenEnvVar", body.get("bearer_token_env_var")))
    header_env_vars = _env_ref_mapping(
        body.get(
            "headerEnvVars",
            body.get("header_env_vars", body.get("headersFromEnv", body.get("headers_from_env"))),
        )
    )
    command = _optional_text(body.get("command"))
    args = _string_list(body.get("args"))
    url = _optional_text(body.get("url"))
    include_tools = _filter_list(body.get("includeTools", body.get("include_tools")))
    exclude_tools = _filter_list(body.get("excludeTools", body.get("exclude_tools")))

    if strict and transport == "stdio" and not command:
        raise ValueError("MCP stdio servers require a command.")
    if strict and transport == "http" and not url:
        raise ValueError("MCP HTTP servers require a URL.")

    return {
        "id": server_id,
        "name": name,
        "enabled": _bool_or_default(body.get("enabled"), True),
        "transport": transport,
        "command": command,
        "args": args,
        "env": env,
        "url": url,
        "headers": headers,
        "bearerTokenEnvVar": bearer_token_env_var,
        "headerEnvVars": header_env_vars,
        "includeTools": include_tools,
        "excludeTools": exclude_tools,
        "timeoutSeconds": _int_or_default(body.get("timeoutSeconds", body.get("timeout_seconds")), DEFAULT_TOOL_TIMEOUT_SECONDS),
        "connectTimeoutSeconds": _int_or_default(
            body.get("connectTimeoutSeconds", body.get("connect_timeout_seconds")),
            DEFAULT_CONNECT_TIMEOUT_SECONDS,
        ),
    }


def normalize_mcp_servers(
    raw_servers: Any,
    *,
    existing_by_id: dict[str, dict[str, Any]] | None = None,
    strict: bool = False,
) -> list[dict[str, Any]]:
    if not isinstance(raw_servers, list):
        return []
    existing_by_id = existing_by_id or {}
    seen: set[str] = set()
    servers: list[dict[str, Any]] = []
    for raw in raw_servers:
        if not isinstance(raw, dict):
            continue
        existing = existing_by_id.get(str(raw.get("id") or ""))
        server = normalize_mcp_server_config(raw, existing=existing, strict=strict)
        base_id = server["id"]
        if base_id in seen:
            suffix = 2
            while f"{base_id}_{suffix}" in seen:
                suffix += 1
            server["id"] = f"{base_id}_{suffix}"
        seen.add(server["id"])
        servers.append(server)
    return servers


def mcp_runtime_config(server: dict[str, Any]) -> dict[str, Any]:
    runtime: dict[str, Any] = {
        "timeout": _int_or_default(server.get("timeoutSeconds"), DEFAULT_TOOL_TIMEOUT_SECONDS),
        "connect_timeout": _int_or_default(server.get("connectTimeoutSeconds"), DEFAULT_CONNECT_TIMEOUT_SECONDS),
    }
    if server.get("transport") == "http":
        runtime["url"] = str(server.get("url") or "")
        runtime["headers"] = _resolve_http_headers(server)
    else:
        runtime["command"] = str(server.get("command") or "")
        runtime["args"] = list(server.get("args") or [])
        runtime["env"] = dict(server.get("env") or {})
    return runtime


def public_mcp_settings(
    settings: dict[str, Any],
    *,
    statuses: dict[str, dict[str, Any]] | None = None,
    settings_path: str | Path | None = None,
) -> dict[str, Any]:
    statuses = statuses or {}
    servers = []
    for server in normalize_mcp_servers(settings.get("servers")):
        status = statuses.get(server["id"], {})
        public = {
            **server,
            "env": _redacted_mapping(server.get("env")),
            "headers": _redacted_mapping(server.get("headers")),
            "bearerTokenEnvVar": str(server.get("bearerTokenEnvVar") or ""),
            "headerEnvVars": _plain_mapping_entries(server.get("headerEnvVars")),
            "status": {
                "connected": bool(status.get("connected")),
                "error": str(status.get("error") or ""),
                "toolCount": int(status.get("toolCount") or len(status.get("tools") or [])),
                "state": str(status.get("state") or ""),
                "failureCount": int(status.get("failureCount") or 0),
                "nextRetryAt": status.get("nextRetryAt"),
                "circuitOpen": bool(status.get("circuitOpen")),
                "securityWarnings": list(status.get("securityWarnings") or []),
            },
            "tools": list(status.get("tools") or []),
        }
        servers.append(public)
    return {
        "success": True,
        "servers": servers,
        "settingsPath": str(mcp_settings_path(settings_path)),
    }


def _optional_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _infer_transport(body: dict[str, Any]) -> str:
    return "http" if _optional_text(body.get("url")) else "stdio"


def _server_id_from_name(name: str) -> str:
    base = _SERVER_ID_RE.sub("_", str(name or "").strip().lower()).strip("_")
    return base or f"server_{uuid4().hex[:8]}"


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        try:
            return shlex.split(text)
        except ValueError:
            return [line.strip() for line in text.splitlines() if line.strip()]
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _filter_list(value: Any) -> list[str]:
    raw_items: list[Any] = []
    if isinstance(value, str):
        raw_items = re.split(r"[\n,]", value)
    elif isinstance(value, list):
        for item in value:
            if isinstance(item, str):
                raw_items.extend(re.split(r"[\n,]", item))
            else:
                raw_items.append(item)
    else:
        return []

    seen: set[str] = set()
    result: list[str] = []
    for item in raw_items:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _env_var_name(value: Any) -> str:
    name = _optional_text(value)
    if not name:
        return ""
    if not _ENV_NAME_RE.match(name):
        raise ValueError(f"Invalid environment variable name: {name}")
    return name


def _env_ref_mapping(value: Any) -> dict[str, str]:
    items: list[tuple[str, Any]] = []
    if isinstance(value, dict):
        items = [(str(key), raw_value) for key, raw_value in value.items()]
    elif isinstance(value, list):
        for entry in value:
            if not isinstance(entry, dict):
                continue
            key = str(entry.get("name", entry.get("key", entry.get("header", ""))))
            env_value = entry.get(
                "value",
                entry.get("envVar", entry.get("env_var", entry.get("variable", entry.get("env", "")))),
            )
            items.append((key, env_value))
    else:
        return {}

    result: dict[str, str] = {}
    for raw_key, raw_value in items:
        key = str(raw_key or "").strip()
        if not key:
            continue
        env_name = _env_var_name(raw_value)
        if env_name:
            result[key] = env_name
    return result


def _plain_mapping_entries(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, dict):
        return []
    return [
        {"name": str(key), "value": str(item)}
        for key, item in value.items()
        if str(key).strip() and str(item).strip()
    ]


def _resolve_http_headers(server: dict[str, Any]) -> dict[str, str]:
    headers = {str(key): str(value) for key, value in dict(server.get("headers") or {}).items()}
    for header_name, env_name in dict(server.get("headerEnvVars") or {}).items():
        headers[str(header_name)] = _required_env_value(
            env_name,
            f"MCP header environment variable {env_name} for {header_name} is not set.",
        )
    bearer_env = str(server.get("bearerTokenEnvVar") or "").strip()
    if bearer_env:
        token = _required_env_value(bearer_env, f"MCP bearer token environment variable {bearer_env} is not set.")
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _required_env_value(name: Any, missing_message: str) -> str:
    env_name = _env_var_name(name)
    value = os.environ.get(env_name, "").strip()
    if value:
        return value
    for path in (default_secrets_path(), *default_env_paths()):
        value = parse_env_file(path).get(env_name, "").strip()
        if value:
            return value
    raise ValueError(missing_message)


def _secret_mapping(
    value: Any,
    existing: Any = None,
    *,
    validate_env_names: bool = True,
) -> dict[str, str]:
    existing_map = existing if isinstance(existing, dict) else {}
    items: list[tuple[str, Any]] = []
    if isinstance(value, dict):
        items = [(str(key), raw_value) for key, raw_value in value.items()]
    elif isinstance(value, list):
        for entry in value:
            if not isinstance(entry, dict):
                continue
            key = str(entry.get("name", entry.get("key", "")))
            items.append((key, entry))
    else:
        return {}

    result: dict[str, str] = {}
    for raw_key, raw_value in items:
        key = raw_key.strip()
        if not key:
            continue
        if validate_env_names and not _ENV_NAME_RE.match(key):
            raise ValueError(f"Invalid environment variable name: {key}")
        if isinstance(raw_value, dict):
            explicit = raw_value.get("value")
            configured = _bool_or_default(raw_value.get("configured"), False)
            if explicit is not None and str(explicit) != "":
                result[key] = str(explicit)
            elif configured and key in existing_map:
                result[key] = str(existing_map[key])
            continue
        if raw_value is not None and str(raw_value) != "":
            result[key] = str(raw_value)
    return result


def _redacted_mapping(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, dict):
        return []
    return [
        {"name": str(key), "configured": bool(str(secret))}
        for key, secret in sorted(value.items())
        if str(key).strip()
    ]


def _resolve_mcp_secret_refs(
    servers: list[dict[str, Any]],
    *,
    settings_path: str | Path | None = None,
) -> list[dict[str, Any]]:
    secrets = parse_env_file(mcp_secrets_path(settings_path))
    resolved: list[dict[str, Any]] = []
    for server in servers:
        item = dict(server)
        item["env"] = _resolve_secret_mapping(item.get("env"), secrets)
        item["headers"] = _resolve_secret_mapping(item.get("headers"), secrets)
        resolved.append(item)
    return resolved


def _resolve_secret_mapping(value: Any, secrets: dict[str, str]) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, str] = {}
    for key, raw_value in value.items():
        name = _secret_ref_name(raw_value)
        if name:
            secret = secrets.get(name)
            if secret is not None:
                result[str(key)] = secret
            continue
        if raw_value is not None and str(raw_value) != "":
            result[str(key)] = str(raw_value)
    return result


def _externalize_mcp_secrets(
    servers: list[dict[str, Any]],
    *,
    settings_path: str | Path | None = None,
) -> list[dict[str, Any]]:
    path = mcp_settings_path(settings_path)
    old_refs = _stored_mcp_secret_refs(path)
    new_refs: set[str] = set()
    updates: dict[str, str | None] = {}
    stored_servers: list[dict[str, Any]] = []

    for server in servers:
        item = dict(server)
        for field, kind in (("env", "ENV"), ("headers", "HEADER")):
            mapping = server.get(field)
            stored_mapping: dict[str, str] = {}
            if isinstance(mapping, dict):
                for key, value in mapping.items():
                    text = str(value)
                    if not str(key).strip() or text == "":
                        continue
                    ref_name = _secret_ref_name(text) or _mcp_secret_name(str(server.get("id") or ""), kind, str(key))
                    stored_mapping[str(key)] = _secret_ref(ref_name)
                    new_refs.add(ref_name)
                    if not _secret_ref_name(text):
                        updates[ref_name] = text
            item[field] = stored_mapping
        stored_servers.append(item)

    for ref_name in sorted(old_refs - new_refs):
        updates[ref_name] = None
    if updates:
        write_env_values(mcp_secrets_path(settings_path), updates)
    return stored_servers


def _stored_mcp_secret_refs(path: Path) -> set[str]:
    if not path.exists():
        return set()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return set()
    if not isinstance(payload, dict):
        return set()
    refs: set[str] = set()
    for raw_server in payload.get("servers") or []:
        if not isinstance(raw_server, dict):
            continue
        for field in ("env", "headers"):
            mapping = raw_server.get(field)
            if not isinstance(mapping, dict):
                continue
            for raw_value in mapping.values():
                ref_name = _secret_ref_name(raw_value)
                if ref_name:
                    refs.add(ref_name)
    return refs


def _mcp_secret_name(server_id: str, kind: str, key: str) -> str:
    seed = f"{server_id}:{kind}:{key}"
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:8].upper()
    return f"PAPER_NOTES_MCP_{_secret_name_part(server_id)}_{kind}_{_secret_name_part(key)}_{digest}"


def _secret_name_part(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9]+", "_", str(value or "").upper()).strip("_")
    return text or "VALUE"


def _secret_ref(name: str) -> str:
    return f"{_SECRET_REF_PREFIX}{name}"


def _secret_ref_name(value: Any) -> str:
    text = str(value or "")
    if not text.startswith(_SECRET_REF_PREFIX):
        return ""
    name = text[len(_SECRET_REF_PREFIX):].strip()
    return name if _ENV_NAME_RE.match(name) else ""


def _int_or_default(value: Any, default: int) -> int:
    if isinstance(value, bool):
        return default
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(1, number)


def _bool_or_default(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    return default


def _secure_settings_path(path: Path) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(path.parent, 0o700)
    except OSError:
        pass
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass

