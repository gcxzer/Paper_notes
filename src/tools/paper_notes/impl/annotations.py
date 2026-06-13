from __future__ import annotations

# Annotation create/update/delete logic, including PDF quote-to-rect location.

import re
import time
from pathlib import Path
from typing import Any

from app_infra.formatting import normalize_text
from library.annotations import read_annotations as read_note_annotations, write_annotations
from tools.paper_notes.impl.common import (
    positive_int,
    relative_project_path,
    resolve_note,
    tool_error,
)
from tools.paper_notes.impl.paper import _import_pymupdf, _resolved_pdf_path_for_note


ANNOTATION_COLORS = {"yellow", "green", "blue", "red", "purple"}
ANNOTATION_TYPES = {"highlight", "underline", "area", "note"}

def create_annotation(
    args: dict[str, Any],
    *,
    library_path: Path | None = None,
    annotations_dir: Path | None = None,
    papers_dir: Path | None = None,
) -> dict[str, Any]:
    note_id = normalize_text(args.get("note_id") or args.get("id"))
    if not note_id:
        return tool_error("note_id_required", "note_id is required")
    annotations = _read_annotation_list(note_id, annotations_dir=annotations_dir)
    annotation_args = dict(args)
    if not _has_annotation_geometry(annotation_args):
        located = _locate_annotation_target(annotation_args, library_path=library_path, papers_dir=papers_dir)
        if located.get("success"):
            current_quote = normalize_text(annotation_args.get("quote"))
            located_quote = normalize_text(located.get("quote"))
            next_quote = located_quote if not current_quote or _annotation_match_text(current_quote) == _annotation_match_text(located_quote) else current_quote
            annotation_args.update({
                "page": located["page"],
                "rects": located["rects"],
                "quote": next_quote,
            })
        elif normalize_text(annotation_args.get("quote") or annotation_args.get("query")):
            return {**located, "note_id": note_id}
    annotation = _annotation_from_args(annotation_args, existing_annotations=annotations, require_geometry=True)
    if "error" in annotation:
        return {**annotation, "note_id": note_id}
    annotation_id = normalize_text(annotation["id"])
    if any(isinstance(entry, dict) and normalize_text(entry.get("id")) == annotation_id for entry in annotations):
        return tool_error("annotation_exists", f"Annotation already exists: {annotation_id}", note_id=note_id)
    before_count = len(annotations)
    annotations.append(annotation)
    _write_annotation_list(note_id, annotations, annotations_dir=annotations_dir)
    return {
        "success": True,
        "changed": True,
        "note_id": note_id,
        "annotation_id": annotation_id,
        "message": "Created annotation.",
        "before": {"annotation_count": before_count},
        "after": annotation,
    }


def update_annotation(args: dict[str, Any], *, annotations_dir: Path | None = None) -> dict[str, Any]:
    note_id = normalize_text(args.get("note_id") or args.get("id"))
    annotation_id = normalize_text(args.get("annotation_id") or args.get("annotationId"))
    if not note_id:
        return tool_error("note_id_required", "note_id is required")
    if not annotation_id:
        return tool_error("annotation_id_required", "annotation_id is required", note_id=note_id)

    annotations = _read_annotation_list(note_id, annotations_dir=annotations_dir)
    annotation = next(
        (entry for entry in annotations if isinstance(entry, dict) and normalize_text(entry.get("id")) == annotation_id),
        None,
    )
    if annotation is None:
        return tool_error("annotation_not_found", f"Annotation not found: {annotation_id}", note_id=note_id)

    before = dict(annotation)
    update = _annotation_update_from_args(args, existing=annotation)
    if "error" in update:
        return {**update, "note_id": note_id}
    annotation.update(update)
    annotation.pop("text", None)
    _write_annotation_list(note_id, annotations, annotations_dir=annotations_dir)
    return {
        "success": True,
        "changed": before != annotation,
        "note_id": note_id,
        "annotation_id": annotation_id,
        "message": "Updated annotation.",
        "before": before,
        "after": dict(annotation),
    }


def delete_annotation(args: dict[str, Any], *, annotations_dir: Path | None = None) -> dict[str, Any]:
    note_id = normalize_text(args.get("note_id") or args.get("id"))
    annotation_id = normalize_text(args.get("annotation_id") or args.get("annotationId"))
    if not note_id:
        return tool_error("note_id_required", "note_id is required")
    if not annotation_id:
        return tool_error("annotation_id_required", "annotation_id is required", note_id=note_id)

    annotations = _read_annotation_list(note_id, annotations_dir=annotations_dir)
    index = next(
        (idx for idx, entry in enumerate(annotations) if isinstance(entry, dict) and normalize_text(entry.get("id")) == annotation_id),
        -1,
    )
    if index < 0:
        return tool_error("annotation_not_found", f"Annotation not found: {annotation_id}", note_id=note_id)
    removed = annotations.pop(index)
    _write_annotation_list(note_id, annotations, annotations_dir=annotations_dir)
    return {
        "success": True,
        "changed": True,
        "note_id": note_id,
        "annotation_id": annotation_id,
        "message": "Deleted annotation.",
        "before": removed,
        "after": {"annotation_count": len(annotations)},
    }


def _read_annotation_list(note_id: str, *, annotations_dir: Path | None = None) -> list[dict[str, Any]]:
    payload = (
        read_note_annotations(note_id, annotations_dir)
        if annotations_dir is not None
        else read_note_annotations(note_id)
    )
    annotations = payload.get("annotations") if isinstance(payload, dict) else []
    if not isinstance(annotations, list):
        return []
    return [dict(annotation) for annotation in annotations if isinstance(annotation, dict)]


def _write_annotation_list(note_id: str, annotations: list[dict[str, Any]], *, annotations_dir: Path | None = None) -> None:
    cleaned = []
    for annotation in annotations:
        next_annotation = dict(annotation)
        next_annotation.pop("text", None)
        cleaned.append(next_annotation)
    if annotations_dir is not None:
        write_annotations(note_id, cleaned, annotations_dir)
    else:
        write_annotations(note_id, cleaned)


def _annotation_from_args(
    args: dict[str, Any],
    *,
    existing_annotations: list[dict[str, Any]],
    require_geometry: bool,
) -> dict[str, Any]:
    annotation_type = normalize_text(args.get("annotation_type") or args.get("type") or "highlight").lower()
    if annotation_type not in ANNOTATION_TYPES:
        return tool_error("invalid_annotation_type", f"annotation_type must be one of: {', '.join(sorted(ANNOTATION_TYPES))}")
    if args.get("page") is None:
        return tool_error("page_required", "page is required for annotation changes.")
    page = positive_int(args.get("page"), default=1, maximum=100_000)
    rects_payload = _annotation_rects_from_args(args, require_geometry=require_geometry)
    if "error" in rects_payload:
        return rects_payload
    rects = rects_payload["rects"]
    bounds = _annotation_bounds(rects) if rects else {"x": 0, "y": 0, "w": 0, "h": 0}
    color = normalize_text(args.get("color") or "yellow").lower()
    if color not in ANNOTATION_COLORS:
        return tool_error("invalid_color", f"color must be one of: {', '.join(sorted(ANNOTATION_COLORS))}")
    annotation_id = normalize_text(args.get("annotation_id") or args.get("annotationId"))
    if not annotation_id:
        annotation_id = _next_annotation_id(annotation_type, existing_annotations)
    return {
        "id": annotation_id,
        "type": annotation_type,
        "page": page,
        "x": bounds["x"],
        "y": bounds["y"],
        "w": bounds["w"],
        "h": bounds["h"],
        "rects": rects,
        "color": color,
        "comment": normalize_text(args.get("comment")),
        "quote": normalize_text(args.get("quote")),
        "createdAt": normalize_text(args.get("createdAt") or args.get("created_at")) or _iso_timestamp(),
    }


def _has_annotation_geometry(args: dict[str, Any]) -> bool:
    return isinstance(args.get("rects"), list) or all(key in args for key in ("x", "y", "w", "h"))


def _locate_annotation_target(
    args: dict[str, Any],
    *,
    library_path: Path | None = None,
    papers_dir: Path | None = None,
) -> dict[str, Any]:
    note_result = resolve_note(args, library_path=library_path)
    if "error" in note_result:
        return note_result
    note = note_result["note"]
    note_id = normalize_text(note.get("id"))
    target_text = normalize_text(args.get("query") or args.get("quote"))
    if not target_text:
        return tool_error("annotation_target_required", "Provide quote/query or normalized coordinates for create_annotation.", note_id=note_id)
    pdf_path = _resolved_pdf_path_for_note(note, papers_dir=papers_dir)
    if "error" in pdf_path:
        return pdf_path
    page_hint = args.get("page")
    page_number = positive_int(page_hint, default=0, maximum=100_000) if page_hint is not None else 0
    return _search_pdf_text_rects(
        note_id=note_id,
        pdf_path=pdf_path["pdf_path"],
        target_text=target_text,
        page_number=page_number,
    )


def _search_pdf_text_rects(*, note_id: str, pdf_path: Path, target_text: str, page_number: int = 0) -> dict[str, Any]:
    pymupdf = _import_pymupdf()
    if isinstance(pymupdf, dict):
        return {**pymupdf, "note_id": note_id}
    try:
        document = pymupdf.open(str(pdf_path))
        try:
            page_count = int(document.page_count)
            if page_number and (page_number < 1 or page_number > page_count):
                return tool_error("page_out_of_range", f"page must be between 1 and {page_count}.", note_id=note_id, page_count=page_count)
            page_indices = [page_number - 1] if page_number else range(page_count)
            target_candidates = _annotation_target_candidates(target_text)
            for page_index in page_indices:
                page = document.load_page(page_index)
                located = _search_page_text_rects(page, target_candidates)
                if located:
                    return {
                        "success": True,
                        "note_id": note_id,
                        "page": page_index + 1,
                        "rects": located["rects"],
                        "quote": located["quote"],
                        "match_count": len(located["rects"]),
                        "source_pdf": relative_project_path(pdf_path),
                    }
        finally:
            document.close()
    except Exception as error:
        return tool_error("annotation_locate_failed", f"Could not locate annotation text: {type(error).__name__}: {error}", note_id=note_id)
    scope = f" on page {page_number}" if page_number else ""
    return tool_error("annotation_target_not_found", f"Could not find quote/query in PDF{scope}: {target_text}", note_id=note_id)


def _annotation_target_candidates(target_text: str) -> list[str]:
    candidates = [
        target_text,
        re.sub(r"\s+", " ", target_text).strip(),
    ]
    seen: set[str] = set()
    unique = []
    for candidate in candidates:
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        unique.append(candidate)
    return unique


def _search_page_text_rects(page: Any, target_candidates: list[str]) -> dict[str, Any] | None:
    page_rect = page.rect
    width = float(page_rect.width) or 1.0
    height = float(page_rect.height) or 1.0
    for candidate in target_candidates:
        rects = page.search_for(candidate)
        normalized_rects = [_rect_to_unit(rect, width=width, height=height) for rect in rects]
        normalized_rects = [rect for rect in normalized_rects if rect is not None]
        if normalized_rects:
            return {"rects": normalized_rects, "quote": candidate}
    return _search_page_words_flexible(page, target_candidates, width=width, height=height)


def _annotation_match_text(value: str) -> str:
    return re.sub(r"\s+", "", normalize_text(value)).casefold()


def _search_page_words_flexible(page: Any, target_candidates: list[str], *, width: float, height: float) -> dict[str, Any] | None:
    words = page.get_text("words") or []
    entries = []
    for raw_word in words:
        if not isinstance(raw_word, (list, tuple)) or len(raw_word) < 5:
            continue
        text = normalize_text(raw_word[4])
        if not text:
            continue
        block = int(raw_word[5]) if len(raw_word) > 5 else 0
        line = int(raw_word[6]) if len(raw_word) > 6 else 0
        word_index = int(raw_word[7]) if len(raw_word) > 7 else len(entries)
        entries.append({
            "rect": raw_word,
            "text": text,
            "block": block,
            "line": line,
            "word": word_index,
            "order": len(entries),
        })
    entries.sort(key=lambda item: (item["block"], item["line"], item["word"], item["order"]))

    stream = []
    stream_word_indices: list[int] = []
    for index, entry in enumerate(entries):
        normalized = _annotation_match_text(entry["text"])
        if not normalized:
            continue
        stream.append(normalized)
        stream_word_indices.extend([index] * len(normalized))
    haystack = "".join(stream)
    if not haystack:
        return None

    for candidate in target_candidates:
        needle = _annotation_match_text(candidate)
        if not needle:
            continue
        start = haystack.find(needle)
        if start < 0:
            continue
        end = start + len(needle) - 1
        matched_indices = stream_word_indices[start:end + 1]
        if not matched_indices:
            continue
        selected = entries[min(matched_indices):max(matched_indices) + 1]
        rects = _word_entries_to_unit_rects(selected, width=width, height=height)
        if rects:
            return {
                "rects": rects,
                "quote": " ".join(entry["text"] for entry in selected),
            }
    return None


def _word_entries_to_unit_rects(entries: list[dict[str, Any]], *, width: float, height: float) -> list[dict[str, float]]:
    by_line: dict[tuple[int, int], list[Any]] = {}
    for entry in entries:
        by_line.setdefault((entry["block"], entry["line"]), []).append(entry["rect"])
    rects = []
    for line_rects in by_line.values():
        x0 = min(float(rect[0]) for rect in line_rects)
        y0 = min(float(rect[1]) for rect in line_rects)
        x1 = max(float(rect[2]) for rect in line_rects)
        y1 = max(float(rect[3]) for rect in line_rects)
        rect = _rect_tuple_to_unit((x0, y0, x1, y1), width=width, height=height)
        if rect is not None:
            rects.append(rect)
    rects.sort(key=lambda rect: (rect["y"], rect["x"]))
    return rects


def _rect_to_unit(rect: Any, *, width: float, height: float) -> dict[str, float] | None:
    return _rect_tuple_to_unit((rect.x0, rect.y0, rect.x1, rect.y1), width=width, height=height)


def _rect_tuple_to_unit(rect: tuple[float, float, float, float], *, width: float, height: float) -> dict[str, float] | None:
    x = max(0.0, min(1.0, float(rect[0]) / width))
    y = max(0.0, min(1.0, float(rect[1]) / height))
    right = max(0.0, min(1.0, float(rect[2]) / width))
    bottom = max(0.0, min(1.0, float(rect[3]) / height))
    w = right - x
    h = bottom - y
    if w <= 0 or h <= 0:
        return None
    return {"x": x, "y": y, "w": w, "h": h}


def _annotation_update_from_args(args: dict[str, Any], *, existing: dict[str, Any]) -> dict[str, Any]:
    update: dict[str, Any] = {}
    if "annotation_type" in args or "type" in args:
        annotation_type = normalize_text(args.get("annotation_type") or args.get("type")).lower()
        if annotation_type not in ANNOTATION_TYPES:
            return tool_error("invalid_annotation_type", f"annotation_type must be one of: {', '.join(sorted(ANNOTATION_TYPES))}")
        update["type"] = annotation_type
    if "page" in args:
        page = positive_int(args.get("page"), default=0, maximum=100_000)
        if page < 1:
            return tool_error("invalid_page", "page must be a positive integer.")
        update["page"] = page
    if "comment" in args:
        update["comment"] = normalize_text(args.get("comment"))
    if "quote" in args:
        update["quote"] = normalize_text(args.get("quote"))
    if "color" in args:
        color = normalize_text(args.get("color")).lower()
        if color not in ANNOTATION_COLORS:
            return tool_error("invalid_color", f"color must be one of: {', '.join(sorted(ANNOTATION_COLORS))}")
        update["color"] = color
    if any(key in args for key in ("x", "y", "w", "h", "rects")):
        rects_payload = _annotation_rects_from_args(args, require_geometry=True)
        if "error" in rects_payload:
            return rects_payload
        rects = rects_payload["rects"]
        bounds = _annotation_bounds(rects)
        update.update({"x": bounds["x"], "y": bounds["y"], "w": bounds["w"], "h": bounds["h"], "rects": rects})
    if not update:
        return tool_error("no_annotation_updates", "Provide at least one annotation field to update.")
    if "createdAt" not in existing:
        update["createdAt"] = _iso_timestamp()
    return update


def _annotation_rects_from_args(args: dict[str, Any], *, require_geometry: bool) -> dict[str, Any]:
    raw_rects = args.get("rects")
    rects: list[dict[str, float]] = []
    if isinstance(raw_rects, list):
        for raw_rect in raw_rects:
            rect = _normalize_annotation_rect(raw_rect if isinstance(raw_rect, dict) else {})
            if rect is None:
                return tool_error("invalid_rects", "rects must contain normalized x, y, w, h values between 0 and 1.")
            rects.append(rect)
    elif any(key in args for key in ("x", "y", "w", "h")):
        rect = _normalize_annotation_rect(args)
        if rect is None:
            return tool_error("invalid_geometry", "x, y, w, and h must be normalized values between 0 and 1.")
        rects.append(rect)
    if require_geometry and not rects:
        return tool_error("geometry_required", "Provide rects or normalized x, y, w, h for create_annotation.")
    return {"rects": rects}


def _finite_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed != parsed or parsed in {float("inf"), float("-inf")}:
        return None
    return parsed


def _normalized_unit_float(value: Any) -> float | None:
    parsed = _finite_float(value)
    if parsed is None or parsed < 0 or parsed > 1:
        return None
    return parsed


def _normalize_annotation_rect(raw: dict[str, Any]) -> dict[str, float] | None:
    x = _normalized_unit_float(raw.get("x"))
    y = _normalized_unit_float(raw.get("y"))
    w = _normalized_unit_float(raw.get("w"))
    h = _normalized_unit_float(raw.get("h"))
    if x is None or y is None or w is None or h is None:
        return None
    if w <= 0 or h <= 0 or x + w > 1.000001 or y + h > 1.000001:
        return None
    return {"x": x, "y": y, "w": w, "h": h}


def _annotation_bounds(rects: list[dict[str, float]]) -> dict[str, float]:
    left = min(rect["x"] for rect in rects)
    top = min(rect["y"] for rect in rects)
    right = max(rect["x"] + rect["w"] for rect in rects)
    bottom = max(rect["y"] + rect["h"] for rect in rects)
    return {"x": left, "y": top, "w": right - left, "h": bottom - top}


def _next_annotation_id(annotation_type: str, existing_annotations: list[dict[str, Any]]) -> str:
    existing = {normalize_text(annotation.get("id")) for annotation in existing_annotations if isinstance(annotation, dict)}
    while True:
        candidate = f"{annotation_type}-{int(time.time() * 1000):x}"
        if candidate not in existing:
            return candidate
        time.sleep(0.001)


def _iso_timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

__all__ = [name for name in globals() if not name.startswith("__")]
