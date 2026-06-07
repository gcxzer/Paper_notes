from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(slots=True)
class MemoryItem:
    memory_id: str
    content: str
    kind: str = "fact"
    note_id: str = ""
    session_id: str = ""
    created_at: str = ""
    updated_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "memory_id": self.memory_id,
            "content": self.content,
            "kind": self.kind,
            "note_id": self.note_id,
            "session_id": self.session_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MemoryItem:
        return cls(
            memory_id=str(data.get("memory_id") or ""),
            content=str(data.get("content") or ""),
            kind=str(data.get("kind") or "fact"),
            note_id=str(data.get("note_id") or ""),
            session_id=str(data.get("session_id") or ""),
            created_at=str(data.get("created_at") or ""),
            updated_at=str(data.get("updated_at") or ""),
            metadata=dict(data.get("metadata") or {}),
        )


class MemoryProvider(Protocol):
    """Small local version of Hermes' MemoryProvider lifecycle."""

    @property
    def name(self) -> str:
        ...

    def prefetch(
        self,
        query: str,
        *,
        session_id: str = "",
        note_id: str = "",
        limit: int = 5,
    ) -> str:
        ...

    def sync_turn(
        self,
        user_content: str,
        assistant_content: str,
        *,
        session_id: str = "",
        note_id: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> MemoryItem | None:
        ...

    def search(self, query: str, *, note_id: str = "", limit: int = 5) -> list[MemoryItem]:
        ...
