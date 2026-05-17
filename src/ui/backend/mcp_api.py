from __future__ import annotations

from pathlib import Path
from typing import Any

from tools.mcp import (
    normalize_mcp_server_config,
    normalize_mcp_settings_update,
    probe_mcp_server,
    public_mcp_settings,
    read_mcp_settings,
    read_mcp_stderr_log,
    write_mcp_settings,
)


def get_mcp_settings(
    *,
    settings_path: str | Path | None = None,
    service: Any = None,
) -> dict[str, Any]:
    settings = read_mcp_settings(settings_path)
    agent_service = service
    if agent_service is None:
        try:
            from ui.backend.agent_api import get_agent_service

            agent_service = get_agent_service()
        except Exception:
            agent_service = None
    manager = getattr(agent_service, "mcp_manager", None)
    statuses = manager.statuses() if manager is not None else {}
    return public_mcp_settings(settings, statuses=statuses, settings_path=settings_path)


def update_mcp_settings(
    body: Any,
    *,
    settings_path: str | Path | None = None,
) -> dict[str, Any]:
    current = read_mcp_settings(settings_path)
    settings = normalize_mcp_settings_update(body, current=current)
    write_mcp_settings(settings, settings_path)
    _reset_agent_service()
    return public_mcp_settings(read_mcp_settings(settings_path), settings_path=settings_path)


def test_mcp_server(body: Any) -> dict[str, Any]:
    server = normalize_mcp_server_config(body, strict=True)
    return probe_mcp_server(server)


def reconnect_mcp_server(
    body: Any,
    *,
    service: Any = None,
) -> dict[str, Any]:
    server_id = _server_id_from_body(body)
    manager = _mcp_manager(service)
    if manager is None:
        return {"success": False, "serverId": server_id, "error": "Agent service is not running.", "code": "agent_service_not_running"}
    reconnect = getattr(manager, "reconnect_server", None)
    if not callable(reconnect):
        return {"success": False, "serverId": server_id, "error": "MCP manager does not support reconnect.", "code": "mcp_reconnect_unavailable"}
    return reconnect(server_id)


def reset_mcp_server_circuit(
    body: Any,
    *,
    service: Any = None,
) -> dict[str, Any]:
    server_id = _server_id_from_body(body)
    manager = _mcp_manager(service)
    if manager is None:
        return {"success": False, "serverId": server_id, "error": "Agent service is not running.", "code": "agent_service_not_running"}
    reset = getattr(manager, "reset_server_circuit", None)
    if not callable(reset):
        return {"success": False, "serverId": server_id, "error": "MCP manager does not support circuit reset.", "code": "mcp_reset_unavailable"}
    return reset(server_id)


def get_mcp_stderr_log(*, max_chars: int = 60000) -> dict[str, Any]:
    return read_mcp_stderr_log(max_chars=max_chars)


def _mcp_manager(service: Any = None) -> Any:
    agent_service = service
    if agent_service is None:
        try:
            from ui.backend.agent_api import get_agent_service

            agent_service = get_agent_service()
        except Exception:
            return None
    return getattr(agent_service, "mcp_manager", None)


def _server_id_from_body(body: Any) -> str:
    if not isinstance(body, dict):
        raise ValueError("Request body must be a JSON object.")
    server_id = str(body.get("serverId") or body.get("server_id") or body.get("id") or "").strip()
    if not server_id:
        raise ValueError("MCP server id is required.")
    return server_id


def _reset_agent_service() -> None:
    from ui.backend.agent_api import set_agent_service

    set_agent_service(None)


__all__ = [
    "get_mcp_settings",
    "get_mcp_stderr_log",
    "reconnect_mcp_server",
    "reset_mcp_server_circuit",
    "test_mcp_server",
    "update_mcp_settings",
]
