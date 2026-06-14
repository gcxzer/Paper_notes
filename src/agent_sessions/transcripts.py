from __future__ import annotations

import json
import re
import threading
from pathlib import Path
from typing import Any

from agent_sessions.models import AgentSessionMetadata, AgentTranscriptMessage

from app_infra.storage import atomic_write_text


_LOCKS: dict[Path, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()
_JSONL_UNSAFE_CHARACTERS = re.compile(r"[\u007f-\u009f\u2028\u2029]")


def transcript_path_for(sessions_root: str | Path, metadata: AgentSessionMetadata) -> Path:
    return Path(sessions_root) / metadata.date_bucket / f"{metadata.session_id}.jsonl"


def debug_transcript_path_for(sessions_root: str | Path, metadata: AgentSessionMetadata) -> Path:
    return Path(sessions_root) / metadata.date_bucket / f"{metadata.session_id}.debug.jsonl"


def normalize_message(message: AgentTranscriptMessage | dict[str, Any]) -> dict[str, Any]:
    if isinstance(message, AgentTranscriptMessage):
        data = message.to_dict()
    else:
        data = dict(message)
    if not data.get("role"):
        raise ValueError("Transcript message must include a role.")
    if "created_at" not in data:
        data["created_at"] = AgentTranscriptMessage.from_dict(data).created_at
    return data


def read_transcript(path: str | Path) -> list[dict[str, Any]]:
    transcript_path = Path(path)
    if not transcript_path.exists():
        return []

    messages: list[dict[str, Any]] = []
    for line_number, line in enumerate(transcript_path.read_text(encoding="utf-8").split("\n"), start=1):
        if not line.strip():
            continue
        try:
            messages.append(json.loads(line))
        except json.JSONDecodeError as error:
            raise ValueError(f"Invalid JSONL transcript at {transcript_path}:{line_number}") from error
    return messages


def write_transcript(path: str | Path, messages: list[AgentTranscriptMessage | dict[str, Any]]) -> list[dict[str, Any]]:
    transcript_path = Path(path)
    normalized = [normalize_message(message) for message in messages]
    text = "".join(_dumps_transcript_message(message) + "\n" for message in normalized)
    atomic_write_text(transcript_path, text)
    return normalized


def append_transcript_message(path: str | Path, message: AgentTranscriptMessage | dict[str, Any]) -> list[dict[str, Any]]:
    transcript_path = Path(path)
    with _lock_for(transcript_path):
        messages = read_transcript(transcript_path)
        messages.append(normalize_message(message))
        return write_transcript(transcript_path, messages)


def append_transcript_messages(path: str | Path, messages: list[AgentTranscriptMessage | dict[str, Any]]) -> list[dict[str, Any]]:
    transcript_path = Path(path)
    normalized = [normalize_message(message) for message in messages]
    if not normalized:
        return []
    with _lock_for(transcript_path):
        transcript_path.parent.mkdir(parents=True, exist_ok=True)
        with transcript_path.open("a", encoding="utf-8") as handle:
            for message in normalized:
                handle.write(_dumps_transcript_message(message) + "\n")
    return normalized


def _dumps_transcript_message(message: dict[str, Any]) -> str:
    text = json.dumps(message, ensure_ascii=False)
    return _JSONL_UNSAFE_CHARACTERS.sub(lambda match: f"\\u{ord(match.group(0)):04x}", text)


def _lock_for(path: Path) -> threading.Lock:
    resolved = path.resolve()
    with _LOCKS_GUARD:
        if resolved not in _LOCKS:
            _LOCKS[resolved] = threading.Lock()
        return _LOCKS[resolved]
