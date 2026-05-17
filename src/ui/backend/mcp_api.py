from __future__ import annotations

from pathlib import Path
from typing import Any

from tools.mcp import (
    normalize_mcp_server_config,
    normalize_mcp_settings_update,
    probe_mcp_server,
    public_mcp_settings,
    read_mcp_settings,
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


def _reset_agent_service() -> None:
    from ui.backend.agent_api import set_agent_service

    set_agent_service(None)


__all__ = ["get_mcp_settings", "test_mcp_server", "update_mcp_settings"]
