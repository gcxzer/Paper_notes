from __future__ import annotations

from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage

from agent_runtime import run_agent_loop
from middleware import (
    SUMMARY_MESSAGE_PREFIX,
    ContextCompactionMiddleware,
    SummarizationMiddleware,
    compaction_trigger_tokens,
    create_context_collapse_middleware,
)


def test_run_agent_loop_coerces_string_messages(tmp_path) -> None:
    model = FakeMessagesListChatModel(responses=[AIMessage(content="done")])

    chunks = list(
        run_agent_loop(
            model,
            "hello",
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
            thread_id="memory-thread",
        )
    )

    assert chunks[-1]["messages"][-1].content == "remembered"


def test_run_agent_loop_does_not_create_sqlite_checkpoint(tmp_path) -> None:
    model = FakeMessagesListChatModel(responses=[AIMessage(content="saved")])
    checkpoint_path = tmp_path / "checkpoints.sqlite"

    chunks = list(
        run_agent_loop(
            model,
            "hello",
            thread_id="jsonl-session-thread",
        )
    )

    assert chunks[-1]["messages"][-1].content == "saved"
    assert not checkpoint_path.exists()


def test_run_agent_loop_accepts_context_collapse_middleware(tmp_path) -> None:
    model = FakeMessagesListChatModel(responses=[AIMessage(content="done")])
    collapse = create_context_collapse_middleware(
        model=model,
        trigger=("messages", 100),
        keep=("messages", 20),
    )

    chunks = list(
        run_agent_loop(
            model,
            "hello",
            middleware=[collapse],
            thread_id="context-collapse-thread",
        )
    )

    assert chunks[-1]["messages"][-1].content == "done"


def test_create_context_collapse_middleware_uses_official_defaults() -> None:
    model = FakeMessagesListChatModel(responses=[AIMessage(content="summary")])

    collapse = create_context_collapse_middleware(model)
    direct = SummarizationMiddleware(model=model)

    assert collapse.trigger == direct.trigger
    assert collapse.keep == direct.keep
    assert collapse.summary_prompt == direct.summary_prompt
    assert collapse.trim_tokens_to_summarize == direct.trim_tokens_to_summarize


def test_context_collapse_middleware_prefixes_new_summary() -> None:
    model = FakeMessagesListChatModel(responses=[AIMessage(content="compressed history")])
    collapse = create_context_collapse_middleware(
        model,
        trigger=("messages", 3),
        keep=("messages", 1),
    )

    update = collapse.before_model(
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


def test_context_collapse_middleware_preserves_existing_summary_messages() -> None:
    model = FakeMessagesListChatModel(responses=[AIMessage(content="new compressed history")])
    collapse = create_context_collapse_middleware(
        model,
        trigger=("messages", 4),
        keep=("messages", 1),
    )
    existing_summary = HumanMessage(content=f"{SUMMARY_MESSAGE_PREFIX}\n\nold compressed history")

    update = collapse.before_model(
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


def test_compaction_trigger_tokens_reserves_context_space() -> None:
    assert compaction_trigger_tokens(400_000) == 380_000
    assert compaction_trigger_tokens(128_000, reserve_tokens=20_000) == 108_000


def test_context_compaction_middleware_compacts_existing_summaries() -> None:
    model = FakeMessagesListChatModel(responses=[AIMessage(content="dense summary")])
    compaction = ContextCompactionMiddleware(
        model,
        context_window=100,
        reserve_tokens=20,
        token_counter=lambda messages: 100,
    )
    recent_message = HumanMessage(content="recent question")

    update = compaction.before_model(
        {
            "messages": [
                HumanMessage(content=f"{SUMMARY_MESSAGE_PREFIX}\n\nold summary"),
                HumanMessage(content=f"{SUMMARY_MESSAGE_PREFIX}\n\nnewer summary"),
                recent_message,
            ]
        },
        runtime=None,
    )

    assert update is not None
    messages = update["messages"]
    assert isinstance(messages[0], RemoveMessage)
    assert messages[1].content.startswith(SUMMARY_MESSAGE_PREFIX)
    assert "dense summary" in messages[1].content
    assert messages[2] is recent_message
