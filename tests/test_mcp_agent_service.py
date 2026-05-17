from __future__ import annotations

from agent_runtime.service import AgentService
from agent_sessions import AgentSessionStore
from tools.registry import ToolDefinition


def test_agent_service_discovers_mcp_tools_and_hides_unknown_mutating_in_readonly(tmp_path, monkeypatch):
    managers = []

    class FakeMCPManager:
        def __init__(self, registry, *, media_store=None) -> None:
            self.registry = registry
            self.media_store = media_store
            self.closed = False
            managers.append(self)

        def discover_from_settings(self):
            self.registry.register(ToolDefinition(
                name="mcp_filesystem_write_file",
                description="External write tool.",
                parameters={"type": "object", "properties": {}},
                handler=lambda args: {"success": True},
                toolset="mcp",
                mutating=True,
                risk="write",
                kind="external",
            ))
            return ["mcp_filesystem_write_file"]

        def statuses(self):
            return {}

        def shutdown(self):
            self.closed = True

    monkeypatch.setattr("tools.mcp.MCPManager", FakeMCPManager)
    service = AgentService(
        session_store=AgentSessionStore(tmp_path / ".paper-notes" / "sessions"),
        use_memory=False,
        use_session_search=False,
        use_compression=False,
    )

    enabled = service._tool_schemas_for_selection(
        enable_tools=True,
        enabled_toolsets=["mcp"],
        disabled_toolsets=None,
        disabled_tools=None,
        tool_write_modes=None,
        write_tool_mode="auto",
    )
    readonly = service._tool_schemas_for_selection(
        enable_tools=True,
        enabled_toolsets=["mcp"],
        disabled_toolsets=None,
        disabled_tools=None,
        tool_write_modes=None,
        write_tool_mode="readonly",
    )

    assert [tool["function"]["name"] for tool in enabled] == ["mcp_filesystem_write_file"]
    assert readonly == []
    service.close()
    assert managers[0].closed is True
    assert service.mcp_manager is None
