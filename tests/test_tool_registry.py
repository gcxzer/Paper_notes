from __future__ import annotations

import json

from agent_runtime import AgentRunRequest, AgentRunner
from model_providers.types import ModelRequest, ModelResponse, ToolCall
from tools.executor import ToolExecutorAdapter
from tools.output_limits import ToolResultBudget
from tools.registry import ToolDefinition, ToolRegistry
from tools.result_storage import ToolResultStore
from tools.types import ToolGroupDefinition
from tools.toolsets import resolve_toolsets


class FakeProvider:
    name = "fake"

    def __init__(self, responses: list[ModelResponse]) -> None:
        self.responses = list(responses)
        self.requests: list[ModelRequest] = []

    def generate(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        return self.responses.pop(0)


def test_registry_exports_openai_function_schema():
    registry = ToolRegistry()
    registry.register(ToolDefinition(
        name="lookup",
        description="Look up a value.",
        parameters={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
        handler=lambda args: {"query": args["query"]},
        toolset="test",
        read_only=True,
    ))

    schemas = registry.schemas()

    assert schemas == [{
        "type": "function",
        "function": {
            "name": "lookup",
            "description": "Look up a value.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    }]


def test_registry_filters_schemas_by_tool_names():
    registry = ToolRegistry()
    registry.register(ToolDefinition(
        name="lookup",
        description="Look up a value.",
        parameters={"type": "object", "properties": {}},
        handler=lambda args: {"ok": True},
        toolset="test",
    ))
    registry.register(ToolDefinition(
        name="write_persistent_memory",
        description="Write persistent memory.",
        parameters={"type": "object", "properties": {}},
        handler=lambda args: {"ok": True},
        toolset="persistent_memory",
    ))

    schemas = registry.schemas(tool_names={"lookup"})

    assert [schema["function"]["name"] for schema in schemas] == ["lookup"]


def test_registry_registers_group_manifest_and_rejects_duplicate_names():
    registry = ToolRegistry()
    registry.register_group(ToolGroupDefinition(
        name="research",
        display_name="Research",
        description="Research tools.",
        tools=("lookup",),
        capabilities=("search",),
    ))
    registry.register(ToolDefinition(
        name="lookup",
        description="Look up a value.",
        parameters={"type": "object", "properties": {}},
        handler=lambda args: {"ok": True},
        toolset="research",
    ))

    assert registry.get_group("research").display_name == "Research"
    assert registry.tool_names_for_toolset("research") == ["lookup"]
    assert registry.generation >= 2

    try:
        registry.register(ToolDefinition(
            name="lookup",
            description="Duplicate.",
            parameters={"type": "object", "properties": {}},
            handler=lambda args: {"ok": True},
        ))
    except ValueError as error:
        assert "Tool already registered" in str(error)
    else:
        raise AssertionError("duplicate tool name should be rejected")


def test_registry_availability_cache_and_dynamic_schema():
    calls = {"count": 0}

    def available() -> dict:
        calls["count"] += 1
        return {"available": calls["count"] > 1, "reason": "warming_up"}

    registry = ToolRegistry(availability_ttl_seconds=60)
    registry.register(ToolDefinition(
        name="lookup",
        description="Look up a value.",
        parameters={"type": "object", "properties": {}},
        dynamic_schema=lambda: {
            "type": "object",
            "properties": {"query": {"type": ["string", "null"]}},
            "required": ["query"],
        },
        availability_check=available,
        handler=lambda args: {"ok": True},
        read_only=True,
    ))

    assert registry.schemas(tool_names={"lookup"}) == []
    registry.invalidate_availability_cache("lookup")
    schemas = registry.schemas(tool_names={"lookup"})

    assert calls["count"] == 2
    assert schemas[0]["function"]["parameters"]["properties"]["query"]["type"] == ["string", "null"]


def test_registry_json_trim_preserves_artifacts_and_security_warnings():
    artifact = {"id": "artifact-1", "kind": "image", "fileName": "plot.png"}
    registry = ToolRegistry()
    registry.register(ToolDefinition(
        name="large_json",
        description="Large JSON.",
        parameters={"type": "object", "properties": {}},
        handler=lambda args: {
            "success": True,
            "server_id": "mcp_server",
            "result": "x" * 500,
            "structuredContent": {"large": "y" * 500},
            "artifacts": [artifact],
            "mediaErrors": [{"code": "mcp_media_artifact_failed", "error": "nope"}],
            "securityWarnings": [{"code": "mcp_prompt_injection_suspected"}],
            "extra": "z" * 500,
        },
        result_max_chars=180,
    ))

    payload = json.loads(registry.dispatch("large_json", {}).content)

    assert payload["success"] is True
    assert payload["server_id"] == "mcp_server"
    assert payload["artifacts"] == [artifact]
    assert payload["mediaErrors"][0]["code"] == "mcp_media_artifact_failed"
    assert payload["securityWarnings"][0]["code"] == "mcp_prompt_injection_suspected"
    assert payload["truncated"] is True
    assert payload["result"].endswith("...[truncated]")
    assert payload["structuredContent"]["truncated"] is True
    assert "extra" in payload["omitted_keys"]


def test_registry_non_json_trim_still_returns_preview_payload():
    registry = ToolRegistry()
    registry.register(ToolDefinition(
        name="large_text",
        description="Large text.",
        parameters={"type": "object", "properties": {}},
        handler=lambda args: "a" * 500,
        result_max_chars=100,
    ))

    payload = json.loads(registry.dispatch("large_text", {}).content)

    assert payload["success"] is True
    assert payload["truncated"] is True
    assert payload["preview"].endswith("...[truncated]")
    assert payload["original_chars"] == 500


def test_toolset_resolution_composes_builtin_toolsets_and_disables_groups():
    registry = ToolRegistry()
    for name, toolset in (
        ("search_notes", "paper_notes"),
        ("get_note_context", "paper_notes"),
        ("read_paper", "paper_notes"),
        ("write_note", "paper_notes"),
        ("manage_annotations", "paper_notes"),
        ("write_note_media", "paper_notes"),
        ("review_note", "paper_notes"),
        ("persistent_memory", "persistent_memory"),
        ("session_search", "session_search"),
        ("todo", "todo"),
        ("skills_list", "skills"),
        ("skill_view", "skills"),
        ("execute_code", "code_execution"),
        ("custom_lookup", "custom"),
    ):
        registry.register(ToolDefinition(
            name=name,
            description=f"{name} tool.",
            parameters={"type": "object", "properties": {}},
            handler=lambda args: {"ok": True},
            toolset=toolset,
        ))

    default_resolution = resolve_toolsets(registry)
    paper_notes_only = resolve_toolsets(registry, enabled_toolsets=["paper_notes"])
    without_todo = resolve_toolsets(registry, disabled_toolsets=["todo"])
    old_alias = resolve_toolsets(registry, enabled_toolsets=["paper", "planning"], default_toolsets=None)
    custom = resolve_toolsets(registry, enabled_toolsets=["custom"], default_toolsets=None)
    readonly = resolve_toolsets(registry, enabled_toolsets=["readonly"], default_toolsets=None)

    assert set(default_resolution.tool_names) == {
        "search_notes",
        "get_note_context",
        "read_paper",
        "write_note",
        "manage_annotations",
        "write_note_media",
        "review_note",
        "persistent_memory",
        "session_search",
        "todo",
        "skills_list",
        "skill_view",
        "execute_code",
    }
    assert set(paper_notes_only.tool_names) == {
        "search_notes",
        "get_note_context",
        "read_paper",
        "write_note",
        "manage_annotations",
        "write_note_media",
        "review_note",
    }
    assert set(readonly.tool_names) == {
        "search_notes",
        "get_note_context",
        "read_paper",
        "review_note",
        "session_search",
    }
    assert "write_note" not in readonly.tool_names
    assert resolve_toolsets(registry, enabled_toolsets=["paper_notes_internal"]).unknown_toolsets == ("paper_notes_internal",)
    assert "todo" not in without_todo.tool_names
    assert old_alias.tool_names == ()
    assert old_alias.unknown_toolsets == ("paper", "planning")
    assert custom.tool_names == ("custom_lookup",)


def test_tool_executor_adapter_dispatches_tool_call():
    registry = ToolRegistry()
    registry.register(ToolDefinition(
        name="lookup",
        description="Look up a value.",
        parameters={"type": "object", "properties": {"query": {"type": "string"}}},
        handler=lambda args: {"result": args["query"].upper()},
    ))
    executor = ToolExecutorAdapter(registry)

    result = executor.execute(ToolCall(id="call_1", name="lookup", arguments='{"query": "paper"}'))

    assert result.call_id == "call_1"
    assert result.name == "lookup"
    assert result.is_error is False
    assert json.loads(result.content) == {"result": "PAPER"}


def test_tool_executor_adapter_reports_read_only_status():
    registry = ToolRegistry()
    registry.register(ToolDefinition(
        name="lookup",
        description="Look up a value.",
        parameters={"type": "object"},
        handler=lambda args: {"result": "ok"},
        read_only=True,
    ))
    registry.register(ToolDefinition(
        name="write_persistent_memory",
        description="Write persistent memory.",
        parameters={"type": "object"},
        handler=lambda args: {"success": True},
        read_only=False,
    ))
    executor = ToolExecutorAdapter(registry)

    assert executor.is_read_only("lookup") is True
    assert executor.is_read_only("write_persistent_memory") is False
    assert executor.is_read_only("missing") is False


def test_tool_executor_adapter_reports_invalid_arguments():
    registry = ToolRegistry()
    executor = ToolExecutorAdapter(registry)

    result = executor.execute(ToolCall(id="call_1", name="lookup", arguments="not-json"))

    assert result.is_error is True
    assert json.loads(result.content)["error"] == "Tool arguments must be a JSON object."


def test_tool_executor_adapter_coerces_common_json_schema_arguments():
    registry = ToolRegistry()
    registry.register(ToolDefinition(
        name="coerce",
        description="Coerce arguments.",
        parameters={
            "type": "object",
            "properties": {
                "count": {"type": "integer"},
                "enabled": {"type": "boolean"},
                "tags": {"type": "array", "items": {"type": "string"}},
            },
        },
        handler=lambda args: args,
    ))
    executor = ToolExecutorAdapter(registry)

    result = executor.execute(ToolCall(
        id="call_1",
        name="coerce",
        arguments='{"count": "3", "enabled": "true", "tags": "paper"}',
    ))

    assert result.is_error is False
    assert json.loads(result.content) == {
        "count": 3,
        "enabled": True,
        "tags": ["paper"],
    }


def test_tool_executor_adapter_coerces_object_and_nullable_arguments():
    registry = ToolRegistry()
    registry.register(ToolDefinition(
        name="coerce_object",
        description="Coerce object arguments.",
        parameters={
            "type": "object",
            "properties": {
                "payload": {
                    "type": "object",
                    "properties": {"count": {"type": "integer"}},
                },
                "optional": {"type": ["string", "null"]},
            },
        },
        handler=lambda args: args,
    ))
    executor = ToolExecutorAdapter(registry)

    result = executor.execute(ToolCall(
        id="call_1",
        name="coerce_object",
        arguments='{"payload": "{\\"count\\": \\"4\\"}", "optional": null}',
    ))

    assert result.is_error is False
    assert json.loads(result.content) == {
        "payload": {"count": 4},
        "optional": None,
    }


def test_tool_executor_persists_large_result_and_preserves_full_output(tmp_path):
    artifact = {"id": "artifact-1", "kind": "image", "fileName": "plot.png"}
    registry = ToolRegistry()
    registry.register(ToolDefinition(
        name="large_lookup",
        description="Large lookup.",
        parameters={"type": "object", "properties": {}},
        handler=lambda args: {
            "success": True,
            "result": "x" * 240,
            "artifacts": [artifact],
            "securityWarnings": [{"code": "mcp_prompt_injection_suspected"}],
        },
        result_max_chars=60,
    ))
    result_store = ToolResultStore(
        tmp_path / ".paper-notes" / "tool-results",
        budget=ToolResultBudget(default_result_size=1_000, preview_size=40),
        project_root=tmp_path,
    )
    executor = ToolExecutorAdapter(
        registry,
        session_id_provider=lambda: "session-1",
        result_store=result_store,
    )

    result = executor.execute(ToolCall(id="call_large", name="large_lookup", arguments="{}"))
    payload = json.loads(result.content)
    stored_path = tmp_path / payload["path"]
    stored = json.loads(stored_path.read_text(encoding="utf-8"))

    assert payload["persisted_tool_result"] is True
    assert payload["original_chars"] > 200
    assert len(payload["preview"]) < payload["original_chars"]
    assert payload["artifacts"] == [artifact]
    assert payload["securityWarnings"][0]["code"] == "mcp_prompt_injection_suspected"
    assert stored["content"].count("x") == 240
    assert result.metadata["tool_result"]["persisted"] is True


def test_tool_executor_enforces_turn_budget_across_medium_results(tmp_path):
    registry = ToolRegistry()
    registry.register(ToolDefinition(
        name="medium_a",
        description="Medium A.",
        parameters={"type": "object", "properties": {}},
        handler=lambda args: "a" * 80,
    ))
    registry.register(ToolDefinition(
        name="medium_b",
        description="Medium B.",
        parameters={"type": "object", "properties": {}},
        handler=lambda args: "b" * 80,
    ))
    result_store = ToolResultStore(
        tmp_path / ".paper-notes" / "tool-results",
        budget=ToolResultBudget(default_result_size=1_000, turn_budget=120, preview_size=20),
        project_root=tmp_path,
    )
    executor = ToolExecutorAdapter(
        registry,
        session_id_provider=lambda: "session-2",
        result_store=result_store,
    )
    first = executor.execute(ToolCall(id="call_a", name="medium_a", arguments="{}"))
    second = executor.execute(ToolCall(id="call_b", name="medium_b", arguments="{}"))
    messages = [
        {"role": "tool", "name": first.name, "tool_call_id": first.call_id, "content": first.content},
        {"role": "tool", "name": second.name, "tool_call_id": second.call_id, "content": second.content},
    ]

    executor.enforce_turn_budget(messages)

    persisted_count = 0
    for message in messages:
        try:
            payload = json.loads(message["content"])
        except json.JSONDecodeError:
            continue
        if payload.get("persisted_tool_result"):
            persisted_count += 1
    assert persisted_count >= 1


def test_runner_can_use_registry_executor_for_tool_loop():
    registry = ToolRegistry()
    registry.register(ToolDefinition(
        name="lookup",
        description="Look up a value.",
        parameters={"type": "object", "properties": {"query": {"type": "string"}}},
        handler=lambda args: {"result": f"found {args['query']}"},
    ))
    provider = FakeProvider([
        ModelResponse(
            content=None,
            tool_calls=[ToolCall(id="call_1", name="lookup", arguments='{"query": "notes"}')],
            finish_reason="tool_calls",
        ),
        ModelResponse(content="The lookup found notes."),
    ])
    runner = AgentRunner(provider, tool_executor=ToolExecutorAdapter(registry))

    result = runner.run(AgentRunRequest(
        model="test-model",
        messages=[{"role": "user", "content": "Find notes"}],
        tools=registry.schemas(),
    ))

    assert result.completed is True
    assert result.final_response == "The lookup found notes."
    tool_message = provider.requests[1].messages[-1]
    assert tool_message["role"] == "tool"
    assert json.loads(tool_message["content"]) == {"result": "found notes"}
