from __future__ import annotations

from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage

from agent_runtime import ATTACHMENT_ONLY_MESSAGE, AgentService, AgentServiceRequest
from agent_sessions import AgentSessionStore
from app_config import AppConfig


def _config() -> AppConfig:
    return AppConfig(
        data={
            "models": {
                "default": "main",
                "main": {
                    "provider": "openai",
                    "name": "gpt-5.5",
                    "options": {},
                },
            },
        },
        path=None,
    )


def test_agent_service_creates_session_and_persists_transcript(tmp_path):
    store = AgentSessionStore(tmp_path / "sessions")
    model = FakeMessagesListChatModel(responses=[AIMessage(content="Hello from LangChain.")])
    service = AgentService(app_config=_config(), session_store=store, chat_model=model, use_default_tools=False)

    result = service.run(AgentServiceRequest(message="Hello", title="Paper chat", enable_tools=False))

    assert result.created_session is True
    assert result.response == "Hello from LangChain."
    assert result.session.metadata.title == "Paper chat"
    assert result.session.metadata.provider == "openai"
    assert result.session.metadata.model == "gpt-5.5"
    assert [message["role"] for message in result.messages] == ["user", "assistant"]
    assert [message["content"] for message in result.messages] == ["Hello", "Hello from LangChain."]
    assert store.require_session(result.session_id).messages == result.messages


def test_agent_service_continues_existing_session(tmp_path):
    store = AgentSessionStore(tmp_path / "sessions")
    model = FakeMessagesListChatModel(
        responses=[
            AIMessage(content="First answer."),
            AIMessage(content="Second answer."),
        ]
    )
    service = AgentService(app_config=_config(), session_store=store, chat_model=model, use_default_tools=False)

    first = service.run(AgentServiceRequest(message="First question", title="Continuity", enable_tools=False))
    second = service.run(AgentServiceRequest(message="Second question", session_id=first.session_id, enable_tools=False))

    assert second.created_session is False
    assert [message["content"] for message in second.messages] == [
        "First question",
        "First answer.",
        "Second question",
        "Second answer.",
    ]
    assert store.require_session(first.session_id).metadata.message_count == 4


def test_agent_service_uses_attachment_fallback_for_empty_message(tmp_path):
    store = AgentSessionStore(tmp_path / "sessions")
    model = FakeMessagesListChatModel(responses=[AIMessage(content="Read the attachment.")])
    service = AgentService(app_config=_config(), session_store=store, chat_model=model, use_default_tools=False)

    result = service.run(AgentServiceRequest(message="", title="Attachment", enable_tools=False))

    assert result.messages[0]["content"] == ATTACHMENT_ONLY_MESSAGE
    assert result.response == "Read the attachment."


def test_agent_service_request_model_overrides_session_metadata(tmp_path):
    store = AgentSessionStore(tmp_path / "sessions")
    model = FakeMessagesListChatModel(responses=[AIMessage(content="Using requested model.")])
    service = AgentService(app_config=_config(), session_store=store, chat_model=model, use_default_tools=False)

    result = service.run(
        AgentServiceRequest(
            message="Use Claude",
            provider="anthropic",
            model="claude-sonnet-4-6",
            enable_tools=False,
        )
    )

    assert result.session.metadata.provider == "anthropic"
    assert result.session.metadata.model == "claude-sonnet-4-6"


def test_agent_service_context_status_uses_model_profile_and_reserve(tmp_path):
    store = AgentSessionStore(tmp_path / "sessions")
    model = FakeMessagesListChatModel(responses=[AIMessage(content="Context answer.")])
    service = AgentService(app_config=_config(), session_store=store, chat_model=model, use_default_tools=False)
    result = service.run(AgentServiceRequest(message="Measure context", enable_tools=False))

    status = service.context_status(session_id=result.session_id, enable_tools=False)

    assert status.provider == "openai"
    assert status.model == "gpt-5.5"
    assert status.context_window == 1_050_000
    assert status.reserve_tokens == 20_000
    assert status.collapse_trigger_tokens == 1_030_000
    assert status.compaction_trigger_tokens == 1_030_000
    assert status.remaining_tokens == status.context_window - status.estimated_tokens
    assert status.message_count == 2
