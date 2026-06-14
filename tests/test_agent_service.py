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
