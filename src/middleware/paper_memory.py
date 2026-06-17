"""Update current-paper durable memory after enough conversation turns."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain.chat_models import init_chat_model
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from app_infra.content import content_text
from memory import (
    PAPER_MEMORY_DIR,
    paper_memory_path,
    read_paper_memory_file,
    write_paper_memory_file,
)

__all__ = [
    "DEFAULT_PAPER_MEMORY_UPDATE_INTERVAL",
    "PaperMemoryMiddleware",
    "create_paper_memory_middleware",
    "paper_memory_path",
    "read_paper_memory_file",
]

DEFAULT_PAPER_MEMORY_UPDATE_INTERVAL = 3
DEFAULT_PAPER_MEMORY_MAX_CONVERSATION_CHARS = 60_000
DEFAULT_PAPER_MEMORY_MAX_EXISTING_CHARS = 40_000

PAPER_MEMORY_UPDATE_PROMPT = """You are updating a durable paper-specific memory file for Paper Notes.

This memory is for future conversations about one paper or note. It is not a transcript summary. Preserve stable, useful context learned from the conversation, especially:
- what the paper is about,
- concepts, methods, figures, tables, or equations the user asked about,
- explanations or interpretations that were useful,
- the user's reading focus, confusions, or open questions,
- follow-up pointers that would help the next conversation resume quickly.

Do not invent paper facts. Do not include API keys, tokens, passwords, credentials, or private secrets. Do not save generic codebase details, temporary task state, or information unrelated to this paper.
If existing memory conflicts with the latest conversation, update it. If there is little new durable information, keep the memory concise and preserve the existing useful content.

Paper note:
- note id: {note_id}
- title: {note_title}

Existing paper memory:
<existing_memory>
{existing_memory}
</existing_memory>

Recent conversation:
<conversation>
{conversation}
</conversation>

Return only Markdown for the memory body using this structure:

# Paper Memory: {heading}

## Stable Paper Context

## User Reading Focus

## Discussed Details

## Open Questions

## Useful Pointers
"""


class PaperMemoryMiddleware(AgentMiddleware):
    def __init__(
        self,
        model: str | BaseChatModel,
        *,
        note_id: str,
        note_title: str = "",
        session_id: str = "",
        memory_dir: Path | None = None,
        update_interval: int = DEFAULT_PAPER_MEMORY_UPDATE_INTERVAL,
        max_conversation_chars: int = DEFAULT_PAPER_MEMORY_MAX_CONVERSATION_CHARS,
        max_existing_chars: int = DEFAULT_PAPER_MEMORY_MAX_EXISTING_CHARS,
        update_prompt: str = PAPER_MEMORY_UPDATE_PROMPT,
    ) -> None:
        super().__init__()
        self.model = init_chat_model(model) if isinstance(model, str) else model
        self.note_id = str(note_id or "").strip()
        self.note_title = str(note_title or "").strip()
        self.session_id = str(session_id or "").strip()
        self.memory_dir = Path(memory_dir or PAPER_MEMORY_DIR)
        self.update_interval = max(1, int(update_interval or DEFAULT_PAPER_MEMORY_UPDATE_INTERVAL))
        self.max_conversation_chars = max(1_000, int(max_conversation_chars or DEFAULT_PAPER_MEMORY_MAX_CONVERSATION_CHARS))
        self.max_existing_chars = max(1_000, int(max_existing_chars or DEFAULT_PAPER_MEMORY_MAX_EXISTING_CHARS))
        self.update_prompt = update_prompt

    def after_agent(self, state: dict[str, Any], runtime: Any) -> dict[str, Any] | None:
        self.update_memory(state)
        return None

    async def aafter_agent(self, state: dict[str, Any], runtime: Any) -> dict[str, Any] | None:
        self.update_memory(state)
        return None

    def update_memory(self, state: dict[str, Any]) -> bool:
        if not self.note_id:
            return False
        messages = [message for message in state.get("messages", []) if isinstance(message, BaseMessage)]
        if not messages:
            return False
        user_turn_count = _user_turn_count(messages)
        if user_turn_count <= 0:
            return False

        path = paper_memory_path(self.memory_dir, self.note_id)
        metadata, existing_memory = read_paper_memory_file(path)
        if not self._should_update(user_turn_count, metadata):
            return False

        conversation = format_conversation_for_memory(messages, max_chars=self.max_conversation_chars)
        if not conversation:
            return False
        updated_memory = self._create_updated_memory(existing_memory, conversation)
        if not updated_memory:
            return False

        write_paper_memory_file(
            path,
            updated_memory,
            metadata={
                "note_id": self.note_id,
                "note_title": self.note_title,
                "session_id": self.session_id,
                "last_user_turn_count": user_turn_count,
            },
        )
        return True

    def _should_update(self, user_turn_count: int, metadata: dict[str, Any]) -> bool:
        if str(metadata.get("session_id") or "") != self.session_id:
            previous_count = 0
        else:
            previous_count = _int_value(metadata.get("last_user_turn_count"))
        return user_turn_count - previous_count >= self.update_interval

    def _create_updated_memory(self, existing_memory: str, conversation: str) -> str:
        existing = _truncate_text(existing_memory, self.max_existing_chars) or "No existing paper memory."
        prompt = self.update_prompt.format(
            note_id=self.note_id,
            note_title=self.note_title or "Untitled paper",
            heading=self.note_title or self.note_id,
            existing_memory=existing,
            conversation=conversation,
        ).rstrip()
        messages = [
            SystemMessage(content=(
                "You update durable paper-specific memory files for Paper Notes. "
                "Return only the updated Markdown memory body."
            )),
            HumanMessage(content=prompt),
        ]
        try:
            return _invoke_memory_update_model(self.model, messages).strip()
        except Exception:
            return ""


def create_paper_memory_middleware(
    model: str | BaseChatModel,
    *,
    note_id: str,
    note_title: str = "",
    session_id: str = "",
    memory_dir: Path | None = None,
    update_interval: int = DEFAULT_PAPER_MEMORY_UPDATE_INTERVAL,
) -> PaperMemoryMiddleware:
    return PaperMemoryMiddleware(
        model=model,
        note_id=note_id,
        note_title=note_title,
        session_id=session_id,
        memory_dir=memory_dir,
        update_interval=update_interval,
    )


def format_conversation_for_memory(messages: list[BaseMessage], *, max_chars: int) -> str:
    lines: list[str] = []
    for message in messages:
        if isinstance(message, HumanMessage):
            role = "User"
        elif isinstance(message, AIMessage):
            if getattr(message, "tool_calls", None):
                continue
            role = "Assistant"
        else:
            continue
        text = content_text(message.content).strip()
        if not text:
            continue
        lines.append(f"{role}: {text}")
    return _truncate_text("\n\n".join(lines), max_chars)


def _invoke_memory_update_model(model: Any, messages: list[BaseMessage]) -> str:
    config = {"metadata": {"lc_source": "paper_memory_update"}}
    try:
        response = model.invoke(messages, config=config)
    except Exception as error:
        if "stream must be set to true" not in str(error).lower():
            raise
        stream = getattr(model, "stream", None)
        if not callable(stream):
            raise
        return _stream_response_text(stream(messages, config=config))
    return _response_text(response)


def _stream_response_text(chunks: Any) -> str:
    parts: list[str] = []
    last_chunk: Any = None
    for chunk in chunks:
        last_chunk = chunk
        text = _response_text(chunk)
        if text:
            parts.append(text)
    return "".join(parts) or _response_text(last_chunk)


def _user_turn_count(messages: list[BaseMessage]) -> int:
    return sum(1 for message in messages if isinstance(message, HumanMessage))


def _response_text(response: Any) -> str:
    if hasattr(response, "content"):
        return content_text(getattr(response, "content"))
    text = getattr(response, "text", None)
    if callable(text):
        try:
            return str(text() or "")
        except Exception:
            return ""
    return str(text or response or "")


def _truncate_text(text: str, max_chars: int) -> str:
    clean = str(text or "").strip()
    if len(clean) <= max_chars:
        return clean
    return f"{clean[-max_chars:].lstrip()}\n\n[Earlier content truncated.]"


def _int_value(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0

