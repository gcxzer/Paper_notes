from __future__ import annotations

import re
import threading
from pathlib import Path
from typing import Any

from agent_memory.store import MEMORY_TARGET, USER_TARGET, LocalMemoryStore
from agent_memory.types import MemoryItem


_REMEMBER_PATTERNS = [
    re.compile(r"(?is)\bplease\s+remember(?:\s+that)?\b[:\s]*(.+)"),
    re.compile(r"(?is)\bremember(?:\s+that)?\b[:\s]*(.+)"),
    re.compile(r"(?is)\bsave\s+(?:this|that)\b[:\s]*(.+)"),
    re.compile(r"(?s)(?:请|帮我)?记住[:：\s]*(.+)"),
    re.compile(r"(?s)以后(?:请)?记得[:：\s]*(.+)"),
]
_MEMORY_CONTEXT_RE = re.compile(r"<\s*memory-context\s*>[\s\S]*?</\s*memory-context\s*>", re.IGNORECASE)
_TAG_RE = re.compile(r"</?\s*memory-context\s*>", re.IGNORECASE)
_PROGRESS_RE = re.compile(
    r"\b(done|finished|fixed|implemented|merged|commit|sha|pull request|pr\s*#|phase)\b"
    r"|完成|修复|提交|合并|阶段",
    re.IGNORECASE,
)
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_USER_MEMORY_RE = re.compile(r"\b(i|me|my|user)\b|\bprefer|preference|喜欢|偏好|我的|我", re.IGNORECASE)


class LocalMemoryProvider:
    """Built-in Paper Notes memory provider, following Hermes' curated-memory route."""

    def __init__(self, store: LocalMemoryStore | None = None, *, memory_path: str | Path | None = None) -> None:
        self.store = store or LocalMemoryStore(memory_path)
        self._session_prompt_snapshots: dict[str, str] = {}
        self._snapshot_lock = threading.RLock()

    @property
    def name(self) -> str:
        return "local"

    def prefetch(
        self,
        query: str,
        *,
        session_id: str = "",
        note_id: str = "",
        limit: int = 5,
    ) -> str:
        del query, note_id, limit
        if session_id:
            with self._snapshot_lock:
                existing = self._session_prompt_snapshots.get(session_id)
                if existing is not None:
                    return existing
                self.store.load_from_disk()
                snapshot = self.store.format_all_for_system_prompt()
                self._session_prompt_snapshots[session_id] = snapshot
                return snapshot
        self.store.load_from_disk()
        return self.store.format_all_for_system_prompt()

    def clear_session_snapshot(self, session_id: str) -> None:
        with self._snapshot_lock:
            self._session_prompt_snapshots.pop(session_id, None)

    def sync_turn(
        self,
        user_content: str,
        assistant_content: str,
        *,
        session_id: str = "",
        note_id: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> MemoryItem | None:
        del assistant_content, note_id, metadata
        content = extract_explicit_memory(user_content)
        if content is None:
            return None
        target = classify_memory_target(content)
        result = self.store.add(content, target=target)
        if not result.get("success"):
            return None
        return MemoryItem(
            memory_id=f"{target}:{result.get('entry_count', '')}",
            content=content,
            kind=target,
            session_id=session_id,
        )

    def search(self, query: str, *, note_id: str = "", limit: int = 5) -> list[MemoryItem]:
        del note_id
        self.store.load_from_disk()
        return self.store.search(query, limit=limit)

    def persistent_memory_tool(self, arguments: dict[str, Any]) -> dict[str, Any]:
        action = str(arguments.get("action") or "read").strip().lower()
        target = str(arguments.get("target") or MEMORY_TARGET).strip().lower()

        try:
            if action == "read":
                return self.store.read(target)
            if action == "add":
                return self.store.add(str(arguments.get("content") or ""), target=target)
            if action == "replace":
                return self.store.replace(
                    target,
                    old_text=str(arguments.get("old_text") or ""),
                    content=str(arguments.get("content") or ""),
                )
            if action == "remove":
                return self.store.remove(target, old_text=str(arguments.get("old_text") or ""))
        except ValueError as error:
            return {"success": False, "error": str(error)}

        return {"success": False, "error": "Unknown action. Use add, replace, remove, or read."}


def extract_explicit_memory(text: Any) -> str | None:
    raw = _sanitize_memory_text(str(text or ""))
    for pattern in _REMEMBER_PATTERNS:
        match = pattern.search(raw)
        if not match:
            continue
        candidate = _trim_memory_candidate(match.group(1))
        if _is_valid_memory(candidate):
            return candidate
    return None


def classify_memory_target(content: str) -> str:
    return USER_TARGET if _USER_MEMORY_RE.search(content) else MEMORY_TARGET


def _sanitize_memory_text(text: str) -> str:
    without_context = _MEMORY_CONTEXT_RE.sub("", text)
    without_tags = _TAG_RE.sub("", without_context)
    return re.sub(r"\s+", " ", without_tags).strip()


def _trim_memory_candidate(text: str) -> str:
    candidate = str(text or "").strip(" \t\r\n:：-")
    candidate = re.sub(r"^(that|to)\s+", "", candidate, flags=re.IGNORECASE)
    candidate = re.split(r"\n|(?:\.\s+|\。\s*)", candidate, maxsplit=1)[0].strip(" \t\r\n.。")
    return re.sub(r"\s+", " ", candidate).strip()


def _is_valid_memory(candidate: str) -> bool:
    min_length = 4 if _CJK_RE.search(candidate) else 8
    if len(candidate) < min_length:
        return False
    if len(candidate) > 600:
        return False
    return _PROGRESS_RE.search(candidate) is None
