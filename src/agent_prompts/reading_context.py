"""Helpers for building the current reading-context prompt section."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class AgentPromptContext:
    current_note: dict[str, Any] | None = None
    current_page: int | None = None
    selection_text: str = ""
    visible_annotations: list[dict[str, Any]] = field(default_factory=list)
    session_title: str = ""

    @classmethod
    def from_note(
        cls,
        note: dict[str, Any] | None,
        *,
        current_page: int | None = None,
        selection_text: str = "",
        visible_annotations: list[dict[str, Any]] | None = None,
        session_title: str = "",
    ) -> AgentPromptContext:
        return cls(
            current_note=note,
            current_page=current_page,
            selection_text=selection_text,
            visible_annotations=list(visible_annotations or []),
            session_title=session_title,
        )


def build_context_section(context: AgentPromptContext | dict[str, Any] | None) -> str:
    normalized = normalize_prompt_context(context)
    if not normalized:
        return ""

    lines = ["# Current Reading Context"]
    if normalized.session_title:
        lines.append(f"- Session: {normalized.session_title}")

    if normalized.current_note:
        note = normalized.current_note
        lines.append("- Current note:")
        lines.append(f"  - id: {_text(note.get('id'))}")
        lines.append(f"  - title: {_text(note.get('title'))}")
        collection_path = _text(note.get("collectionPath") or note.get("collection_path"))
        collection_name = _text(note.get("collectionName") or note.get("collection") or note.get("collection_name"))
        if collection_path:
            lines.append(f"  - collection: {collection_path}")
        elif collection_name:
            lines.append(f"  - collection: {collection_name}")
        summary = _text(note.get("summary"))
        if summary:
            lines.append(f"  - summary: {summary}")
        tags = note.get("tags")
        if isinstance(tags, list) and tags:
            lines.append(f"  - tags: {', '.join(_text(tag) for tag in tags if _text(tag))}")

    if normalized.current_page is not None:
        lines.append(f"- Current page: {normalized.current_page}")

    selection = _text(normalized.selection_text)
    if selection:
        lines.append(
            "- Selected text guidance: When selected text is provided, treat it as the primary focus of the user's "
            "question unless the user clearly asks for broader context."
        )
        lines.append("- Selected text:")
        lines.append(_block(selection))

    if normalized.visible_annotations:
        lines.append("- Visible annotations:")
        for annotation in normalized.visible_annotations[:8]:
            annotation_id = _text(annotation.get("id"))
            page = _text(annotation.get("page"))
            comment = _text(annotation.get("comment") or annotation.get("content"))
            quote = _text(annotation.get("quote"))
            parts = []
            if annotation_id:
                parts.append(f"id={annotation_id}")
            if page:
                parts.append(f"page={page}")
            prefix = f"  - {'; '.join(parts)}" if parts else "  -"
            body = comment or quote
            lines.append(f"{prefix}: {body}" if body else prefix)

    return "\n".join(line for line in lines if line.strip())


def normalize_prompt_context(context: AgentPromptContext | dict[str, Any] | None) -> AgentPromptContext | None:
    if context is None:
        return None
    if isinstance(context, AgentPromptContext):
        return context
    if not isinstance(context, dict):
        return None
    return AgentPromptContext(
        current_note=context.get("current_note") or context.get("note"),
        current_page=context.get("current_page") or context.get("page"),
        selection_text=_text(context.get("selection_text") or context.get("selection")),
        visible_annotations=list(context.get("visible_annotations") or context.get("annotations") or []),
        session_title=_text(context.get("session_title")),
    )


def _block(text: str) -> str:
    return "\n".join(f"> {line}" for line in text.splitlines() if line.strip())


def _text(value: Any) -> str:
    return str(value or "").strip()
