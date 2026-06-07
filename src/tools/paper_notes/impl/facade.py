from __future__ import annotations

# Registers model-visible Paper Notes tools and routes facade actions to domain modules.

from pathlib import Path
from typing import Any

from tools.paper_notes.impl.formatting import normalize_text
from tools.paper_notes.impl.annotations import create_annotation, delete_annotation, update_annotation
from tools.paper_notes.impl.common import resolve_note, tool_error, truthy
from tools.paper_notes.impl.media import write_note_from_paper_image
from tools.paper_notes.impl.notes import (
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
    write_note_section,
)
from tools.paper_notes.impl.paper import extract_paper_images, read_paper_text, render_paper_page, search_paper_text
from tools.paper_notes.schemas import (
    get_note_context_parameters,
    manage_annotations_parameters,
    read_paper_parameters,
    review_note_parameters,
    search_notes_parameters,
    write_note_media_parameters,
    write_note_parameters,
)


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
    args, correction = _read_paper_args_with_note_id_correction(args, action=action, library_path=library_path)
    if action == "search_text":
        return _with_note_id_correction(
            search_paper_text(args, library_path=library_path, papers_dir=papers_dir, paper_text_cache_dir=paper_text_cache_dir),
            correction,
        )
    if action == "read_pages":
        return _with_note_id_correction(
            read_paper_text(args, library_path=library_path, papers_dir=papers_dir, paper_text_cache_dir=paper_text_cache_dir),
            correction,
        )
    if action == "render_page":
        return _with_note_id_correction(
            render_paper_page(args, library_path=library_path, papers_dir=papers_dir, paper_page_cache_dir=paper_page_cache_dir, media_store=media_store),
            correction,
        )
    if action == "extract_images":
        return _with_note_id_correction(
            extract_paper_images(args, library_path=library_path, papers_dir=papers_dir, paper_image_cache_dir=paper_image_cache_dir, media_store=media_store),
            correction,
        )
    if action == "analyze_image":
        if not callable(paper_image_analyzer):
            return tool_error("image_analysis_unavailable", "Image analysis is not available in this registry.", note_id=normalize_text(args.get("note_id")))
        return paper_image_analyzer({
            "artifact_id": args.get("artifact_id"),
            "path": args.get("path"),
            "question": args.get("query") or args.get("question") or "Analyze this paper image.",
        })
    return tool_error("invalid_action", "action must be search_text, read_pages, render_page, extract_images, or analyze_image.", note_id=normalize_text(args.get("note_id")))


def _read_paper_args_with_note_id_correction(
    args: dict[str, Any],
    *,
    action: str,
    library_path: Path | None,
) -> tuple[dict[str, Any], dict[str, str] | None]:
    if action not in {"search_text", "read_pages", "render_page", "extract_images"}:
        return args, None
    note_result = resolve_note(args, library_path=library_path, allow_similar_id=True)
    if "error" in note_result:
        return args, None
    if not note_result.get("note_id_corrected"):
        return args, None
    note = note_result.get("note") if isinstance(note_result.get("note"), dict) else {}
    corrected_note_id = normalize_text(note.get("id"))
    requested_note_id = normalize_text(note_result.get("requested_note_id"))
    if not corrected_note_id or corrected_note_id == requested_note_id:
        return args, None
    return {**args, "note_id": corrected_note_id}, {
        "requested_note_id": requested_note_id,
        "corrected_note_id": corrected_note_id,
    }


def _with_note_id_correction(payload: dict[str, Any], correction: dict[str, str] | None) -> dict[str, Any]:
    if not correction:
        return payload
    return {
        **payload,
        "requested_note_id": correction["requested_note_id"],
        "note_id_corrected": True,
    }


def write_note(
    args: dict[str, Any],
    *,
    library_path: Path | None = None,
    html_dir: Path | None = None,
    media_store: Any | None = None,
) -> dict[str, Any]:
    action = normalize_text(args.get("action")).lower()
    if action == "append_to_section":
        result = write_note_section(
            {**args, "position": normalize_text(args.get("position") or "append").lower()},
            library_path=library_path,
            html_dir=html_dir,
            media_store=media_store,
        )
        return _with_html_validation(result, library_path=library_path, html_dir=html_dir)
    if action == "write_section":
        position = normalize_text(args.get("position")).lower()
        result = (
            write_note_section({**args, "position": position}, library_path=library_path, html_dir=html_dir, media_store=media_store)
            if position
            else replace_note_section(args, library_path=library_path, html_dir=html_dir, media_store=media_store)
        )
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
