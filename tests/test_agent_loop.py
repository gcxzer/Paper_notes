from __future__ import annotations

from types import SimpleNamespace

from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage, SystemMessage, ToolMessage

from agent_runtime import run_agent_loop
from agent_runtime.agent_loop import with_context_management
from agent_runtime.messages import messages_from_transcript
from app_config import AppConfig
from middleware import (
    SUMMARY_MESSAGE_PREFIX,
    ContextCollapseMiddleware,
    ContextCompactionMiddleware,
    PaperMemoryMiddleware,
    RagToolSerializationMiddleware,
    SummarizationMiddleware,
    ToolCallLimitMiddleware,
    ToolOutputPlaceholderMiddleware,
    ToolOutputTruncationMiddleware,
    compaction_trigger_tokens,
    create_context_collapse_middleware,
    create_tool_call_limit_middleware,
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


def test_context_management_inserts_message_based_collapse_middleware() -> None:
    model = FakeMessagesListChatModel(responses=[AIMessage(content="done")])
    app_config = AppConfig(
        data={
            "models": {"default": "main", "main": {"provider": "openai", "name": "gpt-5.5"}},
            "context_collapse": {"trigger_messages": 12, "trigger_tokens": 40_000},
        },
        path=None,
    )

    middleware = with_context_management(model=model, middleware=None, app_config=app_config)

    collapse = next(item for item in middleware if isinstance(item, ContextCollapseMiddleware))
    assert collapse.trigger == [("messages", 12), ("tokens", 40_000)]
    assert collapse.keep == ("messages", 1)
    assert collapse.keep_to_previous_user_question is True


def test_context_management_inserts_tool_output_middleware(tmp_path) -> None:
    model = FakeMessagesListChatModel(responses=[AIMessage(content="done")])
    app_config = AppConfig(
        data={
            "models": {"default": "main", "main": {"provider": "openai", "name": "gpt-5.5"}},
            "tool_output": {
                "root_dir": str(tmp_path / "tool-outputs"),
                "default_max_tokens": 1234,
                "placeholder_keep_recent": 3,
                "tool_limits": {"inspect_paper_visuals": 4321},
            },
        },
        path=None,
    )

    middleware = with_context_management(model=model, middleware=None, app_config=app_config)

    truncation = next(item for item in middleware if isinstance(item, ToolOutputTruncationMiddleware))
    placeholder = next(item for item in middleware if isinstance(item, ToolOutputPlaceholderMiddleware))
    assert middleware.index(truncation) < middleware.index(placeholder)
    assert truncation.root_dir == (tmp_path / "tool-outputs").resolve()
    assert truncation.default_max_tokens == 1234
    assert truncation.tool_limits == {"inspect_paper_visuals": 4321}
    assert placeholder.keep_recent == 3


def test_context_management_inserts_tool_call_limit_middleware() -> None:
    model = FakeMessagesListChatModel(responses=[AIMessage(content="done")])
    app_config = AppConfig(
        data={
            "models": {"default": "main", "main": {"provider": "openai", "name": "gpt-5.5"}},
            "tool_call_limit": {
                "enabled": True,
                "limits": [
                    {
                        "tool_name": "query_paper_content",
                        "run_limit": 4,
                        "exit_behavior": "continue",
                    }
                ],
            },
        },
        path=None,
    )

    middleware = with_context_management(model=model, middleware=None, app_config=app_config)

    limiter = next(item for item in middleware if isinstance(item, ToolCallLimitMiddleware))
    assert limiter.tool_name == "query_paper_content"
    assert limiter.run_limit == 4
    assert limiter.thread_limit is None
    assert limiter.exit_behavior == "continue"


def test_context_management_inserts_paper_memory_middleware(tmp_path) -> None:
    model = FakeMessagesListChatModel(responses=[AIMessage(content="done")])
    memory_dir = tmp_path / "paper-memory"
    app_config = AppConfig(
        data={
            "models": {"default": "main", "main": {"provider": "openai", "name": "gpt-5.5"}},
            "paper_memory": {
                "dir": str(memory_dir),
                "update_interval": 2,
            },
        },
        path=None,
    )

    middleware = with_context_management(
        model=model,
        middleware=None,
        app_config=app_config,
        paper_memory_context={
            "note_id": "note-1",
            "note_title": "Graph RAG",
            "session_id": "session-1",
        },
    )

    paper_memory = next(item for item in middleware if isinstance(item, PaperMemoryMiddleware))
    assert paper_memory.note_id == "note-1"
    assert paper_memory.note_title == "Graph RAG"
    assert paper_memory.session_id == "session-1"
    assert paper_memory.memory_dir == memory_dir
    assert paper_memory.update_interval == 2


def test_context_management_inserts_rag_tool_serialization_middleware() -> None:
    model = FakeMessagesListChatModel(responses=[AIMessage(content="done")])
    app_config = AppConfig(
        data={
            "models": {"default": "main", "main": {"provider": "openai", "name": "gpt-5.5"}},
            "rag_tool_serialization": {"tool_names": ["query_paper_content"]},
        },
        path=None,
    )

    middleware = with_context_management(model=model, middleware=None, app_config=app_config)

    serializer = next(item for item in middleware if isinstance(item, RagToolSerializationMiddleware))
    assert serializer.tool_names == ("query_paper_content",)


def test_tool_call_limit_middleware_blocks_excess_tool_calls() -> None:
    middleware = create_tool_call_limit_middleware(
        tool_name="query_paper_content",
        run_limit=1,
        exit_behavior="continue",
    )

    update = middleware.after_model(
        {
            "messages": [
                AIMessage(
                    content="",
                    tool_calls=[
                        {"name": "query_paper_content", "args": {}, "id": "call-1", "type": "tool_call"},
                        {"name": "query_paper_content", "args": {}, "id": "call-2", "type": "tool_call"},
                    ],
                )
            ]
        },
        runtime=None,
    )

    assert update is not None
    assert update["thread_tool_call_count"]["query_paper_content"] == 1
    assert update["run_tool_call_count"]["query_paper_content"] == 2
    blocked = update["messages"]
    assert len(blocked) == 1
    assert isinstance(blocked[0], ToolMessage)
    assert blocked[0].tool_call_id == "call-2"
    assert blocked[0].status == "error"


def test_tool_output_truncation_middleware_writes_oversized_outputs(tmp_path) -> None:
    middleware = ToolOutputTruncationMiddleware(
        root_dir=tmp_path,
        default_max_tokens=160,
        tool_limits={"large_tool": 160},
    )
    content = "0123456789 " * 200
    request = SimpleNamespace(
        tool=SimpleNamespace(name="large_tool"),
        tool_call={"name": "large_tool", "id": "call-1"},
    )

    result = middleware.wrap_tool_call(
        request,
        lambda _request: ToolMessage(content=content, tool_call_id="call-1"),
    )

    saved_files = list(tmp_path.glob("*.txt"))
    assert len(saved_files) == 1
    assert saved_files[0].read_text(encoding="utf-8") == content
    assert isinstance(result, ToolMessage)
    assert f"Full output path: {saved_files[0]}" in result.content
    assert "Estimated tokens:" in result.content
    assert "Beginning of output:" in result.content
    assert "01234567" in result.content
    assert content not in result.content


def test_tool_output_placeholder_middleware_omits_old_outputs() -> None:
    middleware = ToolOutputPlaceholderMiddleware(keep_recent=2)
    old = ToolMessage(
        content="Full output path: /tmp/full-output.txt\n" + ("old output " * 100),
        name="inspect_paper_visuals",
        tool_call_id="old-call",
    )
    middle = ToolMessage(content="middle output", name="get_paper_context", tool_call_id="middle-call")
    recent = ToolMessage(content="recent output", name="write_note", tool_call_id="recent-call")

    update = middleware.before_model(
        {"messages": [HumanMessage(content="question"), old, middle, recent]},
        runtime=None,
    )

    assert update is not None
    messages = update["messages"]
    assert isinstance(messages[0], RemoveMessage)
    replaced_old = messages[2]
    assert isinstance(replaced_old, ToolMessage)
    assert replaced_old.tool_call_id == "old-call"
    assert replaced_old.content.startswith("[tool output omitted]")
    assert "Full output path: /tmp/full-output.txt" in replaced_old.content
    assert "old output old output" not in replaced_old.content
    assert messages[3:] == [middle, recent]


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


def test_context_collapse_middleware_can_keep_to_previous_user_question() -> None:
    model = FakeMessagesListChatModel(responses=[AIMessage(content="older compressed history")])
    collapse = create_context_collapse_middleware(
        model,
        trigger=("messages", 5),
        keep=("messages", 1),
        keep_to_previous_user_question=True,
    )
    previous_question = HumanMessage(content="previous user question")
    previous_answer = AIMessage(content="previous assistant answer")
    current_question = HumanMessage(content="current user question")

    update = collapse.before_model(
        {
            "messages": [
                HumanMessage(content="old user question"),
                AIMessage(content="old assistant answer"),
                previous_question,
                previous_answer,
                current_question,
            ]
        },
        runtime=None,
    )

    assert update is not None
    messages = update["messages"]
    assert isinstance(messages[0], RemoveMessage)
    assert messages[1].content.startswith(SUMMARY_MESSAGE_PREFIX)
    assert messages[2:] == [previous_question, previous_answer, current_question]


def test_context_collapse_middleware_does_not_summarize_only_user_question() -> None:
    model = FakeMessagesListChatModel(responses=[AIMessage(content="older compressed history")])
    collapse = create_context_collapse_middleware(
        model,
        trigger=("messages", 5),
        keep=("messages", 1),
        keep_to_previous_user_question=True,
    )

    update = collapse.before_model(
        {
            "messages": [
                HumanMessage(content="current user question"),
                AIMessage(content="", tool_calls=[{"name": "query_paper_content", "args": {}, "id": "call-1"}]),
                ToolMessage(content="large result", tool_call_id="call-1"),
                AIMessage(content="", tool_calls=[{"name": "query_paper_content", "args": {}, "id": "call-2"}]),
                ToolMessage(content="another large result", tool_call_id="call-2"),
            ]
        },
        runtime=None,
    )

    assert update is None


def test_summary_transcript_messages_are_model_context_not_user_input() -> None:
    messages = messages_from_transcript([
        {"role": "summary", "content": f"{SUMMARY_MESSAGE_PREFIX}\n\ncompressed"},
        {"role": "user", "content": f"{SUMMARY_MESSAGE_PREFIX}\n\nlegacy compressed"},
        {"role": "user", "content": "current question"},
    ])

    assert isinstance(messages[0], SystemMessage)
    assert isinstance(messages[1], SystemMessage)
    assert isinstance(messages[2], HumanMessage)


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
    assert compaction_trigger_tokens(400_000) == 387_000
    assert compaction_trigger_tokens(128_000, reserve_tokens=20_000) == 108_000


def test_context_compaction_middleware_compacts_history_before_previous_user_message() -> None:
    model = FakeMessagesListChatModel(responses=[AIMessage(content="dense summary")])
    compaction = ContextCompactionMiddleware(
        model,
        context_window=100,
        reserve_tokens=20,
        token_counter=lambda messages: 100,
    )
    old_summary = HumanMessage(content=f"{SUMMARY_MESSAGE_PREFIX}\n\nold summary")
    old_question = HumanMessage(content="old question")
    old_answer = AIMessage(content="old answer")
    previous_question = HumanMessage(content="previous question")
    previous_answer = AIMessage(content="previous answer")
    current_question = HumanMessage(content="current question")

    update = compaction.before_model(
        {
            "messages": [
                old_summary,
                old_question,
                old_answer,
                previous_question,
                previous_answer,
                current_question,
            ]
        },
        runtime=None,
    )

    assert update is not None
    messages = update["messages"]
    assert isinstance(messages[0], RemoveMessage)
    assert messages[1].content.startswith(SUMMARY_MESSAGE_PREFIX)
    assert "dense summary" in messages[1].content
    assert messages[2:] == [previous_question, previous_answer, current_question]
