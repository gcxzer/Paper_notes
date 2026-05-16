from __future__ import annotations

import pytest

from agent_runtime.service import AgentService
from agent_sessions import AgentSessionStore
from backend.agent_api import (
    AgentAPIError,
    cleanup_debug_runs,
    get_debug_run,
    handle_chat_request,
    list_debug_runs,
)
from model_providers.types import ModelRequest, ModelResponse
from tools.registry import ToolRegistry
from telemetry.debug_logs import DebugRunStore, sanitize_debug_payload


class FakeProvider:
    name = "fake"

    def __init__(self, responses: list[ModelResponse]) -> None:
        self.responses = list(responses)
        self.requests: list[ModelRequest] = []

    def generate(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        return self.responses.pop(0)


def test_sanitize_debug_payload_redacts_secrets_and_base64() -> None:
    payload = sanitize_debug_payload({
        "Authorization": "Bearer secret-token",
        "OPENAI_API_KEY": "sk-test",
        "image": "data:image/png;base64,abcdef",
        "large": "a" * 5000,
    })

    assert payload["Authorization"] == "[redacted]"
    assert payload["OPENAI_API_KEY"] == "[redacted]"
    assert payload["image"] == "[image-data-url-redacted]"
    assert "large-string-redacted" in payload["large"]


def test_sanitize_debug_payload_keeps_numeric_token_usage() -> None:
    payload = sanitize_debug_payload({
        "input_tokens": 100,
        "output_tokens": 20,
        "total_tokens": 120,
        "before_estimated_tokens": 1000,
        "access_token": "secret",
        "custom_token": "secret",
    })

    assert payload["input_tokens"] == 100
    assert payload["output_tokens"] == 20
    assert payload["total_tokens"] == 120
    assert payload["before_estimated_tokens"] == 1000
    assert payload["access_token"] == "[redacted]"
    assert payload["custom_token"] == "[redacted]"


def test_chat_success_writes_debug_run(tmp_path) -> None:
    provider = FakeProvider([ModelResponse(content="Debug answer.")])
    service = AgentService(
        model_provider=provider,
        session_store=AgentSessionStore(tmp_path / ".paper-notes" / "sessions"),
        tool_registry=ToolRegistry(),
        default_model="test-model",
    )
    debug_store = DebugRunStore(tmp_path / ".paper-notes" / "logs" / "runs")

    payload = handle_chat_request(
        {"requestId": "debug-req-1", "message": "Hello", "model": "test-model"},
        service=service,
        debug_store=debug_store,
    )

    record = debug_store.get_run("debug-req-1")
    assert payload["requestId"] == "debug-req-1"
    assert record is not None
    assert record["status"] == "completed"
    assert record["sessionId"] == payload["sessionId"]
    assert record["provider"] == "fake"
    assert record["model"] == "test-model"
    assert record["transcriptPath"].endswith(".jsonl")
    assert record["finalMessagePreview"] == "Debug answer."
    assert record["events"]


def test_chat_error_writes_debug_run(tmp_path) -> None:
    service = AgentService(
        model_provider=FakeProvider([]),
        session_store=AgentSessionStore(tmp_path / ".paper-notes" / "sessions"),
        tool_registry=ToolRegistry(),
    )
    debug_store = DebugRunStore(tmp_path / ".paper-notes" / "logs" / "runs")

    with pytest.raises(AgentAPIError):
        handle_chat_request(
            {"requestId": "debug-error-1", "message": ""},
            service=service,
            debug_store=debug_store,
        )

    record = debug_store.get_run("debug-error-1")
    assert record is not None
    assert record["status"] == "failed"
    assert record["error"]["code"] == "message_required"


def test_debug_run_api_list_detail_cleanup(tmp_path) -> None:
    debug_store = DebugRunStore(tmp_path / ".paper-notes" / "logs" / "runs")
    debug_store.start_run(request_id="debug-api-1", session_id="session-1", provider="fake", model="m", transport="json")
    debug_store.finish_run(
        "debug-api-1",
        status="completed",
        session_id="session-1",
        provider="fake",
        model="m",
        final_message_preview="done",
    )

    listed = list_debug_runs({"limit": ["10"], "sessionId": ["session-1"]}, debug_store=debug_store)
    assert [item["requestId"] for item in listed["runs"]] == ["debug-api-1"]

    detail = get_debug_run("debug-api-1", debug_store=debug_store)
    assert detail["run"]["finalMessagePreview"] == "done"

    cleaned = cleanup_debug_runs({"keep": 0, "maxAgeDays": 1}, debug_store=debug_store)
    assert cleaned["deletedCount"] == 1
    assert get_debug_run_missing("debug-api-1", debug_store) == "missing"


def get_debug_run_missing(request_id: str, debug_store: DebugRunStore) -> str:
    try:
        get_debug_run(request_id, debug_store=debug_store)
    except AgentAPIError:
        return "missing"
    return "present"
