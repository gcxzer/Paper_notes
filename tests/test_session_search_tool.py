from __future__ import annotations

from agent_sessions import AgentSessionStore
from tools.registry import ToolRegistry
from tools.session_search import register_session_search_tool, session_search


def test_session_search_lists_recent_sessions_and_excludes_current(tmp_path):
    store = AgentSessionStore(tmp_path / "sessions")
    first = store.create_session(title="First chat")
    store.append_message(first.metadata.session_id, {"role": "user", "content": "Discussed runtime lifecycle."})
    current = store.create_session(title="Current chat")
    store.append_message(current.metadata.session_id, {"role": "user", "content": "Current request."})

    result = session_search({}, session_store=store, current_session_id=current.metadata.session_id)

    assert result["mode"] == "recent"
    assert result["count"] == 1
    assert result["results"][0]["session_id"] == first.metadata.session_id
    assert "runtime lifecycle" in result["results"][0]["preview"]


def test_session_search_finds_matching_transcript_excerpts(tmp_path):
    store = AgentSessionStore(tmp_path / "sessions")
    first = store.create_session(title="Agent architecture")
    store.append_message(first.metadata.session_id, {"role": "user", "content": "We decided memory should not store task progress."})
    store.append_message(first.metadata.session_id, {"role": "assistant", "content": "Use session_search for prior decisions."})
    second = store.create_session(title="Other")
    store.append_message(second.metadata.session_id, {"role": "user", "content": "Unrelated note."})

    result = session_search({"query": "memory progress", "limit": 3}, session_store=store)

    assert result["mode"] == "search"
    assert result["count"] == 1
    assert result["recap"].startswith("Focused recap")
    assert result["results"][0]["session_id"] == first.metadata.session_id
    assert "memory should not store task progress" in result["results"][0]["matches"][0]["excerpt"]


def test_session_search_can_use_provider_backed_recap_hook(tmp_path):
    store = AgentSessionStore(tmp_path / "sessions")
    session = store.create_session(title="Agent architecture")
    store.append_message(session.metadata.session_id, {"role": "user", "content": "We decided memory should freeze per session."})

    result = session_search(
        {"query": "memory freeze", "include_recap": True},
        session_store=store,
        recap_provider=lambda query, results: f"LLM recap for {query}: {results[0]['title']}",
    )

    assert result["recap"] == "LLM recap for memory freeze: Agent architecture"


def test_register_session_search_tool_uses_current_session_provider(tmp_path):
    store = AgentSessionStore(tmp_path / "sessions")
    previous = store.create_session(title="Previous")
    store.append_message(previous.metadata.session_id, {"role": "user", "content": "Worked on provider factory."})
    current = store.create_session(title="Current")
    registry = ToolRegistry()

    register_session_search_tool(
        registry,
        session_store=store,
        current_session_id_provider=lambda: current.metadata.session_id,
    )
    result = registry.dispatch("session_search", {"query": "provider"})

    assert result.is_error is False
    assert previous.metadata.session_id in result.content
    assert current.metadata.session_id not in result.content
