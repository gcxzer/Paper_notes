from __future__ import annotations

from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage

from app_config import AppConfig
from agent_runtime import run_agent_loop
from middleware import SUMMARY_MESSAGE_PREFIX, SummarizationMiddleware, create_summarization_middleware


def _config_for_checkpoint(path) -> AppConfig:
    return AppConfig(data={"checkpointer": {"type": "sqlite", "path": str(path)}}, path=None)


def test_run_agent_loop_coerces_string_messages(tmp_path) -> None:
    model = FakeMessagesListChatModel(responses=[AIMessage(content="done")])

    chunks = list(
        run_agent_loop(
            model,
            "hello",
            app_config=_config_for_checkpoint(tmp_path / "checkpoints.sqlite"),
            thread_id="coerce-thread",
        )
    )

    assert chunks[-1]["messages"][-1].content == "done"


def test_run_agent_loop_uses_thread_id(tmp_path) -> None:
    model = FakeMessagesListChatModel(responses=[AIMessage(content="remembered")])

    chunks = list(
        run_agent_loop(
            model,
            "hello",
            app_config=_config_for_checkpoint(tmp_path / "checkpoints.sqlite"),
            thread_id="memory-thread",
        )
    )

    assert chunks[-1]["messages"][-1].content == "remembered"


def test_run_agent_loop_uses_sqlite_checkpointer(tmp_path) -> None:
    model = FakeMessagesListChatModel(responses=[AIMessage(content="saved")])

    chunks = list(
        run_agent_loop(
            model,
            "hello",
            app_config=_config_for_checkpoint(tmp_path / "checkpoints.sqlite"),
            thread_id="sqlite-thread",
        )
    )

    assert chunks[-1]["messages"][-1].content == "saved"
    assert (tmp_path / "checkpoints.sqlite").exists()


def test_run_agent_loop_accepts_summarization_middleware(tmp_path) -> None:
    model = FakeMessagesListChatModel(responses=[AIMessage(content="done")])
    summarization = create_summarization_middleware(
        model=model,
        trigger=("messages", 100),
        keep=("messages", 20),
    )

    chunks = list(
        run_agent_loop(
            model,
            "hello",
            app_config=_config_for_checkpoint(tmp_path / "checkpoints.sqlite"),
            middleware=[summarization],
            thread_id="summarization-thread",
        )
    )

    assert chunks[-1]["messages"][-1].content == "done"


def test_create_summarization_middleware_uses_official_defaults() -> None:
    model = FakeMessagesListChatModel(responses=[AIMessage(content="summary")])

    summarization = create_summarization_middleware(model)
    direct = SummarizationMiddleware(model=model)

    assert summarization.trigger == direct.trigger
    assert summarization.keep == direct.keep
    assert summarization.summary_prompt == direct.summary_prompt
    assert summarization.trim_tokens_to_summarize == direct.trim_tokens_to_summarize


def test_summarization_middleware_prefixes_new_summary() -> None:
    model = FakeMessagesListChatModel(responses=[AIMessage(content="compressed history")])
    summarization = create_summarization_middleware(
        model,
        trigger=("messages", 3),
        keep=("messages", 1),
    )

    update = summarization.before_model(
        {
            "messages": [
                HumanMessage(content="first"),
                AIMessage(content="second"),
                HumanMessage(content="third"),
            ]
        },
        runtime=None,
    )

    assert update is not None
    summary_messages = [message for message in update["messages"] if isinstance(message, HumanMessage)]
    assert summary_messages[0].content.startswith(SUMMARY_MESSAGE_PREFIX)


def test_summarization_middleware_preserves_existing_summary_messages() -> None:
    model = FakeMessagesListChatModel(responses=[AIMessage(content="new compressed history")])
    summarization = create_summarization_middleware(
        model,
        trigger=("messages", 4),
        keep=("messages", 1),
    )
    existing_summary = HumanMessage(content=f"{SUMMARY_MESSAGE_PREFIX}\n\nold compressed history")

    update = summarization.before_model(
        {
            "messages": [
                existing_summary,
                HumanMessage(content="first unsummarized message"),
                AIMessage(content="second unsummarized message"),
                HumanMessage(content="recent message"),
            ]
        },
        runtime=None,
    )

    assert update is not None
    messages = update["messages"]
    assert isinstance(messages[0], RemoveMessage)
    assert messages[1] is existing_summary
    assert messages[2].content.startswith(SUMMARY_MESSAGE_PREFIX)
    assert "new compressed history" in messages[2].content
