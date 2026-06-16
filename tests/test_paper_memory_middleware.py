"""Verify durable paper memory updates and provider fallback behavior."""

from __future__ import annotations

from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, SystemMessage

from middleware.paper_memory import (
    PaperMemoryMiddleware,
    paper_memory_path,
    read_paper_memory_file,
)


def test_paper_memory_middleware_skips_before_interval(tmp_path):
    model = FakeMessagesListChatModel(responses=[AIMessage(content="should not be used")])
    middleware = PaperMemoryMiddleware(
        model,
        note_id="note-1",
        session_id="session-1",
        memory_dir=tmp_path,
        update_interval=3,
    )

    updated = middleware.update_memory({
        "messages": [
            HumanMessage(content="What is Figure 1?"),
            AIMessage(content="Figure 1 shows the model overview."),
            HumanMessage(content="What is the main method?"),
            AIMessage(content="The method uses retrieval over paper context."),
        ]
    })

    assert updated is False
    assert not paper_memory_path(tmp_path, "note-1").exists()


def test_paper_memory_middleware_updates_every_configured_user_turns(tmp_path):
    model = FakeMessagesListChatModel(responses=[
        AIMessage(
            content=(
                "# Paper Memory: Graph RAG\n\n"
                "## Stable Paper Context\n\n"
                "- The paper uses a retrieval graph.\n"
            )
        )
    ])
    middleware = PaperMemoryMiddleware(
        model,
        note_id="note 1",
        note_title="Graph RAG",
        session_id="session-1",
        memory_dir=tmp_path,
        update_interval=3,
    )

    updated = middleware.update_memory({
        "messages": [
            HumanMessage(content="What is the paper about?"),
            AIMessage(content="It studies graph-based retrieval."),
            HumanMessage(content="What did Figure 2 explain?"),
            AIMessage(content="Figure 2 explains the retrieval graph."),
            HumanMessage(content="Remember that I am focusing on the graph construction."),
            AIMessage(content="I will keep the graph construction focus in mind."),
        ]
    })

    path = paper_memory_path(tmp_path, "note 1")
    metadata, memory = read_paper_memory_file(path)

    assert updated is True
    assert path.exists()
    assert metadata["note_id"] == "note 1"
    assert metadata["note_title"] == "Graph RAG"
    assert metadata["session_id"] == "session-1"
    assert metadata["last_user_turn_count"] == 3
    assert "retrieval graph" in memory


def test_paper_memory_update_model_receives_system_instructions(tmp_path):
    model = InstructionsRequiredModel()
    middleware = PaperMemoryMiddleware(
        model,
        note_id="note-1",
        session_id="session-1",
        memory_dir=tmp_path,
        update_interval=1,
    )

    updated = middleware.update_memory({
        "messages": [
            HumanMessage(content="Remember my focus on active reconstruction."),
            AIMessage(content="I will keep that focus in mind."),
        ]
    })

    assert updated is True
    assert model.saw_system_message is True


def test_paper_memory_update_model_can_fall_back_to_stream(tmp_path):
    model = StreamOnlyModel()
    middleware = PaperMemoryMiddleware(
        model,
        note_id="note-1",
        session_id="session-1",
        memory_dir=tmp_path,
        update_interval=1,
    )

    updated = middleware.update_memory({
        "messages": [
            HumanMessage(content="Remember my focus on active reconstruction."),
            AIMessage(content="I will keep that focus in mind."),
        ]
    })

    _metadata, memory = read_paper_memory_file(paper_memory_path(tmp_path, "note-1"))
    assert updated is True
    assert model.stream_called is True
    assert "stream saved" in memory


class InstructionsRequiredModel:
    def __init__(self) -> None:
        self.saw_system_message = False

    def invoke(self, messages, config=None):
        del config
        if isinstance(messages, str):
            raise RuntimeError("Instructions are required")
        self.saw_system_message = any(isinstance(message, SystemMessage) for message in messages)
        if not self.saw_system_message:
            raise RuntimeError("Instructions are required")
        return AIMessage(content="# Paper Memory: Test\n\n## Stable Paper Context\n\n- saved")


class StreamOnlyModel(InstructionsRequiredModel):
    def __init__(self) -> None:
        super().__init__()
        self.stream_called = False

    def invoke(self, messages, config=None):
        del messages, config
        raise RuntimeError("Stream must be set to true")

    def stream(self, messages, config=None):
        del config
        self.saw_system_message = any(isinstance(message, SystemMessage) for message in messages)
        self.stream_called = True
        yield AIMessageChunk(content="# Paper Memory: Test\n\n")
        yield AIMessageChunk(content="## Stable Paper Context\n\n- stream saved")
