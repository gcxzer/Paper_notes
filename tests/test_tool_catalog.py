from __future__ import annotations

from tools.catalog import ToolCatalog, ToolSelection
from tools.registry import ToolDefinition, ToolRegistry


def test_tool_group_manifests_export_registration_entrypoints():
    from tools.paper_notes import manifest as paper_notes_manifest
    from tools.persistent_memory import manifest as memory_manifest
    from tools.session_search import manifest as session_search_manifest
    from tools.skills import manifest as skills_manifest
    from tools.todo import manifest as todo_manifest
    from tools.code_execution import manifest as code_execution_manifest
    from tools.web_search import manifest as web_search_manifest
    from tools.generated_files import manifest as generated_files_manifest
    from tools.generated_images import manifest as generated_images_manifest

    manifests = (
        paper_notes_manifest,
        memory_manifest,
        session_search_manifest,
        todo_manifest,
        skills_manifest,
        code_execution_manifest,
        web_search_manifest,
        generated_files_manifest,
        generated_images_manifest,
    )

    assert [manifest.TOOL_GROUP.name for manifest in manifests] == [
        "paper_notes",
        "persistent_memory",
        "session_search",
        "todo",
        "skills",
        "code_execution",
        "web_search",
        "generated_artifacts",
        "generated_artifacts",
    ]
    assert all(callable(manifest.register_tools) for manifest in manifests)


def test_catalog_resolves_default_readonly_and_settings_groups():
    registry = _registry_with_group_tools()
    catalog = ToolCatalog(registry)

    default = catalog.resolve(ToolSelection.from_values())
    readonly = catalog.resolve(ToolSelection.from_values(enabled_toolsets=["readonly"], default_toolsets=None))
    group_names = [group.name for group in catalog.describe_groups()]

    assert set(default.tool_names) == {
        "search_notes",
        "write_note",
        "persistent_memory",
        "session_search",
        "todo",
        "skills_list",
        "skill_view",
        "execute_code",
        "web_fetch",
        "web_search",
    }
    assert set(readonly.tool_names) == {"search_notes", "session_search"}
    assert "write_note" not in readonly.tool_names
    assert group_names == ["paper_notes", "code_execution", "persistent_memory", "session_search", "todo", "skills", "web_search"]


def test_generated_artifact_toolset_is_explicit_but_not_default():
    registry = _registry_with_group_tools()
    registry.register(ToolDefinition(
        name="create_file_artifact",
        description="Create file.",
        parameters={"type": "object", "properties": {}},
        handler=lambda args: {"success": True},
        toolset="generated_artifacts",
        risk="write",
        kind="external",
    ))
    registry.register(ToolDefinition(
        name="create_image_artifact",
        description="Create image.",
        parameters={"type": "object", "properties": {}},
        handler=lambda args: {"success": True},
        toolset="generated_artifacts",
        risk="write",
        kind="external",
    ))
    catalog = ToolCatalog(registry)

    default = catalog.resolve(ToolSelection.from_values())
    generated = catalog.resolve(ToolSelection.from_values(enabled_toolsets=["generated_artifacts"], default_toolsets=None))
    groups = {group.name: group for group in catalog.describe_groups()}

    assert "create_file_artifact" not in default.tool_names
    assert "create_image_artifact" not in default.tool_names
    assert set(generated.tool_names) == {"create_file_artifact", "create_image_artifact"}
    assert groups["generated_artifacts"].metadata["ui_hidden"] is True


def test_mcp_toolset_is_explicit_dynamic_settings_group():
    registry = _registry_with_group_tools()
    registry.register(ToolDefinition(
        name="mcp_filesystem_write_file",
        description="Write through an external MCP server.",
        parameters={"type": "object", "properties": {}},
        handler=lambda args: {"success": True},
        toolset="mcp",
        mutating=True,
        risk="write",
        kind="external",
    ))
    catalog = ToolCatalog(registry)

    default = catalog.resolve(ToolSelection.from_values())
    mcp = catalog.resolve(ToolSelection.from_values(enabled_toolsets=["mcp"], default_toolsets=None))
    group_names = [group.name for group in catalog.describe_groups()]

    assert "mcp_filesystem_write_file" not in default.tool_names
    assert mcp.tool_names == ("mcp_filesystem_write_file",)
    assert group_names == [
        "paper_notes",
        "code_execution",
        "persistent_memory",
        "session_search",
        "todo",
        "skills",
        "web_search",
        "mcp",
    ]
    assert catalog.describe_groups()[-1].display_name == "MCP"


def test_catalog_cache_returns_deep_copy_and_invalidates_on_generation():
    registry = _registry_with_group_tools()
    catalog = ToolCatalog(registry)
    selection = ToolSelection.from_values()

    first = catalog.resolve(selection)
    first.model_tools[0]["function"]["description"] = "mutated"
    second = catalog.resolve(selection)
    registry.register(ToolDefinition(
        name="get_note_context",
        description="Get note context.",
        parameters={"type": "object", "properties": {}},
        handler=lambda args: {"ok": True},
        toolset="paper_notes",
        read_only=True,
    ))
    third = catalog.resolve(selection)

    assert second.model_tools[0]["function"]["description"] != "mutated"
    assert "get_note_context" in third.tool_names
    assert third.generation > second.generation


def test_catalog_tracks_availability_and_uses_ttl_cache():
    calls = {"count": 0}

    def available() -> dict:
        calls["count"] += 1
        return {"available": calls["count"] > 1, "reason": "warming_up"}

    registry = ToolRegistry(availability_ttl_seconds=60)
    registry.register(ToolDefinition(
        name="lookup",
        description="Lookup.",
        parameters={"type": "object", "properties": {}},
        handler=lambda args: {"ok": True},
        toolset="custom",
        read_only=True,
        availability_check=available,
    ))
    catalog = ToolCatalog(registry)
    selection = ToolSelection.from_values(enabled_toolsets=["custom"], default_toolsets=None)

    first = catalog.resolve(selection)
    second = catalog.resolve(selection)

    assert first.tool_names == ()
    assert first.unavailable_tools[0]["name"] == "lookup"
    assert second.tool_names == ()
    assert calls["count"] == 1

    registry.invalidate_availability_cache("lookup")
    third = catalog.resolve(selection)

    assert third.tool_names == ("lookup",)
    assert calls["count"] == 2


def test_catalog_falls_back_when_dynamic_schema_raises():
    def bad_schema() -> dict:
        raise RuntimeError("boom")

    registry = ToolRegistry()
    registry.register(ToolDefinition(
        name="lookup",
        description="Lookup.",
        parameters={"type": "object", "properties": {"query": {"type": "string"}}},
        dynamic_schema=bad_schema,
        handler=lambda args: {"ok": True},
        toolset="custom",
        read_only=True,
    ))
    catalog = ToolCatalog(registry)

    snapshot = catalog.resolve(ToolSelection.from_values(enabled_toolsets=["custom"], default_toolsets=None))

    assert snapshot.model_tools[0]["function"]["parameters"]["properties"]["query"]["type"] == "string"


def test_registry_dispatches_async_tool_handler():
    async def async_handler(args):
        return {"value": args["value"]}

    registry = ToolRegistry()
    registry.register(ToolDefinition(
        name="async_lookup",
        description="Async lookup.",
        parameters={"type": "object", "properties": {"value": {"type": "string"}}},
        handler=async_handler,
        read_only=True,
    ))

    result = registry.dispatch("async_lookup", {"value": "ok"})

    assert result.is_error is False
    assert result.content == '{\n  "value": "ok"\n}'


def _registry_with_group_tools() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(ToolDefinition(
        name="search_notes",
        description="Search local notes.",
        parameters={"type": "object", "properties": {}},
        handler=lambda args: {"success": True},
        toolset="paper_notes",
        read_only=True,
    ))
    registry.register(ToolDefinition(
        name="write_note",
        description="Write note HTML.",
        parameters={"type": "object", "properties": {}},
        handler=lambda args: {"success": True},
        toolset="paper_notes",
        mutating=True,
        risk="write",
    ))
    registry.register(ToolDefinition(
        name="persistent_memory",
        description="Manage persistent memory.",
        parameters={"type": "object", "properties": {}},
        handler=lambda args: {"success": True},
        toolset="persistent_memory",
        mutating=True,
        risk="write",
    ))
    registry.register(ToolDefinition(
        name="session_search",
        description="Search sessions.",
        parameters={"type": "object", "properties": {}},
        handler=lambda args: {"success": True},
        toolset="session_search",
        read_only=True,
    ))
    registry.register(ToolDefinition(
        name="todo",
        description="Manage todos.",
        parameters={"type": "object", "properties": {}},
        handler=lambda args: {"success": True},
        toolset="todo",
        mutating=True,
        risk="write",
    ))
    registry.register(ToolDefinition(
        name="skills_list",
        description="List skills.",
        parameters={"type": "object", "properties": {}},
        handler=lambda args: {"success": True},
        toolset="skills",
        read_only=True,
    ))
    registry.register(ToolDefinition(
        name="skill_view",
        description="View skill.",
        parameters={"type": "object", "properties": {}},
        handler=lambda args: {"success": True},
        toolset="skills",
        read_only=True,
    ))
    registry.register(ToolDefinition(
        name="execute_code",
        description="Run code.",
        parameters={"type": "object", "properties": {"code": {"type": "string"}}},
        handler=lambda args: {"success": True},
        toolset="code_execution",
        mutating=True,
        risk="write",
        kind="external",
    ))
    registry.register(ToolDefinition(
        name="web_fetch",
        description="Fetch URL.",
        parameters={"type": "object", "properties": {"url": {"type": "string"}}},
        handler=lambda args: {"success": True},
        toolset="web_search",
        read_only=True,
        kind="read",
    ))
    registry.register(ToolDefinition(
        name="web_search",
        description="Search web.",
        parameters={"type": "object", "properties": {"query": {"type": "string"}}},
        handler=lambda args: {"success": True},
        toolset="web_search",
        read_only=True,
        kind="search",
    ))
    return registry
