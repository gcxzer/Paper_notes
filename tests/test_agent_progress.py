from __future__ import annotations

import json

from agent_runtime import AgentEvent
from telemetry.agent_progress import AgentProgressStore


def test_progress_keeps_raw_events_but_hides_model_events_from_visible_status():
    store = AgentProgressStore()

    store.start("req-1")
    store.append("req-1", AgentEvent("model_request", "Calling model provider."))
    store.append("req-1", AgentEvent("model_response", "Model provider returned a response."))
    snapshot = store.get("req-1")

    assert [event["type"] for event in snapshot["events"]] == ["model_request", "model_response"]
    assert snapshot["visibleEvents"] == []
    assert snapshot["visibleDetail"] == "Starting agent run."


def test_progress_maps_skill_tools_to_user_visible_status():
    store = AgentProgressStore()

    skills_list = store.append("req-skills", AgentEvent(
        "tool_call",
        data={"name": "skills_list", "arguments": "{}"},
    ))
    skill_view = store.append("req-skills", AgentEvent(
        "tool_call",
        data={"name": "skill_view", "arguments": json.dumps({"name": "test-paper-skill"})},
    ))

    assert skills_list["visibleDetail"] == "Checking available skills..."
    assert skill_view["visibleDetail"] == "Loading skill: test-paper-skill..."
    assert [event["detail"] for event in skill_view["visibleEvents"]] == [
        "Checking available skills...",
        "Loading skill: test-paper-skill...",
    ]
    assert [item["type"] for item in skill_view["workTrace"]["items"]] == ["skill", "skill"]


def test_progress_unknown_tool_has_visible_fallback_and_tool_result_stays_raw():
    store = AgentProgressStore()

    store.append("req-tool", AgentEvent("tool_call", data={"name": "custom_tool", "arguments": "{}"}))
    snapshot = store.append("req-tool", AgentEvent("tool_result", "Tool completed.", data={"name": "custom_tool"}))

    assert snapshot["visibleDetail"] == "Using custom_tool..."
    assert [event["type"] for event in snapshot["events"]] == ["tool_call", "tool_result"]
    assert [event["detail"] for event in snapshot["visibleEvents"]] == ["Using custom_tool..."]
    assert snapshot["workTrace"]["items"] == [{
        "type": "tool",
        "text": "Using custom_tool...",
        "at": snapshot["workTrace"]["items"][0]["at"],
        "source": "runtime",
    }]


def test_progress_prefers_provider_work_trace_items_for_visible_status():
    store = AgentProgressStore()

    snapshot = store.append("req-work", AgentEvent(
        "work_trace_item",
        "Checked note metadata.",
        {"text": "Checked note metadata.", "trace_type": "summary", "source": "provider"},
    ))

    assert snapshot["visibleDetail"] == "Checked note metadata."
    assert snapshot["visibleEvents"][0]["type"] == "work_trace_item"
    assert snapshot["workTrace"]["items"] == [{
        "type": "summary",
        "text": "Checked note metadata.",
        "at": snapshot["workTrace"]["items"][0]["at"],
        "source": "provider",
    }]
