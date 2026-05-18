from __future__ import annotations

# Image-to-note workflows that analyze paper/page images and write note sections.

import html as html_lib
import re
from pathlib import Path
from typing import Any

from app_infra.formatting import normalize_text
from tools.paper_notes.artifacts import _artifact_payload
from tools.paper_notes.common import (
    positive_float,
    positive_int,
    resolve_note,
    sanitize_html_fragment,
    tool_error,
)
from tools.paper_notes.notes import preview_note_diff, validate_note_html, write_note_section
from tools.paper_notes.paper import render_paper_page


def _paper_image_note_question(*, heading: str, user_question: str) -> str:
    focus = user_question or "Identify the main claim, visual evidence, important numbers, axes, labels, and caveats."
    return (
        "You are helping write a local paper note from a paper image. "
        "Analyze only what is visible in the image and avoid inventing missing details. "
        "Return concise safe HTML for the body of a note section, without markdown fences and without a top-level heading. "
        "Use only p, ul, ol, li, blockquote, code, pre, table, thead, tbody, tr, th, td, a, strong, and em tags. "
        f"Target section heading: {heading}. "
        f"Writing focus: {focus}"
    )


def _analysis_to_note_html(analysis_text: str) -> str:
    raw = _strip_markdown_fence(str(analysis_text or "").strip())
    if not raw:
        return ""
    if _looks_like_allowed_html(raw):
        return sanitize_html_fragment(raw)
    return sanitize_html_fragment(_plain_text_to_note_html(raw))


def _strip_markdown_fence(value: str) -> str:
    stripped = value.strip()
    stripped = re.sub(r"(?is)^```(?:html)?\s*", "", stripped)
    stripped = re.sub(r"(?is)\s*```\s*$", "", stripped)
    return stripped.strip()


def _looks_like_allowed_html(value: str) -> bool:
    return re.search(
        r"(?is)<\s*(?:a|blockquote|code|em|h[2-4]|li|ol|p|pre|strong|table|tbody|td|th|thead|tr|ul)\b",
        value,
    ) is not None


def _plain_text_to_note_html(value: str) -> str:
    parts: list[str] = []
    paragraph_lines: list[str] = []
    bullet_lines: list[str] = []

    def flush_paragraph() -> None:
        if paragraph_lines:
            text = normalize_text(" ".join(paragraph_lines))
            if text:
                parts.append(f"<p>{html_lib.escape(text)}</p>")
            paragraph_lines.clear()

    def flush_bullets() -> None:
        if bullet_lines:
            items = "".join(f"<li>{html_lib.escape(item)}</li>" for item in bullet_lines if item)
            if items:
                parts.append(f"<ul>{items}</ul>")
            bullet_lines.clear()

    for raw_line in value.splitlines():
        line = normalize_text(raw_line)
        if not line:
            flush_paragraph()
            flush_bullets()
            continue
        bullet_match = re.match(r"^[-*]\s+(.+)$", line)
        if bullet_match:
            flush_paragraph()
            bullet_lines.append(normalize_text(bullet_match.group(1)))
            continue
        flush_bullets()
        paragraph_lines.append(line)

    flush_paragraph()
    flush_bullets()
    return "\n".join(parts)


def _limit_text(value: str, max_chars: int) -> str:
    text = str(value or "")
    limit = max(100, int(max_chars))
    if len(text) <= limit:
        return text
    return f"{text[:limit].rstrip()}...[truncated]"


def write_note_from_paper_image(
    args: dict[str, Any],
    *,
    library_path: Path | None = None,
    html_dir: Path | None = None,
    papers_dir: Path | None = None,
    paper_page_cache_dir: Path | None = None,
    media_store: Any | None = None,
    paper_image_analyzer: Any | None = None,
) -> dict[str, Any]:
    note_result = resolve_note(args, library_path=library_path)
    if "error" in note_result:
        return note_result
    note = note_result["note"]
    note_id = normalize_text(note.get("id"))
    heading = normalize_text(args.get("heading"))
    if not heading:
        return tool_error("heading_required", "heading is required.", note_id=note_id)
    position = normalize_text(args.get("position") or "append").lower()
    if position not in {"append", "prepend", "after_heading", "replace_heading"}:
        return tool_error("invalid_position", "position must be append, prepend, after_heading, or replace_heading.", note_id=note_id)
    if not callable(paper_image_analyzer):
        return tool_error("image_analysis_unavailable", "Image analysis is not available in this registry.", note_id=note_id)

    image_payload = _resolve_workflow_image(
        args,
        note_id=note_id,
        library_path=library_path,
        papers_dir=papers_dir,
        paper_page_cache_dir=paper_page_cache_dir,
        media_store=media_store,
    )
    if not image_payload.get("success"):
        return image_payload

    question = _paper_image_note_question(
        heading=heading,
        user_question=normalize_text(args.get("question")),
    )
    analysis_payload = paper_image_analyzer({
        "artifact_id": image_payload.get("artifact_id"),
        "question": question,
    })
    if not isinstance(analysis_payload, dict):
        return tool_error("image_analysis_failed", "Image analysis returned an invalid result.", note_id=note_id)
    if analysis_payload.get("success") is False or analysis_payload.get("error"):
        return {
            **tool_error(
                str(analysis_payload.get("code") or "image_analysis_failed"),
                str(analysis_payload.get("error") or "Image analysis failed."),
                note_id=note_id,
            ),
            "image": image_payload,
            "analysis": analysis_payload,
        }

    analysis_text = str(analysis_payload.get("analysis") or analysis_payload.get("content") or "").strip()
    html_fragment = _analysis_to_note_html(analysis_text)
    if not html_fragment:
        return tool_error("empty_image_analysis", "Image analysis did not produce note content.", note_id=note_id)

    write_args = {
        "note_id": note_id,
        "heading": heading,
        "html": html_fragment,
        "position": position,
    }
    preview = preview_note_diff(write_args, library_path=library_path, html_dir=html_dir)
    if not preview.get("success"):
        return {
            **tool_error(str(preview.get("code") or "preview_failed"), str(preview.get("error") or "Preview failed."), note_id=note_id),
            "image": image_payload,
            "analysis": _limit_text(analysis_text, 4_000),
            "preview": preview,
        }

    write = write_note_section(write_args, library_path=library_path, html_dir=html_dir)
    if not write.get("success"):
        return {
            **tool_error(str(write.get("code") or "write_failed"), str(write.get("error") or "Write failed."), note_id=note_id),
            "image": image_payload,
            "analysis": _limit_text(analysis_text, 4_000),
            "preview": preview,
            "write": write,
        }

    validation = validate_note_html({"note_id": note_id}, library_path=library_path, html_dir=html_dir)
    return {
        "success": bool(validation.get("success") and validation.get("valid") is not False),
        "changed": bool(write.get("changed")),
        "note_id": note_id,
        "heading": heading,
        "position": position,
        "added_headings": preview.get("added_headings") or [],
        "message": "Analyzed paper image and updated the note section.",
        "image": image_payload,
        "analysis": _limit_text(analysis_text, 4_000),
        "preview": {
            "changed": bool(preview.get("changed")),
            "before": preview.get("before") or {},
            "after": preview.get("after") or {},
            "added_headings": preview.get("added_headings") or [],
            "summary": preview.get("summary") or "",
        },
        "write": {
            "changed": bool(write.get("changed")),
            "before": write.get("before") or {},
            "after": write.get("after") or {},
            "message": write.get("message") or "",
        },
        "validation": validation,
    }


def _resolve_workflow_image(
    args: dict[str, Any],
    *,
    note_id: str,
    library_path: Path | None = None,
    papers_dir: Path | None = None,
    paper_page_cache_dir: Path | None = None,
    media_store: Any | None = None,
) -> dict[str, Any]:
    artifact_id = normalize_text(args.get("artifact_id") or args.get("artifactId"))
    if artifact_id:
        artifact_payload = _artifact_payload(media_store, artifact_id)
        return {
            "success": True,
            "source": "artifact",
            "artifact_id": artifact_id,
            "artifact": artifact_payload,
        }

    if args.get("page") is None:
        return tool_error(
            "image_source_required",
            "Provide artifact_id or page so the workflow knows which image to analyze.",
            note_id=note_id,
        )

    page = positive_int(args.get("page"), default=1, maximum=100_000)
    scale = positive_float(args.get("scale"), default=2.0, minimum=0.5, maximum=4.0)
    rendered = render_paper_page(
        {"note_id": note_id, "page": page, "scale": scale},
        library_path=library_path,
        papers_dir=papers_dir,
        paper_page_cache_dir=paper_page_cache_dir,
        media_store=media_store,
    )
    if not rendered.get("success"):
        return rendered
    rendered_artifact_id = normalize_text(rendered.get("artifact_id"))
    if not rendered_artifact_id:
        return tool_error(
            "image_artifact_missing",
            "PDF page rendered, but no media artifact was registered for image analysis.",
            note_id=note_id,
            page=page,
        )
    return {
        "success": True,
        "source": "pdf_page",
        "page": page,
        "scale": scale,
        "artifact_id": rendered_artifact_id,
        "artifact": rendered.get("artifact") or _artifact_payload(media_store, rendered_artifact_id),
        "rendered": {
            "width": rendered.get("width"),
            "height": rendered.get("height"),
            "relative_path": rendered.get("relative_path") or "",
            "preview_url": rendered.get("preview_url") or "",
            "download_url": rendered.get("download_url") or "",
        },
    }


__all__ = [name for name in globals() if not name.startswith("__")]
