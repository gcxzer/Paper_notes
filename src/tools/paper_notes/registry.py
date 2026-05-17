from __future__ import annotations

# Registers model-visible Paper Notes tools and routes facade actions to domain modules.

from pathlib import Path
from typing import Any

from app_infra.formatting import normalize_text
from tools.paper_notes.annotations import create_annotation, delete_annotation, update_annotation
from tools.paper_notes.common import tool_error, truthy
from tools.paper_notes.manifest import TOOL_GROUP
from tools.paper_notes.media import write_note_from_paper_image
from tools.paper_notes.notes import (
    append_note_section,
    build_note_context,
    delete_note_section,
    insert_note_image,
    preview_note_diff,
    read_note_html,
    replace_note_section,
    _resolve_media_source_args,
    search_library,
    update_note_metadata,
    validate_note_html,
)
from tools.paper_notes.paper import extract_paper_images, read_paper_text, render_paper_page, search_paper_text
from tools.paper_notes.schemas import (
    get_note_context_parameters,
    manage_annotations_parameters,
    read_paper_parameters,
    review_note_parameters,
    search_notes_parameters,
    write_note_media_parameters,
    write_note_parameters,
)
from tools.registry import ToolDefinition, ToolRegistry


PAPER_NOTES_TOOLSET = "paper_notes"

def create_paper_notes_registry(
    registry: ToolRegistry | None = None,
    *,
    library_path: Path | None = None,
    annotations_dir: Path | None = None,
    html_dir: Path | None = None,
    papers_dir: Path | None = None,
    paper_text_cache_dir: Path | None = None,
    paper_page_cache_dir: Path | None = None,
    paper_image_cache_dir: Path | None = None,
    media_store: Any | None = None,
    paper_image_analyzer: Any | None = None,
) -> ToolRegistry:
    registry = registry or ToolRegistry()
    registry.register_group(TOOL_GROUP)
    _register_paper_notes_facade_tools(
        registry,
        library_path=library_path,
        annotations_dir=annotations_dir,
        html_dir=html_dir,
        papers_dir=papers_dir,
        paper_text_cache_dir=paper_text_cache_dir,
        paper_page_cache_dir=paper_page_cache_dir,
        paper_image_cache_dir=paper_image_cache_dir,
        media_store=media_store,
        paper_image_analyzer=paper_image_analyzer,
    )
    return registry

def _register_paper_notes_facade_tools(
    registry: ToolRegistry,
    *,
    library_path: Path | None = None,
    annotations_dir: Path | None = None,
    html_dir: Path | None = None,
    papers_dir: Path | None = None,
    paper_text_cache_dir: Path | None = None,
    paper_page_cache_dir: Path | None = None,
    paper_image_cache_dir: Path | None = None,
    media_store: Any | None = None,
    paper_image_analyzer: Any | None = None,
) -> None:
    registry.register(ToolDefinition(
        name="search_notes",
        description=(
            "Search or list local Paper Notes metadata by title, summary, venue, date, and tags. Use concise "
            "English-first paper keywords; for non-English user requests, include likely English terms "
            "and important original-language terms. Omit query, pass an empty query, or pass '*' only when "
            "the user asks to list/count the library."
        ),
        parameters=search_notes_parameters(),
        handler=lambda args: search_library(args, library_path=library_path),
        toolset=PAPER_NOTES_TOOLSET,
        read_only=True,
        risk="read",
        kind="search",
        result_max_chars=10_000,
        metadata={"facade": True, "internal_tools": ["search_library"]},
    ))
    registry.register(ToolDefinition(
        name="get_note_context",
        description=(
            "Build a compact writing context for one note: metadata, current sections, annotations, "
            "optional note HTML, and optional PDF text snippets."
        ),
        parameters=get_note_context_parameters(),
        handler=lambda args: get_note_context(
            args,
            library_path=library_path,
            annotations_dir=annotations_dir,
            html_dir=html_dir,
            papers_dir=papers_dir,
            paper_text_cache_dir=paper_text_cache_dir,
        ),
        toolset=PAPER_NOTES_TOOLSET,
        read_only=True,
        risk="read",
        kind="read",
        result_max_chars=18_000,
        metadata={"facade": True, "internal_tools": ["get_note", "read_note_html", "list_note_sections", "read_annotations", "build_note_context"]},
    ))
    registry.register(ToolDefinition(
        name="read_paper",
        description=(
            "Read paper source material for a note. Use action=search_text for focused snippets, read_pages for "
            "page text, render_page for a page image, extract_images for figures, or analyze_image for a registered artifact."
        ),
        parameters=read_paper_parameters(),
        handler=lambda args: read_paper(
            args,
            library_path=library_path,
            papers_dir=papers_dir,
            paper_text_cache_dir=paper_text_cache_dir,
            paper_page_cache_dir=paper_page_cache_dir,
            paper_image_cache_dir=paper_image_cache_dir,
            media_store=media_store,
            paper_image_analyzer=paper_image_analyzer,
        ),
        toolset=PAPER_NOTES_TOOLSET,
        read_only=True,
        risk="read",
        kind="read",
        result_max_chars=16_000,
        metadata={
            "facade": True,
            "internal_tools": ["search_paper_text", "read_paper_text", "render_paper_page", "extract_paper_images", "analyze_paper_image"],
        },
    ))
    registry.register(ToolDefinition(
        name="write_note",
        description=(
            "Modify note HTML sections or note metadata. Use action=append_to_section for normal additions, "
            "write_section only when replacing/overwriting a section, delete_section, or update_metadata. "
            "This tool does not manage annotations or images."
        ),
        parameters=write_note_parameters(),
        handler=lambda args: write_note(args, library_path=library_path, html_dir=html_dir, media_store=media_store),
        toolset=PAPER_NOTES_TOOLSET,
        mutating=True,
        risk="write",
        kind="write",
        supports_snapshot=True,
        supports_rollback=True,
        approval_scope="note",
        affected_resources=lambda args: _write_note_resources(args),
        result_max_chars=10_000,
        metadata={"facade": True, "internal_tools": ["write_note_section", "append_note_section", "replace_note_section", "delete_note_section", "update_note_metadata"]},
    ))
    registry.register(ToolDefinition(
        name="manage_annotations",
        description=(
            "Create, update, or delete Paper Notes annotations. For create, provide either quote/query text that "
            "can be located in the PDF or explicit normalized rects/coordinates."
        ),
        parameters=manage_annotations_parameters(),
        handler=lambda args: manage_annotations(args, library_path=library_path, annotations_dir=annotations_dir, papers_dir=papers_dir),
        toolset=PAPER_NOTES_TOOLSET,
        mutating=True,
        risk="write",
        kind="write",
        supports_snapshot=True,
        supports_rollback=True,
        approval_scope="note",
        affected_resources=lambda args: [f"note-annotations:{normalize_text(args.get('note_id'))}"],
        result_max_chars=10_000,
        metadata={"facade": True, "internal_tools": ["create_annotation", "update_annotation", "delete_annotation"]},
    ))
    registry.register(ToolDefinition(
        name="write_note_media",
        description=(
            "Write note content from a paper image or insert an existing image artifact into a note. "
            "Use action=write_from_image or insert_image. User-provided local images must already be under "
            "Paper_Notes/.paper-notes/media or any subfolder; if they are elsewhere, ask the user to copy/move the file there first."
        ),
        parameters=write_note_media_parameters(),
        handler=lambda args: write_note_media(
            args,
            library_path=library_path,
            html_dir=html_dir,
            papers_dir=papers_dir,
            paper_page_cache_dir=paper_page_cache_dir,
            media_store=media_store,
            paper_image_analyzer=paper_image_analyzer,
        ),
        toolset=PAPER_NOTES_TOOLSET,
        mutating=True,
        risk="write",
        kind="write",
        supports_snapshot=True,
        supports_rollback=True,
        approval_scope="note",
        affected_resources=lambda args: [f"note-html:{normalize_text(args.get('note_id'))}"],
        result_max_chars=12_000,
        metadata={"facade": True, "internal_tools": ["write_note_from_paper_image", "insert_note_image"]},
    ))
    registry.register(ToolDefinition(
        name="review_note",
        description="Validate a note or preview a safe HTML section diff without saving changes.",
        parameters=review_note_parameters(),
        handler=lambda args: review_note(args, library_path=library_path, html_dir=html_dir, media_store=media_store),
        toolset=PAPER_NOTES_TOOLSET,
        read_only=True,
        risk="read",
        kind="read",
        result_max_chars=10_000,
        metadata={"facade": True, "internal_tools": ["validate_note_html", "preview_note_diff"]},
    ))


def _write_note_resources(args: dict[str, Any]) -> list[str]:
    note_id = normalize_text(args.get("note_id"))
    if normalize_text(args.get("action")).lower() == "update_metadata":
        return ["notes.json", f"note-metadata:{note_id}"]
    return [f"note-html:{note_id}"]


def get_note_context(
    args: dict[str, Any],
    *,
    library_path: Path | None = None,
    annotations_dir: Path | None = None,
    html_dir: Path | None = None,
    papers_dir: Path | None = None,
    paper_text_cache_dir: Path | None = None,
) -> dict[str, Any]:
    payload = build_note_context(
        args,
        library_path=library_path,
        annotations_dir=annotations_dir,
        html_dir=html_dir,
        papers_dir=papers_dir,
        paper_text_cache_dir=paper_text_cache_dir,
    )
    if not payload.get("success"):
        return payload
    if truthy(args.get("include_html")):
        html_payload = read_note_html(
            {**args, "mode": normalize_text(args.get("html_mode") or "body") or "body"},
            library_path=library_path,
            html_dir=html_dir,
        )
        payload["html"] = html_payload if html_payload.get("success") else {"error": html_payload.get("error"), "code": html_payload.get("code")}
    return payload


def search_notes(args: dict[str, Any], *, library_path: Path | None = None) -> dict[str, Any]:
    return search_library(args, library_path=library_path)


def read_paper(
    args: dict[str, Any],
    *,
    library_path: Path | None = None,
    papers_dir: Path | None = None,
    paper_text_cache_dir: Path | None = None,
    paper_page_cache_dir: Path | None = None,
    paper_image_cache_dir: Path | None = None,
    media_store: Any | None = None,
    paper_image_analyzer: Any | None = None,
) -> dict[str, Any]:
    action = normalize_text(args.get("action")).lower()
    if not action:
        if normalize_text(args.get("artifact_id") or args.get("path")):
            action = "analyze_image"
        elif args.get("page") is not None:
            action = "render_page"
        elif normalize_text(args.get("query")):
            action = "search_text"
        else:
            action = "read_pages"
    if action == "search_text":
        return search_paper_text(args, library_path=library_path, papers_dir=papers_dir, paper_text_cache_dir=paper_text_cache_dir)
    if action == "read_pages":
        return read_paper_text(args, library_path=library_path, papers_dir=papers_dir, paper_text_cache_dir=paper_text_cache_dir)
    if action == "render_page":
        return render_paper_page(args, library_path=library_path, papers_dir=papers_dir, paper_page_cache_dir=paper_page_cache_dir, media_store=media_store)
    if action == "extract_images":
        return extract_paper_images(args, library_path=library_path, papers_dir=papers_dir, paper_image_cache_dir=paper_image_cache_dir, media_store=media_store)
    if action == "analyze_image":
        if not callable(paper_image_analyzer):
            return tool_error("image_analysis_unavailable", "Image analysis is not available in this registry.", note_id=normalize_text(args.get("note_id")))
        return paper_image_analyzer({
            "artifact_id": args.get("artifact_id"),
            "path": args.get("path"),
            "question": args.get("query") or args.get("question") or "Analyze this paper image.",
        })
    return tool_error("invalid_action", "action must be search_text, read_pages, render_page, extract_images, or analyze_image.", note_id=normalize_text(args.get("note_id")))


def write_note(
    args: dict[str, Any],
    *,
    library_path: Path | None = None,
    html_dir: Path | None = None,
    media_store: Any | None = None,
) -> dict[str, Any]:
    action = normalize_text(args.get("action")).lower()
    if action == "append_to_section":
        result = append_note_section(args, library_path=library_path, html_dir=html_dir, media_store=media_store)
        return _with_html_validation(result, library_path=library_path, html_dir=html_dir)
    if action == "write_section":
        result = replace_note_section(args, library_path=library_path, html_dir=html_dir, media_store=media_store)
        if result.get("code") == "heading_not_found":
            result = append_note_section(args, library_path=library_path, html_dir=html_dir, media_store=media_store)
        return _with_html_validation(result, library_path=library_path, html_dir=html_dir)
    if action == "delete_section":
        result = delete_note_section(args, library_path=library_path, html_dir=html_dir)
        return _with_html_validation(result, library_path=library_path, html_dir=html_dir)
    if action == "update_metadata":
        return update_note_metadata(_without_action(args), library_path=library_path)
    return tool_error(
        "invalid_action",
        "action must be write_section, append_to_section, delete_section, or update_metadata.",
        note_id=normalize_text(args.get("note_id")),
    )


def manage_annotations(
    args: dict[str, Any],
    *,
    library_path: Path | None = None,
    annotations_dir: Path | None = None,
    papers_dir: Path | None = None,
) -> dict[str, Any]:
    action = normalize_text(args.get("action")).lower()
    if action == "create":
        return create_annotation(_without_action(args), library_path=library_path, annotations_dir=annotations_dir, papers_dir=papers_dir)
    if action == "update":
        return update_annotation(_without_action(args), annotations_dir=annotations_dir)
    if action == "delete":
        return delete_annotation(_without_action(args), annotations_dir=annotations_dir)
    return tool_error("invalid_action", "action must be create, update, or delete.", note_id=normalize_text(args.get("note_id")))


def write_note_media(
    args: dict[str, Any],
    *,
    library_path: Path | None = None,
    html_dir: Path | None = None,
    papers_dir: Path | None = None,
    paper_page_cache_dir: Path | None = None,
    media_store: Any | None = None,
    paper_image_analyzer: Any | None = None,
) -> dict[str, Any]:
    action = normalize_text(args.get("action")).lower()
    if action == "write_from_image":
        return write_note_from_paper_image(
            args,
            library_path=library_path,
            html_dir=html_dir,
            papers_dir=papers_dir,
            paper_page_cache_dir=paper_page_cache_dir,
            media_store=media_store,
            paper_image_analyzer=paper_image_analyzer,
        )
    if action == "insert_image":
        result = insert_note_image(
            args,
            library_path=library_path,
            html_dir=html_dir,
            media_store=media_store,
        )
        return _with_html_validation(result, library_path=library_path, html_dir=html_dir)
    return tool_error(
        "invalid_action",
        "action must be write_from_image or insert_image.",
        note_id=normalize_text(args.get("note_id")),
    )


def _without_action(args: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in args.items() if key != "action"}


def review_note(
    args: dict[str, Any],
    *,
    library_path: Path | None = None,
    html_dir: Path | None = None,
    media_store: Any | None = None,
) -> dict[str, Any]:
    action = normalize_text(args.get("action") or "validate_html").lower()
    if action == "validate_html":
        return validate_note_html(args, library_path=library_path, html_dir=html_dir)
    if action == "preview_note_diff":
        resolved_args, error = _resolve_media_source_args(args, media_store)
        if error:
            return error
        return preview_note_diff(resolved_args, library_path=library_path, html_dir=html_dir)
    return tool_error("invalid_action", "action must be validate_html or preview_note_diff.", note_id=normalize_text(args.get("note_id")))


def _with_html_validation(
    result: dict[str, Any],
    *,
    library_path: Path | None,
    html_dir: Path | None,
) -> dict[str, Any]:
    if not result.get("success"):
        return result
    note_id = normalize_text(result.get("note_id"))
    validation = validate_note_html({"note_id": note_id}, library_path=library_path, html_dir=html_dir)
    return {
        **result,
        "validation": validation,
        "success": bool(validation.get("success") and validation.get("valid") is not False),
    }

__all__ = [name for name in globals() if not name.startswith("__")]
