"""Verify per-note serialization of selected RAG tool calls."""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace

from langchain_core.messages import ToolMessage

from middleware.rag_tool_serialization import RagToolSerializationMiddleware


def test_rag_tool_serialization_middleware_serializes_same_note_calls() -> None:
    middleware = RagToolSerializationMiddleware()
    active_count = 0
    max_active_count = 0
    active_lock = threading.Lock()
    start_barrier = threading.Barrier(3)
    errors: list[BaseException] = []

    def handler(request):
        nonlocal active_count, max_active_count
        with active_lock:
            active_count += 1
            max_active_count = max(max_active_count, active_count)
        time.sleep(0.05)
        with active_lock:
            active_count -= 1
        return ToolMessage(content="ok", tool_call_id=request.tool_call["id"])

    def invoke(call_id: str) -> None:
        try:
            start_barrier.wait(timeout=2)
            middleware.wrap_tool_call(_request(call_id=call_id, note_id="note-1"), handler)
        except BaseException as error:
            errors.append(error)

    threads = [threading.Thread(target=invoke, args=(f"call-{index}",)) for index in range(2)]
    for thread in threads:
        thread.start()
    start_barrier.wait(timeout=2)
    for thread in threads:
        thread.join(timeout=2)

    assert errors == []
    assert max_active_count == 1


def _request(*, call_id: str, note_id: str):
    return SimpleNamespace(
        tool=SimpleNamespace(name="query_paper_content"),
        tool_call={
            "name": "query_paper_content",
            "args": {"note_id": note_id, "query": "Figure 2"},
            "id": call_id,
        },
    )
