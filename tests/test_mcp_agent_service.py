from __future__ import annotations

from agent_runtime.service import AgentService
from app_config import AppConfig


def test_agent_service_wires_mcp_manager_into_tool_context(monkeypatch, tmp_path):
    created = []

    class FakeMCPManager:
        def __init__(self, *, media_store=None):
            self.media_store = media_store
            self.discovered = False
            self.closed = False
            created.append(self)

        def discover_from_settings(self):
            self.discovered = True
            return ["mcp_fake_tool"]

        def shutdown(self):
            self.closed = True

    import tools.mcp as mcp_package

    monkeypatch.setattr(mcp_package, "MCPManager", FakeMCPManager)
    monkeypatch.setattr(mcp_package, "mcp_enabled", lambda: True)
    media_store = object()

    service = AgentService(
        app_config=AppConfig(data={}, path=tmp_path / "config.json"),
        media_store=media_store,
        use_default_tools=False,
    )

    assert created == [service.mcp_manager]
    assert service.mcp_manager.media_store is media_store
    assert service.mcp_manager.discovered is True
    assert service._tool_context.mcp_manager is service.mcp_manager

    manager = service.mcp_manager
    service.close()

    assert service.mcp_manager is None
    assert manager.closed is True


def test_agent_service_skips_mcp_manager_when_mcp_is_disabled(monkeypatch, tmp_path):
    created = []

    class FakeMCPManager:
        def __init__(self, *, media_store=None):
            created.append(self)

    import tools.mcp as mcp_package

    monkeypatch.setattr(mcp_package, "MCPManager", FakeMCPManager)
    monkeypatch.setattr(mcp_package, "mcp_enabled", lambda: False)

    service = AgentService(
        app_config=AppConfig(data={}, path=tmp_path / "config.json"),
    )

    assert created == []
    assert service.mcp_manager is None
    assert service._tool_context.mcp_manager is None
