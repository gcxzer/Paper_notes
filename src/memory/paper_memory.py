from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from app_infra.paths import LOCAL_STATE_DIR


PAPER_MEMORY_DIR = LOCAL_STATE_DIR / "memory" / "paper-memory"
PAPER_MEMORY_METADATA_PREFIX = "<!-- paper-memory "
PAPER_MEMORY_METADATA_SUFFIX = " -->"
DEFAULT_MAX_PAPER_MEMORY_CHARS = 40_000


def build_paper_memory_section(
    note_id: str,
    memory_dir: Path | None = None,
    *,
    max_chars: int = DEFAULT_MAX_PAPER_MEMORY_CHARS,
) -> str:
    clean_note_id = str(note_id or "").strip()
    if not clean_note_id:
        return ""
    _metadata, memory = read_paper_memory_file(paper_memory_path(memory_dir or PAPER_MEMORY_DIR, clean_note_id))
    memory = _truncate_text(memory, max_chars)
    if not memory:
        return ""
    return "\n\n".join([
        "# Current Paper Memory",
        "You have recalled durable, file-based memory for the current paper/note only.",
        "Use this memory as prior context for the user's reading history, focus, useful explanations, and open questions about this paper.",
        "Memory records can become stale or incomplete. Treat them as claims about what was understood when they were written, not as authoritative paper content.",
        "Before answering with precise paper facts, figures, tables, equations, sections, or recommendations based on this memory, verify against the current paper content or note context. If memory conflicts with the current paper, note, or latest user instruction, trust the current source.",
        memory,
    ])


def paper_memory_path(memory_dir: Path, note_id: str) -> Path:
    return Path(memory_dir) / f"{safe_paper_memory_stem(note_id)}.md"


def safe_paper_memory_stem(note_id: str) -> str:
    text = str(note_id or "").strip().lower()
    text = re.sub(r"[^a-z0-9._-]+", "-", text)
    text = re.sub(r"-{2,}", "-", text).strip(".-")
    return text[:120] or "paper"


def read_paper_memory_file(path: Path) -> tuple[dict[str, Any], str]:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return {}, ""
    lines = raw.splitlines()
    if not lines:
        return {}, ""
    metadata = _metadata_from_comment(lines[0])
    if metadata:
        return metadata, "\n".join(lines[1:]).strip()
    return {}, raw.strip()


def write_paper_memory_file(path: Path, memory: str, *, metadata: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    clean_memory = memory.strip()
    payload = json.dumps(metadata, ensure_ascii=False, sort_keys=True)
    path.write_text(f"{PAPER_MEMORY_METADATA_PREFIX}{payload}{PAPER_MEMORY_METADATA_SUFFIX}\n{clean_memory}\n", encoding="utf-8")


def _metadata_from_comment(line: str) -> dict[str, Any]:
    text = line.strip()
    if not text.startswith(PAPER_MEMORY_METADATA_PREFIX) or not text.endswith(PAPER_MEMORY_METADATA_SUFFIX):
        return {}
    payload = text[len(PAPER_MEMORY_METADATA_PREFIX) : -len(PAPER_MEMORY_METADATA_SUFFIX)]
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _truncate_text(text: str, max_chars: int) -> str:
    clean = str(text or "").strip()
    if len(clean) <= max_chars:
        return clean
    return f"{clean[-max_chars:].lstrip()}\n\n[Earlier paper memory truncated.]"
