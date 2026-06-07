"""Local curated memory store.

Adapted from Nous Research Hermes Agent's MIT-licensed `tools/memory_tool.py`.
This keeps Hermes' two-store shape (`MEMORY.md` and `USER.md`) while using the
Paper Notes local storage helpers and a smaller API surface.
"""

from __future__ import annotations

import re
import threading
from pathlib import Path
from typing import Any

from agent_memory.types import MemoryItem
from app_infra.paths import PROJECT_ROOT
from app_infra.storage import atomic_write_text


ENTRY_DELIMITER = "\n--- memory-entry ---\n"
MEMORY_TARGET = "memory"
USER_TARGET = "user"
MEMORY_FILENAME = "MEMORY.md"
USER_FILENAME = "USER.md"

_VALID_TARGETS = {MEMORY_TARGET, USER_TARGET}
_LOCKS: dict[Path, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()
_QUERY_TOKEN_RE = re.compile(r"[\w\u4e00-\u9fff]+", re.UNICODE)
_INVISIBLE_CHARS = {
    "\u200b",
    "\u200c",
    "\u200d",
    "\u2060",
    "\ufeff",
    "\u202a",
    "\u202b",
    "\u202c",
    "\u202d",
    "\u202e",
}
_MEMORY_THREAT_PATTERNS = [
    (r"ignore\s+(previous|all|above|prior)\s+instructions", "prompt_injection"),
    (r"you\s+are\s+now\s+", "role_hijack"),
    (r"do\s+not\s+tell\s+the\s+user", "deception_hide"),
    (r"system\s+prompt\s+override", "system_prompt_override"),
    (r"disregard\s+(your|all|any)\s+(instructions|rules|guidelines)", "disregard_rules"),
    (r"curl\s+[^\n]*\$\{?\w*(KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|API)", "exfil_curl"),
    (r"wget\s+[^\n]*\$\{?\w*(KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|API)", "exfil_wget"),
    (r"cat\s+[^\n]*(\.env|credentials|\.netrc|\.pgpass|\.npmrc|\.pypirc)", "read_secrets"),
    (r"authorized_keys", "ssh_backdoor"),
    (r"\$HOME/\.ssh|\~/\.ssh", "ssh_access"),
]


class LocalMemoryStore:
    """Bounded Markdown-backed memory with separate user/profile stores."""

    def __init__(
        self,
        memory_path: str | Path | None = None,
        *,
        memory_char_limit: int = 4000,
        user_char_limit: int = 2500,
    ) -> None:
        root = Path(memory_path) if memory_path else PROJECT_ROOT / ".paper-notes" / "memory"
        self.memory_root = root.parent if root.suffix else root
        self.memory_char_limit = memory_char_limit
        self.user_char_limit = user_char_limit
        self.memory_entries: list[str] = []
        self.user_entries: list[str] = []
        self._system_prompt_snapshot: dict[str, str] = {MEMORY_TARGET: "", USER_TARGET: ""}
        self.load_from_disk()

    @property
    def memory_path(self) -> Path:
        return self._path_for(MEMORY_TARGET)

    @property
    def user_path(self) -> Path:
        return self._path_for(USER_TARGET)

    def load_from_disk(self) -> None:
        self.memory_root.mkdir(parents=True, exist_ok=True)
        self.memory_entries = _dedupe(self._read_file(self.memory_path))
        self.user_entries = _dedupe(self._read_file(self.user_path))
        self._system_prompt_snapshot = {
            MEMORY_TARGET: self._render_block(MEMORY_TARGET, self.memory_entries),
            USER_TARGET: self._render_block(USER_TARGET, self.user_entries),
        }

    def add(self, content: str, *, target: str = MEMORY_TARGET) -> dict[str, Any]:
        target = self._normalize_target(target)
        content = _normalize_content(content)
        if not content:
            return _tool_error("Content cannot be empty.")

        scan_error = scan_memory_content(content)
        if scan_error:
            return _tool_error(scan_error)

        with _lock_for(self._path_for(target)):
            entries = _dedupe(self._read_file(self._path_for(target)))
            if content in entries:
                self._set_entries(target, entries)
                self._refresh_snapshot()
                return self._success_response(target, "Entry already exists; no duplicate added.")

            new_entries = entries + [content]
            new_total = len(ENTRY_DELIMITER.join(new_entries))
            limit = self._char_limit(target)
            if new_total > limit:
                return _tool_error(
                    f"Memory would exceed {limit} characters. Replace or remove existing entries first.",
                    current_entries=entries,
                    usage=f"{len(ENTRY_DELIMITER.join(entries))}/{limit}",
                )

            self._write_file(self._path_for(target), new_entries)
            self._set_entries(target, new_entries)
            self._refresh_snapshot()
            return self._success_response(target, "Entry added.")

    def replace(self, target: str, old_text: str, content: str) -> dict[str, Any]:
        target = self._normalize_target(target)
        old_text = _normalize_content(old_text)
        content = _normalize_content(content)
        if not old_text:
            return _tool_error("old_text cannot be empty.")
        if not content:
            return _tool_error("content cannot be empty. Use remove to delete entries.")

        scan_error = scan_memory_content(content)
        if scan_error:
            return _tool_error(scan_error)

        with _lock_for(self._path_for(target)):
            entries = _dedupe(self._read_file(self._path_for(target)))
            matches = [(index, entry) for index, entry in enumerate(entries) if old_text in entry]
            if not matches:
                return _tool_error(f"No entry matched '{old_text}'.")
            if len({entry for _, entry in matches}) > 1:
                return _tool_error(
                    f"Multiple entries matched '{old_text}'. Be more specific.",
                    matches=[entry[:120] for _, entry in matches],
                )

            index = matches[0][0]
            updated = list(entries)
            updated[index] = content
            limit = self._char_limit(target)
            if len(ENTRY_DELIMITER.join(updated)) > limit:
                return _tool_error(f"Replacement would exceed {limit} characters.")

            self._write_file(self._path_for(target), updated)
            self._set_entries(target, updated)
            self._refresh_snapshot()
            return self._success_response(target, "Entry replaced.")

    def remove(self, target: str, old_text: str) -> dict[str, Any]:
        target = self._normalize_target(target)
        old_text = _normalize_content(old_text)
        if not old_text:
            return _tool_error("old_text cannot be empty.")

        with _lock_for(self._path_for(target)):
            entries = _dedupe(self._read_file(self._path_for(target)))
            matches = [(index, entry) for index, entry in enumerate(entries) if old_text in entry]
            if not matches:
                return _tool_error(f"No entry matched '{old_text}'.")
            if len({entry for _, entry in matches}) > 1:
                return _tool_error(
                    f"Multiple entries matched '{old_text}'. Be more specific.",
                    matches=[entry[:120] for _, entry in matches],
                )

            updated = list(entries)
            updated.pop(matches[0][0])
            self._write_file(self._path_for(target), updated)
            self._set_entries(target, updated)
            self._refresh_snapshot()
            return self._success_response(target, "Entry removed.")

    def read(self, target: str) -> dict[str, Any]:
        target = self._normalize_target(target)
        with _lock_for(self._path_for(target)):
            entries = _dedupe(self._read_file(self._path_for(target)))
            self._set_entries(target, entries)
            self._refresh_snapshot()
            return self._success_response(target, "Entries read.")

    def format_for_system_prompt(self, target: str) -> str:
        target = self._normalize_target(target)
        return self._system_prompt_snapshot.get(target, "")

    def format_all_for_system_prompt(self) -> str:
        blocks = [
            self.format_for_system_prompt(MEMORY_TARGET),
            self.format_for_system_prompt(USER_TARGET),
        ]
        return "\n\n".join(block for block in blocks if block.strip())

    def search(self, query: str, *, limit: int = 5) -> list[MemoryItem]:
        query_norm = _normalize_content(query).casefold()
        query_tokens = set(_QUERY_TOKEN_RE.findall(query_norm))
        results: list[tuple[int, MemoryItem]] = []

        for target, entries in ((MEMORY_TARGET, self.memory_entries), (USER_TARGET, self.user_entries)):
            for index, entry in enumerate(entries, start=1):
                entry_norm = entry.casefold()
                score = 0
                if query_norm and query_norm in entry_norm:
                    score += 10
                score += 2 * len(query_tokens & set(_QUERY_TOKEN_RE.findall(entry_norm)))
                if score > 0:
                    results.append((
                        score,
                        MemoryItem(
                            memory_id=f"{target}:{index}",
                            content=entry,
                            kind=target,
                        ),
                    ))

        results.sort(key=lambda item: item[0], reverse=True)
        return [item for _, item in results[: max(0, limit)]]

    def all_items(self) -> list[MemoryItem]:
        items: list[MemoryItem] = []
        for target, entries in ((MEMORY_TARGET, self.memory_entries), (USER_TARGET, self.user_entries)):
            items.extend(
                MemoryItem(memory_id=f"{target}:{index}", content=entry, kind=target)
                for index, entry in enumerate(entries, start=1)
            )
        return items

    def _success_response(self, target: str, message: str) -> dict[str, Any]:
        entries = self._entries_for(target)
        current = len(ENTRY_DELIMITER.join(entries)) if entries else 0
        limit = self._char_limit(target)
        return {
            "success": True,
            "target": target,
            "entries": list(entries),
            "entry_count": len(entries),
            "usage": f"{current}/{limit}",
            "message": message,
        }

    def _render_block(self, target: str, entries: list[str]) -> str:
        if not entries:
            return ""
        limit = self._char_limit(target)
        content = ENTRY_DELIMITER.join(entries)
        current = len(content)
        pct = min(100, int((current / limit) * 100)) if limit else 0
        header = (
            f"USER PROFILE (who the user is) [{pct}% - {current}/{limit} chars]"
            if target == USER_TARGET
            else f"MEMORY (stable project and environment facts) [{pct}% - {current}/{limit} chars]"
        )
        separator = "=" * 46
        return f"{separator}\n{header}\n{separator}\n{content}"

    def _refresh_snapshot(self) -> None:
        self._system_prompt_snapshot = {
            MEMORY_TARGET: self._render_block(MEMORY_TARGET, self.memory_entries),
            USER_TARGET: self._render_block(USER_TARGET, self.user_entries),
        }

    def _entries_for(self, target: str) -> list[str]:
        return self.user_entries if target == USER_TARGET else self.memory_entries

    def _set_entries(self, target: str, entries: list[str]) -> None:
        if target == USER_TARGET:
            self.user_entries = entries
        else:
            self.memory_entries = entries

    def _char_limit(self, target: str) -> int:
        return self.user_char_limit if target == USER_TARGET else self.memory_char_limit

    def _path_for(self, target: str) -> Path:
        target = self._normalize_target(target)
        return self.memory_root / (USER_FILENAME if target == USER_TARGET else MEMORY_FILENAME)

    @staticmethod
    def _read_file(path: Path) -> list[str]:
        if not path.exists():
            return []
        raw = path.read_text(encoding="utf-8")
        if not raw.strip():
            return []
        return [_normalize_content(entry) for entry in raw.split(ENTRY_DELIMITER) if _normalize_content(entry)]

    @staticmethod
    def _write_file(path: Path, entries: list[str]) -> None:
        atomic_write_text(path, ENTRY_DELIMITER.join(entries) if entries else "")

    @staticmethod
    def _normalize_target(target: str) -> str:
        normalized = str(target or MEMORY_TARGET).strip().lower()
        if normalized not in _VALID_TARGETS:
            raise ValueError(f"Invalid memory target: {target}. Use 'memory' or 'user'.")
        return normalized


def scan_memory_content(content: str) -> str | None:
    for char in _INVISIBLE_CHARS:
        if char in content:
            return f"Blocked: content contains invisible unicode character U+{ord(char):04X}."
    for pattern, pattern_id in _MEMORY_THREAT_PATTERNS:
        if re.search(pattern, content, re.IGNORECASE):
            return f"Blocked: content matches threat pattern '{pattern_id}'."
    return None


def _lock_for(path: Path) -> threading.Lock:
    resolved = path.resolve()
    with _LOCKS_GUARD:
        if resolved not in _LOCKS:
            _LOCKS[resolved] = threading.Lock()
        return _LOCKS[resolved]


def _normalize_content(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _dedupe(entries: list[str]) -> list[str]:
    return list(dict.fromkeys(entry for entry in entries if entry))


def _tool_error(message: str, **extra: Any) -> dict[str, Any]:
    return {"success": False, "error": message, **extra}
