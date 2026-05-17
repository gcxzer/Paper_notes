from __future__ import annotations

import json
import os
import re
import shlex
from pathlib import Path
from typing import Any
from uuid import uuid4

from app_config.secrets import LOCAL_STATE_DIR
from app_infra.storage import atomic_write_json


DEFAULT_MCP_SETTINGS_PATH = LOCAL_STATE_DIR / "mcp-servers.json"
DEFAULT_TOOL_TIMEOUT_SECONDS = 120
DEFAULT_CONNECT_TIMEOUT_SECONDS = 10
MCP_TRANSPORTS = frozenset({"stdio", "http"})
_SERVER_ID_RE = re.compile(r"[^A-Za-z0-9_]+")
_ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def mcp_settings_path(settings_path: str | Path | None = None) -> Path:
    return Path(settings_path).expanduser() if settings_path is not None else DEFAULT_MCP_SETTINGS_PATH


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
    return {"servers": normalize_mcp_servers(payload.get("servers"))}


def write_mcp_settings(payload: dict[str, Any], settings_path: str | Path | None = None) -> None:
    path = mcp_settings_path(settings_path)
    atomic_write_json(path, {"servers": normalize_mcp_servers(payload.get("servers"))})
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
        runtime["headers"] = dict(server.get("headers") or {})
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


__all__ = [
    "DEFAULT_CONNECT_TIMEOUT_SECONDS",
    "DEFAULT_MCP_SETTINGS_PATH",
    "DEFAULT_TOOL_TIMEOUT_SECONDS",
    "mcp_runtime_config",
    "mcp_settings_path",
    "normalize_mcp_server_config",
    "normalize_mcp_servers",
    "normalize_mcp_settings_update",
    "public_mcp_settings",
    "read_mcp_settings",
    "write_mcp_settings",
]
