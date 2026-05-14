"""Tool result persistence and budget control.

This module is responsible for keeping tool outputs compact in chat/model
context while preserving full content locally when needed.

Data flow:
1. `ToolResultStore.maybe_persist` checks whether one tool result exceeds the
   allowed per-tool threshold (from `ToolResultBudget`).
2. If the result is small enough, it returns the original content unchanged.
3. If the result is too large, it is written as a JSON file under session
   storage and replaced by a compact JSON reference message.
4. `ToolResultStore.enforce_turn_budget` applies the same idea at turn-level,
   compressing the largest unpersisted messages until the total turn size is within
   `turn_budget`.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tools.output_limits import DEFAULT_TOOL_RESULT_BUDGET, ToolResultBudget
from app_infra.paths import PROJECT_ROOT, is_relative_to
from app_infra.storage import atomic_write_json


PERSISTED_RESULT_MARKER = '"persisted_tool_result": true'
_BUDGET_TOOL_NAME = "__turn_budget__"


@dataclass(slots=True)
class ToolResultPersistence:
    content: str
    persisted: bool = False
    result_id: str = ""
    path: str = ""
    relative_path: str = ""
    original_chars: int = 0
    preview_chars: int = 0

    def metadata(self) -> dict[str, Any]:
        if not self.persisted:
            return {}
        return {
            "persisted": True,
            "result_id": self.result_id,
            "path": self.relative_path,
            "original_chars": self.original_chars,
            "preview_chars": self.preview_chars,
        }


@dataclass(slots=True)
class ToolResultStore:
    root: Path
    budget: ToolResultBudget = field(default_factory=lambda: DEFAULT_TOOL_RESULT_BUDGET)
    project_root: Path = PROJECT_ROOT

    def maybe_persist(
        self,
        *,
        content: str,
        tool_name: str,
        tool_call_id: str,
        session_id: str,
        threshold: int | None = None,
        reason: str = "result_size",
    ) -> ToolResultPersistence:
        text = str(content or "")
        effective_threshold = self.budget.resolve_threshold(tool_name, explicit=threshold)
        if len(text) <= effective_threshold:
            return ToolResultPersistence(content=text)
        return self.persist(
            content=text,
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            session_id=session_id,
            reason=reason,
        )

    def persist(
        self,
        *,
        content: str,
        tool_name: str,
        tool_call_id: str,
        session_id: str,
        reason: str,
    ) -> ToolResultPersistence:
        text = str(content or "")
        preview, has_more = generate_preview(text, max_chars=self.budget.preview_size)
        result_id = self._result_id(tool_call_id, text)
        session_dir = self.root / _safe_id(session_id or "unknown-session")
        path = _unique_path(session_dir / f"{result_id}.json")
        payload = {
            "version": 1,
            "resultId": path.stem,
            "toolCallId": str(tool_call_id or ""),
            "toolName": str(tool_name or ""),
            "reason": reason,
            "createdAt": _now_iso(),
            "originalChars": len(text),
            "previewChars": len(preview),
            "content": text,
        }
        atomic_write_json(path, payload)
        relative_path = self._relative_path(path)
        reference = _persisted_reference(
            tool_name=tool_name,
            result_id=path.stem,
            relative_path=relative_path,
            original_chars=len(text),
            preview=preview,
            has_more=has_more,
            reason=reason,
        )
        return ToolResultPersistence(
            content=reference,
            persisted=True,
            result_id=path.stem,
            path=str(path),
            relative_path=relative_path,
            original_chars=len(text),
            preview_chars=len(preview),
        )

    def enforce_turn_budget(self, tool_messages: list[dict[str, Any]], *, session_id: str) -> list[dict[str, Any]]:
        total_chars = 0
        candidates: list[tuple[int, int]] = []
        for index, message in enumerate(tool_messages):
            content = str(message.get("content") or "")
            size = len(content)
            total_chars += size
            if not is_persisted_reference(content):
                candidates.append((index, size))

        if total_chars <= self.budget.turn_budget:
            return tool_messages

        candidates.sort(key=lambda item: item[1], reverse=True)
        for index, size in candidates:
            if total_chars <= self.budget.turn_budget:
                break
            message = tool_messages[index]
            content = str(message.get("content") or "")
            persisted = self.persist(
                content=content,
                tool_name=str(message.get("name") or _BUDGET_TOOL_NAME),
                tool_call_id=str(message.get("tool_call_id") or f"budget-{index}"),
                session_id=session_id,
                reason="turn_budget",
            )
            if persisted.persisted:
                message["content"] = persisted.content
                total_chars = total_chars - size + len(persisted.content)
        return tool_messages

    def _result_id(self, tool_call_id: str, content: str) -> str:
        base = _safe_id(tool_call_id) or f"tool-result-{uuid.uuid4().hex[:10]}"
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()[:8]
        return f"{base}-{digest}"

    def _relative_path(self, path: Path) -> str:
        resolved = Path(path).resolve()
        project = Path(self.project_root).resolve()
        if is_relative_to(resolved, project):
            return str(resolved.relative_to(project))
        return str(resolved)


def generate_preview(content: str, *, max_chars: int) -> tuple[str, bool]:
    text = str(content or "")
    limit = max(100, int(max_chars))
    if len(text) <= limit:
        return text, False
    preview = text[:limit]
    last_newline = preview.rfind("\n")
    if last_newline > limit // 2:
        preview = preview[: last_newline + 1]
    return preview.rstrip(), True


def is_persisted_reference(content: str) -> bool:
    return PERSISTED_RESULT_MARKER in str(content or "")


def _persisted_reference(
    *,
    tool_name: str,
    result_id: str,
    relative_path: str,
    original_chars: int,
    preview: str,
    has_more: bool,
    reason: str,
) -> str:
    suffix = "\n..." if has_more else ""
    return json.dumps({
        "success": True,
        "persisted_tool_result": True,
        "tool_name": str(tool_name or ""),
        "result_id": result_id,
        "path": relative_path,
        "reason": reason,
        "original_chars": int(original_chars),
        "preview_chars": len(preview),
        "message": "Tool result was too large for inline model context; full output was saved locally.",
        "preview": preview + suffix,
    }, ensure_ascii=False, indent=2)


def _safe_id(value: object) -> str:
    text = str(value or "").strip()
    text = re.sub(r"[^A-Za-z0-9_.-]+", "-", text).strip(".-")
    return text[:96]


def _unique_path(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    for _ in range(20):
        candidate = path.with_name(f"{stem}-{uuid.uuid4().hex[:8]}{suffix}")
        if not candidate.exists():
            return candidate
    return path.with_name(f"{stem}-{uuid.uuid4().hex}{suffix}")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
