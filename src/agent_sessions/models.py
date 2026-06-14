from __future__ import annotations

import copy
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

SESSION_STATES = {"active", "archived", "trashed"}


def normalize_session_state(value: Any, *, archived: bool = False) -> str:
    state = str(value or "").strip().lower()
    if state in SESSION_STATES:
        return state
    return "trashed" if archived else "active"


def now_iso(now: datetime | None = None) -> str:
    value = now or datetime.now().astimezone()
    return value.isoformat(timespec="seconds")


def date_bucket_for(value: datetime | str | None = None) -> str:
    if isinstance(value, datetime):
        date_value = value
    elif isinstance(value, str) and value:
        try:
            date_value = datetime.fromisoformat(value)
        except ValueError:
            date_value = datetime.now().astimezone()
    else:
        date_value = datetime.now().astimezone()
    return date_value.strftime("%d_%m_%Y")


def metadata_with_note_scope(metadata: dict[str, Any], note_id: str | None) -> dict[str, Any]:
    if note_id and not (metadata.get("originNoteId") or metadata.get("origin_note_id")):
        metadata["originNoteId"] = note_id
        metadata["origin_note_id"] = note_id
    if note_id and not (metadata.get("currentNoteId") or metadata.get("current_note_id")):
        metadata["currentNoteId"] = note_id
        metadata["current_note_id"] = note_id
    return metadata


@dataclass(slots=True)
class AgentTranscriptMessage:
    role: str
    content: Any = ""
    created_at: str = field(default_factory=now_iso)
    name: str | None = None
    tool_call_id: str | None = None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict, repr=False)

    def to_dict(self) -> dict[str, Any]:
        data = copy.deepcopy(self.extra)
        data.update({
            "role": self.role,
            "content": self.content,
            "created_at": self.created_at,
        })
        if self.name:
            data["name"] = self.name
        if self.tool_call_id:
            data["tool_call_id"] = self.tool_call_id
        if self.tool_calls:
            data["tool_calls"] = copy.deepcopy(self.tool_calls)
        if self.metadata:
            data["metadata"] = copy.deepcopy(self.metadata)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AgentTranscriptMessage:
        known = {
            "role",
            "content",
            "created_at",
            "name",
            "tool_call_id",
            "tool_calls",
            "metadata",
        }
        extra = {key: copy.deepcopy(value) for key, value in data.items() if key not in known}
        return cls(
            role=str(data.get("role") or ""),
            content=copy.deepcopy(data.get("content", "")),
            created_at=str(data.get("created_at") or now_iso()),
            name=data.get("name"),
            tool_call_id=data.get("tool_call_id"),
            tool_calls=copy.deepcopy(data.get("tool_calls") or []),
            metadata=copy.deepcopy(data.get("metadata") or {}),
            extra=extra,
        )


@dataclass(slots=True)
class AgentSessionMetadata:
    session_id: str
    title: str
    created_at: str
    updated_at: str
    date_bucket: str
    note_id: str | None = None
    provider: str | None = None
    model: str | None = None
    message_count: int = 0
    archived: bool = False
    state: str = "active"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        state = normalize_session_state(self.state, archived=self.archived)
        return {
            "session_id": self.session_id,
            "title": self.title,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "date_bucket": self.date_bucket,
            "note_id": self.note_id,
            "provider": self.provider,
            "model": self.model,
            "message_count": self.message_count,
            "archived": state == "archived",
            "state": state,
            "metadata": copy.deepcopy(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AgentSessionMetadata:
        created_at = str(data.get("created_at") or now_iso())
        legacy_archived = bool(data.get("archived", False))
        state = normalize_session_state(data.get("state"), archived=legacy_archived)
        note_id = data.get("note_id")
        metadata = metadata_with_note_scope(copy.deepcopy(data.get("metadata") or {}), note_id)
        return cls(
            session_id=str(data["session_id"]),
            title=str(data.get("title") or "New chat"),
            created_at=created_at,
            updated_at=str(data.get("updated_at") or created_at),
            date_bucket=str(data.get("date_bucket") or date_bucket_for(created_at)),
            note_id=note_id,
            provider=data.get("provider"),
            model=data.get("model"),
            message_count=int(data.get("message_count") or 0),
            archived=state == "archived",
            state=state,
            metadata=metadata,
        )


@dataclass(slots=True)
class AgentSession:
    metadata: AgentSessionMetadata
    messages: list[dict[str, Any]] = field(default_factory=list)


class SessionNotFoundError(KeyError):
    def __init__(self, session_id: str) -> None:
        super().__init__(f"Agent session not found: {session_id}")
        self.session_id = session_id
