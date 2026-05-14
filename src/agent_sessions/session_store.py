from __future__ import annotations

import threading
import uuid
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from agent_sessions.transcripts import read_transcript, transcript_path_for, write_transcript
from agent_sessions.models import (
    AgentSession,
    AgentSessionMetadata,
    AgentTranscriptMessage,
    SessionNotFoundError,
    date_bucket_for,
    now_iso,
)

from app_infra.paths import PROJECT_ROOT
from app_infra.storage import atomic_write_json

class AgentSessionStore:

    def __init__(
        self,
        sessions_root: str | Path | None = None,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.sessions_root = Path(sessions_root) if sessions_root else PROJECT_ROOT / ".paper-notes" / "sessions"
        self.index_path = self.sessions_root / "sessions.json"
        self._clock = clock or (lambda: datetime.now().astimezone())
        self._lock = threading.Lock()
        self._loaded = False
        self._sessions: dict[str, AgentSessionMetadata] = {}

    def create_session(
        self,
        *,
        title: str = "New chat",
        note_id: str | None = None,
        provider: str | None = None,
        model: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AgentSession:
        now = self._clock()
        created_at = now_iso(now)
        session_id = f"{now.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
        session_metadata = AgentSessionMetadata(
            session_id=session_id,
            title=title or "New chat",
            created_at=created_at,
            updated_at=created_at,
            date_bucket=date_bucket_for(now),
            note_id=note_id,
            provider=provider,
            model=model,
            metadata=dict(metadata or {}),
        )

        with self._lock:
            self._ensure_loaded_locked()
            self._sessions[session_id] = session_metadata
            self._save_index_locked()
            write_transcript(self.transcript_path(session_id), [])

        return AgentSession(metadata=session_metadata, messages=[])

    def get_session(self, session_id: str) -> AgentSession | None:
        with self._lock:
            self._ensure_loaded_locked()
            metadata = self._sessions.get(session_id)
            if metadata is None:
                return None
            return AgentSession(metadata=metadata, messages=read_transcript(self._transcript_path_for_metadata(metadata)))

    def require_session(self, session_id: str) -> AgentSession:
        session = self.get_session(session_id)
        if session is None:
            raise SessionNotFoundError(session_id)
        return session

    def list_sessions(self, *, include_archived: bool = False) -> list[AgentSessionMetadata]:
        with self._lock:
            self._ensure_loaded_locked()
            sessions = [
                metadata
                for metadata in self._sessions.values()
                if include_archived or not metadata.archived
            ]
            return sorted(sessions, key=lambda metadata: metadata.updated_at, reverse=True)

    def append_message(
        self,
        session_id: str,
        message: AgentTranscriptMessage | dict[str, Any],
    ) -> AgentSession:
        with self._lock:
            self._ensure_loaded_locked()
            metadata = self._require_metadata_locked(session_id)
            path = self._transcript_path_for_metadata(metadata)
            messages = read_transcript(path)
            messages.append(self._message_with_created_at(message))
            normalized = write_transcript(path, messages)
            metadata.message_count = len(normalized)
            metadata.updated_at = now_iso(self._clock())
            self._save_index_locked()
            return AgentSession(metadata=metadata, messages=normalized)

    def replace_messages(
        self,
        session_id: str,
        messages: list[AgentTranscriptMessage | dict[str, Any]],
    ) -> AgentSession:
        with self._lock:
            self._ensure_loaded_locked()
            metadata = self._require_metadata_locked(session_id)
            normalized = write_transcript(
                self._transcript_path_for_metadata(metadata),
                [self._message_with_created_at(message) for message in messages],
            )
            metadata.message_count = len(normalized)
            metadata.updated_at = now_iso(self._clock())
            self._save_index_locked()
            return AgentSession(metadata=metadata, messages=normalized)

    def rename_session(self, session_id: str, title: str) -> AgentSessionMetadata:
        with self._lock:
            self._ensure_loaded_locked()
            metadata = self._require_metadata_locked(session_id)
            metadata.title = title or "New chat"
            metadata.updated_at = now_iso(self._clock())
            self._save_index_locked()
            return metadata

    def archive_session(self, session_id: str, *, archived: bool = True) -> AgentSessionMetadata:
        with self._lock:
            self._ensure_loaded_locked()
            metadata = self._require_metadata_locked(session_id)
            metadata.archived = archived
            metadata.updated_at = now_iso(self._clock())
            self._save_index_locked()
            return metadata

    def update_session_model(
        self,
        session_id: str,
        *,
        provider: str | None = None,
        model: str | None = None,
    ) -> AgentSession:
        with self._lock:
            self._ensure_loaded_locked()
            metadata = self._require_metadata_locked(session_id)
            if provider is not None:
                metadata.provider = provider or None
            if model is not None:
                metadata.model = model or None
            metadata.updated_at = now_iso(self._clock())
            self._save_index_locked()
            return AgentSession(metadata=metadata, messages=read_transcript(self._transcript_path_for_metadata(metadata)))

    def update_session_metadata(
        self,
        session_id: str,
        updates: dict[str, Any],
        *,
        replace: bool = False,
    ) -> AgentSessionMetadata:
        with self._lock:
            self._ensure_loaded_locked()
            metadata = self._require_metadata_locked(session_id)
            metadata.metadata = dict(updates) if replace else {**metadata.metadata, **dict(updates)}
            metadata.updated_at = now_iso(self._clock())
            self._save_index_locked()
            return metadata

    def delete_session(self, session_id: str) -> AgentSessionMetadata:
        with self._lock:
            self._ensure_loaded_locked()
            metadata = self._require_metadata_locked(session_id)
            transcript_path = self._transcript_path_for_metadata(metadata)
            deleted_metadata = self._sessions.pop(session_id)
            self._save_index_locked()
            if transcript_path.exists():
                transcript_path.unlink()
            return deleted_metadata

    def branch_session(self, session_id: str, *, title: str | None = None) -> AgentSession:
        with self._lock:
            self._ensure_loaded_locked()
            source_metadata = self._require_metadata_locked(session_id)
            messages = read_transcript(self._transcript_path_for_metadata(source_metadata))
            now = self._clock()
            created_at = now_iso(now)
            branch_id = f"{now.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
            branch_metadata = AgentSessionMetadata(
                session_id=branch_id,
                title=title or f"{source_metadata.title} (branch)",
                created_at=created_at,
                updated_at=created_at,
                date_bucket=date_bucket_for(now),
                note_id=source_metadata.note_id,
                provider=source_metadata.provider,
                model=source_metadata.model,
                message_count=len(messages),
                metadata={
                    **source_metadata.metadata,
                    "parent_session_id": source_metadata.session_id,
                },
            )
            self._sessions[branch_id] = branch_metadata
            write_transcript(self._transcript_path_for_metadata(branch_metadata), messages)
            self._save_index_locked()
            return AgentSession(metadata=branch_metadata, messages=messages)

    def undo_last_turn(self, session_id: str) -> tuple[AgentSession, int]:
        with self._lock:
            self._ensure_loaded_locked()
            metadata = self._require_metadata_locked(session_id)
            path = self._transcript_path_for_metadata(metadata)
            messages = read_transcript(path)
            last_user_index = _last_user_message_index(messages)
            if last_user_index is None:
                return AgentSession(metadata=metadata, messages=messages), 0

            truncated = messages[:last_user_index]
            removed_count = len(messages) - len(truncated)
            normalized = write_transcript(path, truncated)
            metadata.message_count = len(normalized)
            metadata.updated_at = now_iso(self._clock())
            self._save_index_locked()
            return AgentSession(metadata=metadata, messages=normalized), removed_count

    def transcript_path(self, session_id: str) -> Path:
        metadata = self._sessions.get(session_id)
        if metadata is None:
            metadata = self._load_index().get(session_id)
        if metadata is None:
            raise SessionNotFoundError(session_id)
        return self._transcript_path_for_metadata(metadata)

    def _ensure_loaded_locked(self) -> None:
        if self._loaded:
            return
        self._sessions = self._load_index()
        self._loaded = True

    def _load_index(self) -> dict[str, AgentSessionMetadata]:
        if not self.index_path.exists():
            return {}
        import json

        data = json.loads(self.index_path.read_text(encoding="utf-8"))
        raw_sessions = data.get("sessions", {})
        if isinstance(raw_sessions, list):
            return {
                str(entry["session_id"]): AgentSessionMetadata.from_dict(entry)
                for entry in raw_sessions
                if "session_id" in entry
            }
        return {
            str(session_id): AgentSessionMetadata.from_dict({**entry, "session_id": entry.get("session_id", session_id)})
            for session_id, entry in raw_sessions.items()
        }

    def _save_index_locked(self) -> None:
        payload = {
            "version": 1,
            "sessions": {
                session_id: metadata.to_dict()
                for session_id, metadata in sorted(self._sessions.items())
            },
        }
        atomic_write_json(self.index_path, payload)

    def _require_metadata_locked(self, session_id: str) -> AgentSessionMetadata:
        metadata = self._sessions.get(session_id)
        if metadata is None:
            raise SessionNotFoundError(session_id)
        return metadata

    def _transcript_path_for_metadata(self, metadata: AgentSessionMetadata) -> Path:
        return transcript_path_for(self.sessions_root, metadata)

    def _message_with_created_at(self, message: AgentTranscriptMessage | dict[str, Any]) -> dict[str, Any]:
        if isinstance(message, AgentTranscriptMessage):
            data = message.to_dict()
        else:
            data = dict(message)
        if "created_at" not in data:
            data["created_at"] = now_iso(self._clock())
        return data


def _last_user_message_index(messages: list[dict[str, Any]]) -> int | None:
    for index in range(len(messages) - 1, -1, -1):
        if messages[index].get("role") == "user":
            return index
    return None
