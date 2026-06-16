"""Verify AgentService session handling and request-to-run wiring."""

from __future__ import annotations

from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage

from agent_runtime import AgentService, AgentServiceRequest
from agent_sessions import AgentSessionStore
from app_config import AppConfig


def test_agent_service_smoke_creates_session(tmp_path):
    config = AppConfig(
        data={
            "models": {
                "default": "main",
                "main": {"provider": "openai", "name": "gpt-5.5", "options": {}},
            },
        },
        path=None,
    )
    store = AgentSessionStore(tmp_path / "sessions")
    model = FakeMessagesListChatModel(responses=[AIMessage(content="ok")])
    service = AgentService(app_config=config, session_store=store, chat_model=model, use_default_tools=False)

    result = service.run(AgentServiceRequest(message="hello", enable_tools=False))

    assert result.created_session is True
    assert result.response == "ok"
    assert store.require_session(result.session_id).metadata.message_count == 2


def test_agent_service_updates_paper_memory_after_configured_interval(tmp_path):
    memory_dir = tmp_path / "paper-memory"
    config = AppConfig(
        data={
            "models": {
                "default": "main",
                "main": {"provider": "openai", "name": "gpt-5.5", "options": {}},
            },
            "paper_memory": {
                "dir": str(memory_dir),
                "update_interval": 1,
            },
        },
        path=None,
    )
    store = AgentSessionStore(tmp_path / "sessions")
    model = FakeMessagesListChatModel(responses=[
        AIMessage(content="The paper is about graph retrieval."),
        AIMessage(content="# Paper Memory: Graph RAG\n\n## Stable Paper Context\n\n- Graph retrieval matters."),
    ])
    service = AgentService(app_config=config, session_store=store, chat_model=model, use_default_tools=False)

    result = service.run(AgentServiceRequest(
        message="What is this paper about?",
        note_id="note-1",
        title="Graph RAG chat",
        metadata={"currentNoteTitle": "Graph RAG"},
        enable_tools=False,
    ))

    memory_file = memory_dir / "note-1.md"
    assert result.response == "The paper is about graph retrieval."
    assert memory_file.exists()
    assert "Graph retrieval matters" in memory_file.read_text(encoding="utf-8")
