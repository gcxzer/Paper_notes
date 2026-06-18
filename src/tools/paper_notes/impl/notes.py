"""说明：实现笔记元数据和 HTML 内容工具动作。

作用：支持读取、审阅和更新 note 文本内容，服务于写笔记相关工具。
"""

from __future__ import annotations

# Note library, HTML section, metadata, context, and review operations.

import re
from pathlib import Path
from typing import Any

from app_infra.formatting import normalize_text
from library.store import find_note, normalize_tags, read_library, write_library
from library.annotations import read_annotations as read_note_annotations
from tools.paper_notes.impl.artifacts import _resolve_image_artifact_payload
from tools.paper_notes.impl.common import (
    positive_int,
    resolve_note,
    tool_error,
)
from tools.paper_notes.impl.note_html_body import (
    NOTE_SECTION_POSITIONS,
    added_heading_names,
    apply_body_update,
    collect_headings,
    delete_heading_section,
    diff_summary,
    format_note_body_html,
    image_figure_html,
    load_note_html_body,
    note_body_child_indent,
    note_body_match,
    note_html_path,
    prepare_note_section_update,
    read_note_html_body_document,
    resolve_media_source_args,
    resolve_note_html_path,
    validate_html_document,
    write_note_html_body,
)

__all__ = [
    "append_note_section",
    "build_note_context",
    "delete_note_section",
    "insert_note_image",
    "preview_note_diff",
    "read_note_html",
    "replace_note_section",
    "search_library",
    "update_note_metadata",
    "validate_note_html",
    "write_note_section",
]

_METADATA_INPUT_KEYS = {
    "note_id",
    "id",
    "summary",
    "tags",
    "venue",
    "date",
    "category_id",
    "categoryId",
    "collection",
    "collection_name",
    "collectionName",
    "collection_path",
    "collectionPath",
}
_METADATA_COLLECTION_KEYS = (
    "collection",
    "collection_name",
    "collectionName",
    "collection_path",
    "collectionPath",
)



def _note_score(note: dict[str, Any], query: str) -> int:
    score = 0
    title = str(note.get("title") or "").lower()
    summary = str(note.get("summary") or "").lower()
    venue = str(note.get("venue") or "").lower()
    date = str(note.get("date") or "").lower()
    tags = " ".join(str(tag).lower() for tag in note.get("tags", []) if tag)
    haystack = {
        "title": title,
        "tags": tags,
        "summary": summary,
        "venue": venue,
        "date": date,
    }

    if query in title:
        score += 10
    if query in tags:
        score += 6
    if query in summary:
        score += 4
    if query in venue:
        score += 2
    if query in date:
        score += 1
    terms = [
        term for term in re.findall(r"[\w\u4e00-\u9fff]+", query.casefold())
        if term and len(term) > 1
    ]
    for term in terms:
        if term in title:
            score += 5
        if term in tags:
            score += 3
        if term in summary:
            score += 2
        if term in venue or term in date:
            score += 1
    if terms and all(any(term in value for value in haystack.values()) for term in terms):
        score += 2
    return score


def _note_summary(note: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": note.get("id", ""),
        "title": note.get("title", ""),
        "summary": note.get("summary", ""),
        "venue": note.get("venue", ""),
        "date": note.get("date", ""),
        "tags": note.get("tags", []),
        "categoryId": note.get("categoryId", ""),
        "href": note.get("href", ""),
        "htmlHref": note.get("htmlHref", ""),
    }


def _note_detail(note: dict[str, Any], library: dict[str, Any] | None = None) -> dict[str, Any]:
    collection = _collection_metadata(library, note.get("categoryId", "")) if library else {}
    return {
        "id": note.get("id", ""),
        "title": note.get("title", ""),
        "summary": note.get("summary", ""),
        "venue": note.get("venue", ""),
        "date": note.get("date", ""),
        "tags": note.get("tags", []),
        "categoryId": note.get("categoryId", ""),
        **collection,
        "href": note.get("href", ""),
        "htmlHref": note.get("htmlHref", ""),
        "pdfStorageKey": note.get("pdfStorageKey", ""),
    }


def _collection_metadata(library: dict[str, Any] | None, category_id: Any) -> dict[str, str]:
    category = _category_by_id(library, normalize_text(category_id))
    if not category:
        return {"collectionName": "", "collectionPath": ""}
    return {
        "collectionName": normalize_text(category.get("name")),
        "collectionPath": _collection_path(library, normalize_text(category.get("id"))),
    }


def _resolve_collection_id(library: dict[str, Any], value: str) -> str:
    target = _normalize_collection_lookup(value)
    if not target:
        return ""
    for category in _leaf_categories(library):
        if normalize_text(category.get("id")) == value:
            return normalize_text(category.get("id"))
    exact_matches = [
        normalize_text(category.get("id"))
        for category in _leaf_categories(library)
        if _normalize_collection_lookup(category.get("name")) == target
        or _normalize_collection_lookup(_collection_path(library, category.get("id"))) == target
    ]
    return exact_matches[0] if len(exact_matches) == 1 else ""


def _collection_path(library: dict[str, Any] | None, category_id: Any) -> str:
    category = _category_by_id(library, normalize_text(category_id))
    if not category:
        return ""
    parent_id = normalize_text(category.get("parentId"))
    if not parent_id:
        return normalize_text(category.get("name"))
    parent = _category_by_id(library, parent_id)
    return f"{normalize_text(parent.get('name'))} / {normalize_text(category.get('name'))}" if parent else normalize_text(category.get("name"))


def _category_by_id(library: dict[str, Any] | None, category_id: str) -> dict[str, Any] | None:
    if not library or not category_id:
        return None
    return next((category for category in library.get("categories", []) if category.get("id") == category_id), None)


def _leaf_categories(library: dict[str, Any]) -> list[dict[str, Any]]:
    categories = [category for category in library.get("categories", []) if isinstance(category, dict)]
    parent_ids = {normalize_text(category.get("parentId")) for category in categories if normalize_text(category.get("parentId"))}
    return [category for category in categories if normalize_text(category.get("id")) not in parent_ids]


def _normalize_collection_lookup(value: Any) -> str:
    return re.sub(r"\s*/\s*", "/", normalize_text(value).lower())



def search_library(args: dict[str, Any], *, library_path: Path | None = None) -> dict[str, Any]:
    query = normalize_text(args.get("query")).lower()
    limit = positive_int(args.get("limit"), default=10, maximum=25)
    library = read_library(library_path) if library_path is not None else read_library()
    notes_source = [note for note in library.get("notes", []) if isinstance(note, dict)]
    if not query or query in {"*", "all"}:
        sorted_notes = sorted(
            notes_source,
            key=lambda note: (
                str(note.get("date") or ""),
                str(note.get("title") or "").lower(),
            ),
            reverse=True,
        )
        notes = [_note_summary(note) for note in sorted_notes[:limit]]
        return {
            "query": query,
            "mode": "list",
            "total": len(notes_source),
            "count": len(notes),
            "notes": notes,
        }

    scored_notes = []
    for note in notes_source:
        score = _note_score(note, query)
        if score > 0:
            scored_notes.append((score, note))

    scored_notes.sort(key=lambda item: (-item[0], str(item[1].get("title") or "").lower()))
    notes = [_note_summary(note) for _, note in scored_notes[:limit]]
    return {
        "query": query,
        "count": len(notes),
        "notes": notes,
    }


def get_note(args: dict[str, Any], *, library_path: Path | None = None) -> dict[str, Any]:
    note_id = normalize_text(args.get("note_id") or args.get("id"))
    if not note_id:
        return {"error": "note_id is required"}

    library = read_library(library_path) if library_path is not None else read_library()
    note = find_note(library, note_id)
    if note is None:
        return {"error": f"Note not found: {note_id}"}
    return {"note": _note_detail(note, library)}


def read_annotations_tool(args: dict[str, Any], *, annotations_dir: Path | None = None) -> dict[str, Any]:
    note_id = normalize_text(args.get("note_id") or args.get("id"))
    if not note_id:
        return {"error": "note_id is required"}

    payload = (
        read_note_annotations(note_id, annotations_dir)
        if annotations_dir is not None
        else read_note_annotations(note_id)
    )
    if payload is None:
        return {"error": "note_id is required"}
    annotations = payload.get("annotations") if isinstance(payload, dict) else []
    return {
        "note_id": note_id,
        "annotations": annotations if isinstance(annotations, list) else [],
    }


def read_note_html(
    args: dict[str, Any],
    *,
    library_path: Path | None = None,
    html_dir: Path | None = None,
) -> dict[str, Any]:
    note_result = resolve_note(args, library_path=library_path)
    if "error" in note_result:
        return note_result
    note = note_result["note"]
    html_path = note_html_path(note, html_dir=html_dir)
    if html_path is None:
        return tool_error("note_html_missing", "Note has no local HTML path.", note_id=note["id"])
    try:
        document = html_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return tool_error("note_html_not_found", f"HTML note file was not found: {html_path.name}", note_id=note["id"])

    mode = normalize_text(args.get("mode") or "body").lower()
    if mode not in {"body", "full"}:
        return tool_error("invalid_mode", "mode must be body or full.", note_id=note["id"])
    if mode == "body":
        match = note_body_match(document)
        if match is None:
            return tool_error("note_body_missing", "HTML note does not contain a .note-body element.", note_id=note["id"])
        content = match.group("body").strip()
    else:
        content = document
    return {
        "success": True,
        "note_id": note["id"],
        "mode": mode,
        "html": content,
        "chars": len(content),
    }


def list_note_sections(
    args: dict[str, Any],
    *,
    library_path: Path | None = None,
    html_dir: Path | None = None,
) -> dict[str, Any]:
    payload = read_note_html({**args, "mode": "body"}, library_path=library_path, html_dir=html_dir)
    if not payload.get("success"):
        return payload
    sections = collect_headings(str(payload.get("html") or ""))
    return {
        "success": True,
        "note_id": payload["note_id"],
        "count": len(sections),
        "sections": sections,
    }


def build_note_context(
    args: dict[str, Any],
    *,
    library_path: Path | None = None,
    annotations_dir: Path | None = None,
    html_dir: Path | None = None,
) -> dict[str, Any]:
    note_result = get_note(args, library_path=library_path)
    if "error" in note_result:
        return note_result
    note = note_result["note"]
    sections_payload = list_note_sections(args, library_path=library_path, html_dir=html_dir)
    annotations_payload = read_annotations_tool(args, annotations_dir=annotations_dir)
    return {
        "success": True,
        "note_id": note["id"],
        "note": note,
        "rag": _rag_status_for_note(note["id"], library_path=library_path),
        "sections": sections_payload.get("sections", []) if sections_payload.get("success") else [],
        "annotations": annotations_payload.get("annotations", []) if not annotations_payload.get("error") else [],
    }


def _rag_status_for_note(note_id: str, *, library_path: Path | None = None) -> dict[str, Any]:
    enabled = False
    try:
        from app_config import load_app_config

        enabled = bool(load_app_config().rag.query_enabled())
    except Exception:
        enabled = False
    try:
        from rag.service import get_rag_service

        status = get_rag_service().status(note_id=note_id, library_path=library_path)
    except Exception as error:
        return {
            "enabled": enabled,
            "ready": False,
            "code": getattr(error, "code", "rag_status_failed"),
            "error": str(error),
        }
    return {
        "enabled": enabled,
        "ready": bool(status.get("ready")),
        "indexKey": status.get("indexKey", ""),
        "indexes": status.get("indexes", {}),
    }


def validate_note_html(
    args: dict[str, Any],
    *,
    library_path: Path | None = None,
    html_dir: Path | None = None,
) -> dict[str, Any]:
    note_result = resolve_note(args, library_path=library_path)
    if "error" in note_result:
        return note_result
    note = note_result["note"]
    html_path = note_html_path(note, html_dir=html_dir)
    if html_path is None:
        return tool_error("note_html_missing", "Note has no local HTML path.", note_id=note["id"])
    try:
        document = html_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return tool_error("note_html_not_found", f"HTML note file was not found: {html_path.name}", note_id=note["id"])
    issues = validate_html_document(document)
    match = note_body_match(document)
    body = match.group("body") if match else ""
    sections = collect_headings(body)
    return {
        "success": True,
        "valid": not issues,
        "note_id": note["id"],
        "issues": issues,
        "section_count": len(sections),
        "body_chars": len(body),
        "path": str(html_path),
    }


def preview_note_diff(
    args: dict[str, Any],
    *,
    library_path: Path | None = None,
    html_dir: Path | None = None,
) -> dict[str, Any]:
    loaded, load_error = load_note_html_body(args, library_path=library_path, html_dir=html_dir)
    if load_error:
        return load_error
    assert loaded is not None
    note = loaded.note
    html_path = loaded.html_path
    document = loaded.document
    match = loaded.match
    update, update_error = prepare_note_section_update(args, document=document, match=match, note_id=note["id"])
    if update_error:
        return update_error
    assert update is not None
    return {
        "success": True,
        "changed": update.next_body != update.current_body,
        "note_id": note["id"],
        "heading": update.heading,
        "position": update.position,
        "path": str(html_path),
        "before": {
            "section_count": len(update.before_headings),
            "body_chars": len(update.current_body),
        },
        "after": {
            "section_count": len(update.after_headings),
            "body_chars": len(update.next_body),
        },
        "added_headings": added_heading_names(update.before_headings, update.after_headings),
        "summary": diff_summary(update.current_body, update.next_body),
        "snapshot_id": "",
    }


def write_note_section(
    args: dict[str, Any],
    *,
    library_path: Path | None = None,
    html_dir: Path | None = None,
    media_store: Any | None = None,
) -> dict[str, Any]:
    args, media_error = resolve_media_source_args(args, media_store)
    if media_error:
        return media_error
    loaded, load_error = load_note_html_body(args, library_path=library_path, html_dir=html_dir)
    if load_error:
        return load_error
    assert loaded is not None
    note = loaded.note
    html_path = loaded.html_path
    document = loaded.document
    match = loaded.match

    update, update_error = prepare_note_section_update(args, document=document, match=match, note_id=note["id"])
    if update_error:
        return update_error
    assert update is not None
    before = {
        "section_count": len(update.before_headings),
        "body_chars": len(update.current_body),
    }

    next_document = write_note_html_body(html_path, document, match, update.next_body)
    return {
        "success": True,
        "changed": next_document != document,
        "note_id": note["id"],
        "heading": update.heading,
        "position": update.position,
        "added_headings": added_heading_names(update.before_headings, update.after_headings),
        "message": f"Updated HTML note section using {update.position}.",
        "section_count": len(update.after_headings),
        "html_chars": len(next_document),
        "before": before,
        "after": {
            "section_count": len(update.after_headings),
            "body_chars": len(update.next_body),
        },
    }


def append_note_section(
    args: dict[str, Any],
    *,
    library_path: Path | None = None,
    html_dir: Path | None = None,
    media_store: Any | None = None,
) -> dict[str, Any]:
    return write_note_section({**args, "position": "append"}, library_path=library_path, html_dir=html_dir, media_store=media_store)


def replace_note_section(
    args: dict[str, Any],
    *,
    library_path: Path | None = None,
    html_dir: Path | None = None,
    media_store: Any | None = None,
) -> dict[str, Any]:
    return write_note_section({**args, "position": "replace_heading"}, library_path=library_path, html_dir=html_dir, media_store=media_store)


def delete_note_section(
    args: dict[str, Any],
    *,
    library_path: Path | None = None,
    html_dir: Path | None = None,
) -> dict[str, Any]:
    note, html_path, path_error = resolve_note_html_path(args, library_path=library_path, html_dir=html_dir)
    if path_error:
        return path_error
    assert note is not None
    assert html_path is not None
    heading = normalize_text(args.get("heading"))
    if not heading:
        return tool_error("heading_required", "heading is required.", note_id=note["id"])
    document, match, body_error = read_note_html_body_document(note, html_path)
    if body_error:
        return body_error
    assert match is not None

    current_body = match.group("body").strip()
    before = {
        "section_count": len(collect_headings(current_body)),
        "body_chars": len(current_body),
    }
    next_body, changed = delete_heading_section(current_body, heading)
    if not changed:
        return tool_error("heading_not_found", f"Could not find heading: {heading}", note_id=note["id"])
    next_body = format_note_body_html(next_body, base_indent=note_body_child_indent(document, match))
    after_headings = collect_headings(next_body)

    next_document = write_note_html_body(html_path, document, match, next_body)
    return {
        "success": True,
        "changed": next_document != document,
        "note_id": note["id"],
        "heading": heading,
        "message": "Deleted HTML note section.",
        "section_count": len(after_headings),
        "html_chars": len(next_document),
        "before": before,
        "after": {
            "section_count": len(after_headings),
            "body_chars": len(next_body),
        },
    }


def insert_note_image(
    args: dict[str, Any],
    *,
    library_path: Path | None = None,
    html_dir: Path | None = None,
    media_store: Any | None = None,
) -> dict[str, Any]:
    note, html_path, path_error = resolve_note_html_path(args, library_path=library_path, html_dir=html_dir)
    if path_error:
        return path_error
    assert note is not None
    assert html_path is not None
    if media_store is None:
        return tool_error("media_store_unavailable", "Media store is not available.", note_id=note["id"])

    artifact_ref = normalize_text(args.get("artifact_id"))
    if not artifact_ref:
        return tool_error("artifact_id_required", "artifact_id is required.", note_id=note["id"])
    artifact = _resolve_image_artifact_payload(media_store, artifact_ref)
    if not artifact or not normalize_text(artifact.get("url")):
        return tool_error("image_artifact_not_found", f"Image artifact was not found: {artifact_ref}", note_id=note["id"])
    if normalize_text(artifact.get("kind") or "image") != "image":
        return tool_error("image_artifact_required", "insert_image requires an image artifact.", note_id=note["id"], artifact_id=artifact_ref)
    artifact_id = normalize_text(artifact.get("id") or artifact_ref)

    document, match, body_error = read_note_html_body_document(note, html_path)
    if body_error:
        return body_error
    assert match is not None

    heading = normalize_text(args.get("heading"))
    position = normalize_text(args.get("position") or ("after_heading" if heading else "append")).lower()
    if position not in NOTE_SECTION_POSITIONS:
        return tool_error("invalid_position", "position must be append, prepend, after_heading, or replace_heading.", note_id=note["id"])

    figure_html = image_figure_html(
        artifact=artifact,
        caption=normalize_text(args.get("caption")),
        alt=normalize_text(args.get("alt")),
    )
    current_body = match.group("body").strip()
    before = {
        "section_count": len(collect_headings(current_body)),
        "body_chars": len(current_body),
    }
    next_body, changed = apply_body_update(
        current_body,
        fragment=figure_html,
        heading=heading,
        position=position,
    )
    if not changed:
        return tool_error("heading_not_found", f"Could not find heading: {heading}", note_id=note["id"])
    next_body = format_note_body_html(next_body, base_indent=note_body_child_indent(document, match))

    next_document = write_note_html_body(html_path, document, match, next_body)
    return {
        "success": True,
        "changed": next_document != document,
        "note_id": note["id"],
        "heading": heading,
        "position": position,
        "artifact_id": artifact_id,
        "message": "Inserted image into HTML note.",
        "image": artifact,
        "before": before,
        "after": {
            "section_count": len(collect_headings(next_body)),
            "body_chars": len(next_body),
        },
    }


def _unsupported_metadata_fields(args: dict[str, Any]) -> list[str]:
    return sorted(key for key in args if key not in _METADATA_INPUT_KEYS)


def _metadata_collection_value(args: dict[str, Any]) -> str:
    return normalize_text(next((args.get(key) for key in _METADATA_COLLECTION_KEYS if args.get(key)), ""))


def _metadata_updates_from_args(
    args: dict[str, Any],
    *,
    library: dict[str, Any],
    note_id: str,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    updates: dict[str, Any] = {}
    if "summary" in args:
        updates["summary"] = normalize_text(args.get("summary"))
    if "tags" in args:
        raw_tags = args.get("tags")
        if isinstance(raw_tags, str):
            raw_tags = [tag for tag in re.split(r"[,，]", raw_tags)]
        updates["tags"] = normalize_tags(raw_tags)
    if "venue" in args:
        updates["venue"] = normalize_text(args.get("venue"))
    if "date" in args:
        updates["date"] = normalize_text(args.get("date"))
    if "category_id" in args or "categoryId" in args:
        updates["categoryId"] = normalize_text(args.get("category_id") or args.get("categoryId"))

    collection_value = _metadata_collection_value(args)
    if collection_value:
        resolved_category_id = _resolve_collection_id(library, collection_value)
        if not resolved_category_id:
            return {}, tool_error("collection_not_found", f"Collection not found: {collection_value}", note_id=note_id)
        updates["categoryId"] = resolved_category_id

    if not updates:
        return {}, tool_error("no_metadata_updates", "Provide at least one metadata field to update.", note_id=note_id)
    return updates, None


def update_note_metadata(args: dict[str, Any], *, library_path: Path | None = None) -> dict[str, Any]:
    note_id = normalize_text(args.get("note_id") or args.get("id"))
    if not note_id:
        return tool_error("note_id_required", "note_id is required")

    unknown = _unsupported_metadata_fields(args)
    if unknown:
        return tool_error("unknown_metadata_fields", f"Unsupported metadata fields: {', '.join(unknown)}", note_id=note_id)

    path = library_path if library_path is not None else None
    library = read_library(path) if path is not None else read_library()
    note = find_note(library, note_id)
    if note is None:
        return tool_error("note_not_found", f"Note not found: {note_id}", note_id=note_id)

    before = _note_detail(note, library)
    updates, update_error = _metadata_updates_from_args(args, library=library, note_id=note_id)
    if update_error:
        return update_error

    note.update(updates)
    saved = write_library(library, path) if path is not None else write_library(library)
    after_note = find_note(saved, note_id) or note
    return {
        "success": True,
        "changed": before != _note_detail(after_note, saved),
        "note_id": note_id,
        "message": "Updated note metadata.",
        "before": before,
        "after": _note_detail(after_note, saved),
    }
