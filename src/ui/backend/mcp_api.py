from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from tools.mcp import (
    normalize_mcp_server_config,
    normalize_mcp_settings_update,
    probe_mcp_server,
    public_mcp_settings,
    read_mcp_settings,
    read_mcp_stderr_log,
    write_mcp_settings,
)


def register_mcp_routes(app: FastAPI) -> None:
    @app.get("/api/settings/mcp")
    async def api_get_mcp_settings() -> JSONResponse:
        return JSONResponse(get_mcp_settings())

    @app.post("/api/settings/mcp")
    async def api_update_mcp_settings(request: Request) -> JSONResponse:
        try:
            return JSONResponse(update_mcp_settings(await _json_body(request)))
        except Exception as error:
            return _mcp_error_response(error)

    @app.post("/api/settings/mcp/test")
    async def api_test_mcp_server(request: Request) -> JSONResponse:
        try:
            return JSONResponse(test_mcp_server(await _json_body(request)))
        except Exception as error:
            return _mcp_error_response(error)

    @app.post("/api/settings/mcp/connect")
    async def api_connect_mcp_server(request: Request) -> JSONResponse:
        try:
            return JSONResponse(connect_mcp_server(await _json_body(request)))
        except Exception as error:
            return _mcp_error_response(error)

    @app.post("/api/settings/mcp/reset-circuit")
    async def api_reset_mcp_server_circuit(request: Request) -> JSONResponse:
        try:
            return JSONResponse(reset_mcp_server_circuit(await _json_body(request)))
        except Exception as error:
            return _mcp_error_response(error)

    @app.get("/api/settings/mcp/stderr-log")
    async def api_get_mcp_stderr_log(maxChars: int = 60000, max_chars: int = 0) -> JSONResponse:
        return JSONResponse(get_mcp_stderr_log(max_chars=max_chars or maxChars))


def get_mcp_settings(
    *,
    settings_path: str | Path | None = None,
    service: Any = None,
) -> dict[str, Any]:
    settings = read_mcp_settings(settings_path)
    agent_service = service
    if agent_service is None:
        try:
            from ui.backend.agent_api import existing_agent_service

            agent_service = existing_agent_service()
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


def connect_mcp_server(
    body: Any,
    *,
    settings_path: str | Path | None = None,
    service: Any = None,
) -> dict[str, Any]:
    if not isinstance(body, dict):
        raise ValueError("Request body must be a JSON object.")
    persist = body.get("persist") is not False
    current = read_mcp_settings(settings_path)
    if isinstance(body.get("servers"), list):
        settings = normalize_mcp_settings_update(body, current=current)
        server_id = str(body.get("serverId") or body.get("server_id") or "").strip()
    else:
        server = normalize_mcp_server_config(body, strict=True)
        server_id = str(server.get("id") or "").strip()
        replaced = False
        servers: list[dict[str, Any]] = []
        for existing in current.get("servers") or []:
            if str(existing.get("id") or "") == server_id:
                servers.append(server)
                replaced = True
            else:
                servers.append(existing)
        if not replaced:
            servers.append(server)
        settings = normalize_mcp_settings_update({"servers": servers}, current=current)

    agent_service = service
    should_register = service is not None or not persist
    if agent_service is None:
        if persist:
            write_mcp_settings(settings, settings_path)
            _reset_agent_service()
        from ui.backend.agent_api import get_agent_service

        agent_service = get_agent_service()
    else:
        if persist:
            write_mcp_settings(settings, settings_path)
    if should_register:
        manager = getattr(agent_service, "mcp_manager", None)
        register = getattr(manager, "register_servers", None)
        if callable(register):
            register(settings.get("servers") or [])

    manager = getattr(agent_service, "mcp_manager", None)
    statuses = manager.statuses() if manager is not None else {}
    payload_settings = read_mcp_settings(settings_path) if persist else settings
    payload = public_mcp_settings(payload_settings, statuses=statuses, settings_path=settings_path)
    payload["serverId"] = server_id
    return payload


def test_mcp_server(body: Any) -> dict[str, Any]:
    server = normalize_mcp_server_config(body, strict=True)
    return probe_mcp_server(server)


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


async def _json_body(request: Request) -> dict[str, Any]:
    try:
        payload = await request.json()
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _mcp_error_response(error: Exception) -> JSONResponse:
    return JSONResponse(
        {"success": False, "error": str(error) or "MCP request failed."},
        status_code=400,
    )


__all__ = [
    "connect_mcp_server",
    "get_mcp_settings",
    "get_mcp_stderr_log",
    "register_mcp_routes",
    "reset_mcp_server_circuit",
    "test_mcp_server",
    "update_mcp_settings",
]
