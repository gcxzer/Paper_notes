"""Load human-maintained long-term memory into the agent prompt."""

from __future__ import annotations

from pathlib import Path

from app_infra.files import LOCAL_STATE_DIR


MEMORY_DIR = LOCAL_STATE_DIR / "memory"
MEMORY_FILE_NAMES = ("system.md", "user.md")
DEFAULT_MAX_MEMORY_CHARS = 40_000


def build_memory_section(
    memory_dir: Path | None = None,
    *,
    max_chars: int = DEFAULT_MAX_MEMORY_CHARS,
) -> str:
    """Load human-maintained memory markdown for the system prompt."""
    directory = memory_dir or MEMORY_DIR
    sections = _memory_sections(directory, max_chars=max_chars)
    if not sections:
        return ""
    return "\n\n".join([
        "# Memory",
        "You have a persistent, file-based memory system.",
        "Use this memory so future conversations can retain a durable picture of who the user is, how they like to collaborate, what behaviors to avoid or repeat, and the context behind their work.",
        "Treat memory as context, not as live state. If memory conflicts with the user's latest instruction or current Paper Notes state, trust the latest instruction or current state.",
        *sections,
    ])


def _memory_sections(directory: Path, *, max_chars: int) -> list[str]:
    sections: list[str] = []
    remaining_chars = max(0, max_chars)
    for file_name in MEMORY_FILE_NAMES:
        text = _read_markdown(directory / file_name)
        if not text:
            continue
        if remaining_chars and len(text) > remaining_chars:
            text = f"{text[:remaining_chars].rstrip()}\n\n[Memory truncated.]"
        sections.append(text)
        if remaining_chars:
            remaining_chars -= min(len(text), remaining_chars)
            if remaining_chars <= 0:
                break
    return sections


def _read_markdown(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return ""
