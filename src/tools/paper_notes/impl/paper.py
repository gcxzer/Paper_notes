"""说明：实现论文 PDF 内容和图片工具动作。

作用：支持读取页面、渲染页面、提取图片和查询索引状态。
"""

from __future__ import annotations

# PDF-backed page rendering, image extraction, and cache helpers.

import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from app_infra.formatting import normalize_text
from app_infra.files import PAPERS_DIR, PROJECT_ROOT, atomic_write_text, is_relative_to
from tools.paper_notes.impl.artifacts import _artifact_payload, _attach_artifact
from tools.paper_notes.impl.common import (
    positive_float,
    positive_int,
    relative_project_path,
    resolve_note,
    tool_error,
)

__all__ = [
    "PAPER_VISUALS_DIR",
    "_import_pymupdf",
    "_paper_page_cache_path",
    "_paper_text_cache_path",
    "_paper_visual_images_dir",
    "_resolved_pdf_path_for_note",
    "analyze_paper_image",
    "extract_paper_images",
    "read_paper_text",
    "render_paper_page",
    "search_paper_text",
]

PAPER_TEXT_DIR = PROJECT_ROOT / "resources" / "Paper-text"
PAPER_VISUALS_DIR = PROJECT_ROOT / "resources" / "Paper-visuals"


def search_paper_text(
    args: dict[str, Any],
    *,
    library_path: Path | None = None,
    papers_dir: Path | None = None,
    paper_text_cache_dir: Path | None = None,
) -> dict[str, Any]:
    note_result = resolve_note(args, library_path=library_path)
    if "error" in note_result:
        return note_result
    note = note_result["note"]
    query = normalize_text(args.get("query"))
    if not query:
        return tool_error("query_required", "query is required.", note_id=note["id"])
    pages_payload = _load_or_extract_paper_text(
        note,
        papers_dir=papers_dir,
        paper_text_cache_dir=paper_text_cache_dir,
    )
    if not pages_payload.get("success"):
        return pages_payload
    limit = positive_int(args.get("limit"), default=5, maximum=10)
    matches = _search_paper_pages(pages_payload.get("pages", []), query=query, limit=limit)
    return {
        "success": True,
        "note_id": note["id"],
        "query": query,
        "count": len(matches),
        "matches": matches,
        "source": pages_payload.get("source", ""),
    }


def read_paper_text(
    args: dict[str, Any],
    *,
    library_path: Path | None = None,
    papers_dir: Path | None = None,
    paper_text_cache_dir: Path | None = None,
) -> dict[str, Any]:
    note_result = resolve_note(args, library_path=library_path)
    if "error" in note_result:
        return note_result
    note = note_result["note"]
    pages_payload = _load_or_extract_paper_text(
        note,
        papers_dir=papers_dir,
        paper_text_cache_dir=paper_text_cache_dir,
    )
    if not pages_payload.get("success"):
        return pages_payload
    pages = [
        page for page in pages_payload.get("pages", [])
        if isinstance(page, dict) and normalize_text(page.get("text"))
    ]
    page_start = positive_int(args.get("page_start"), default=1, maximum=max(len(pages), 1))
    page_end = positive_int(args.get("page_end"), default=len(pages) or 1, maximum=max(len(pages), 1))
    if page_end < page_start:
        page_start, page_end = page_end, page_start
    selected = [
        page for page in pages
        if page_start <= int(page.get("page") or 0) <= page_end
    ]
    max_chars = positive_int(args.get("max_chars"), default=12_000, maximum=20_000)
    text = _join_page_text(selected)
    truncated = len(text) > max_chars
    if truncated:
        text = text[:max_chars].rstrip()
    return {
        "success": True,
        "note_id": note["id"],
        "page_start": page_start,
        "page_end": page_end,
        "page_count": len(selected),
        "text": text,
        "chars": len(text),
        "truncated": truncated,
        "source": pages_payload.get("source", ""),
    }


def render_paper_page(
    args: dict[str, Any],
    *,
    library_path: Path | None = None,
    papers_dir: Path | None = None,
    paper_visual_cache_dir: Path | None = None,
    media_store: Any | None = None,
) -> dict[str, Any]:
    note_result = resolve_note(args, library_path=library_path)
    if "error" in note_result:
        return note_result
    note = note_result["note"]
    pdf_path = _resolved_pdf_path_for_note(note, papers_dir=papers_dir)
    if "error" in pdf_path:
        return pdf_path

    requested_page = positive_int(args.get("page"), default=1, maximum=100_000) if args.get("page") is not None else None
    figure_page = _resolved_figure_page_hint(note, args, papers_dir=papers_dir)
    page_number = int(figure_page["page"]) if figure_page else (requested_page or 1)
    scale = positive_float(args.get("scale"), default=2.0, minimum=0.5, maximum=4.0)
    result = _render_pdf_page(
        note_id=normalize_text(note.get("id")),
        pdf_path=pdf_path["pdf_path"],
        page_number=page_number,
        scale=scale,
        paper_visual_cache_dir=paper_visual_cache_dir,
    )
    _attach_artifact(
        result,
        media_store=media_store,
        path_key="image_path",
        source="pdf_page",
        metadata={
            "note_id": normalize_text(note.get("id")),
            "page": page_number,
            "scale": scale,
        },
    )
    _attach_figure_page_resolution(result, figure_page, requested_page=requested_page)
    return result


def extract_paper_images(
    args: dict[str, Any],
    *,
    library_path: Path | None = None,
    papers_dir: Path | None = None,
    paper_visual_cache_dir: Path | None = None,
    media_store: Any | None = None,
) -> dict[str, Any]:
    note_result = resolve_note(args, library_path=library_path)
    if "error" in note_result:
        return note_result
    note = note_result["note"]
    pdf_path = _resolved_pdf_path_for_note(note, papers_dir=papers_dir)
    if "error" in pdf_path:
        return pdf_path

    figure_page = _resolved_figure_page_hint(note, args, papers_dir=papers_dir)
    page_start = args.get("page_start")
    page_end = args.get("page_end")
    requested_page = _single_requested_visual_page(args)
    if figure_page:
        page_start = page_end = int(figure_page["page"])
    limit = positive_int(args.get("limit"), default=20, maximum=50)
    result = _extract_pdf_images(
        note_id=normalize_text(note.get("id")),
        pdf_path=pdf_path["pdf_path"],
        page_start=page_start,
        page_end=page_end,
        limit=limit,
        paper_visual_cache_dir=paper_visual_cache_dir,
    )
    for image in result.get("images", []) if isinstance(result.get("images"), list) else []:
        if isinstance(image, dict):
            _attach_artifact(
                image,
                media_store=media_store,
                path_key="image_path",
                source="pdf_image",
                metadata={
                    "note_id": normalize_text(note.get("id")),
                    "page": image.get("page"),
                    "xref": image.get("xref"),
                },
            )
    _attach_figure_page_resolution(result, figure_page, requested_page=requested_page)
    if figure_page and result.get("success") and int(result.get("count") or 0) == 0:
        result["hint"] = (
            "No embedded raster images were found on the resolved figure page. Use action=render_page or "
            "action=analyze_image with this resolved page for vector diagrams or whole-page visual inspection."
        )
    return result


def analyze_paper_image(
    args: dict[str, Any],
    *,
    library_path: Path | None = None,
    papers_dir: Path | None = None,
    paper_visual_cache_dir: Path | None = None,
    media_store: Any | None = None,
    paper_image_analyzer: Any | None = None,
) -> dict[str, Any]:
    if not callable(paper_image_analyzer):
        return tool_error(
            "image_analysis_unavailable",
            "Image analysis is not available for the current model/provider.",
            note_id=normalize_text(args.get("note_id")),
        )

    note_result = resolve_note(args, library_path=library_path)
    if "error" in note_result:
        return note_result
    note = note_result["note"]
    note_id = normalize_text(note.get("id"))

    source = _resolve_image_analysis_source(
        args,
        note_id=note_id,
        library_path=library_path,
        papers_dir=papers_dir,
        paper_visual_cache_dir=paper_visual_cache_dir,
        media_store=media_store,
        note=note,
    )
    if not source.get("success"):
        return source

    question = normalize_text(args.get("query") or args.get("question")) or "Analyze this paper image."
    analysis = paper_image_analyzer({
        "artifact_id": source.get("artifact_id"),
        "path": args.get("path"),
        "question": question,
    })
    if not isinstance(analysis, dict):
        return tool_error("image_analysis_failed", "Image analysis returned an invalid result.", note_id=note_id)
    if not analysis.get("success"):
        return {**analysis, "note_id": analysis.get("note_id") or note_id}
    return {
        "success": True,
        "note_id": note_id,
        "source": source.get("source"),
        "page": source.get("page"),
        "scale": source.get("scale"),
        "artifact_id": source.get("artifact_id"),
        "artifact": source.get("artifact") or analysis.get("artifact") or {},
        "rendered": source.get("rendered") or {},
        "resolved_figure": source.get("resolved_figure") or {},
        "page_correction": source.get("page_correction") or {},
        "question": question,
        "analysis": normalize_text(analysis.get("analysis") or analysis.get("content")),
    }


def _resolve_image_analysis_source(
    args: dict[str, Any],
    *,
    note_id: str,
    library_path: Path | None,
    papers_dir: Path | None,
    paper_visual_cache_dir: Path | None,
    media_store: Any | None,
    note: dict[str, Any],
) -> dict[str, Any]:
    artifact_id = normalize_text(args.get("artifact_id") or args.get("artifactId"))
    if artifact_id:
        return {
            "success": True,
            "source": "artifact",
            "artifact_id": artifact_id,
            "artifact": _artifact_payload(media_store, artifact_id),
        }

    if args.get("path"):
        find_by_path = getattr(media_store, "find_by_path", None)
        if callable(find_by_path):
            try:
                artifact = find_by_path(str(args.get("path") or ""))
            except Exception:
                artifact = None
            artifact_payload = artifact.to_dict() if hasattr(artifact, "to_dict") else {}
            artifact_id = normalize_text(artifact_payload.get("id"))
            if artifact_id:
                return {
                    "success": True,
                    "source": "artifact",
                    "artifact_id": artifact_id,
                    "artifact": artifact_payload,
                }
        return tool_error("image_artifact_not_found", "Could not resolve image artifact from path.", note_id=note_id)

    figure_page = _resolved_figure_page_hint(note, args, papers_dir=papers_dir)
    if args.get("page") is None and not figure_page:
        return tool_error(
            "image_source_required",
            "Provide artifact_id, path, page, or a resolvable figure_label/query for image analysis.",
            note_id=note_id,
        )

    requested_page = positive_int(args.get("page"), default=1, maximum=100_000) if args.get("page") is not None else None
    page = int(figure_page["page"]) if figure_page else (requested_page or 1)
    scale = positive_float(args.get("scale"), default=2.0, minimum=0.5, maximum=4.0)
    rendered = render_paper_page(
        {"note_id": note_id, "page": page, "scale": scale},
        library_path=library_path,
        papers_dir=papers_dir,
        paper_visual_cache_dir=paper_visual_cache_dir,
        media_store=media_store,
    )
    if not rendered.get("success"):
        return rendered
    artifact_id = normalize_text(rendered.get("artifact_id"))
    if not artifact_id:
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
        "artifact_id": artifact_id,
        "artifact": rendered.get("artifact") or _artifact_payload(media_store, artifact_id),
        "resolved_figure": _figure_page_resolution_payload(figure_page),
        "page_correction": _figure_page_correction_payload(figure_page, requested_page=requested_page),
        "rendered": {
            "width": rendered.get("width"),
            "height": rendered.get("height"),
            "relative_path": rendered.get("relative_path") or "",
            "preview_url": rendered.get("preview_url") or "",
            "download_url": rendered.get("download_url") or "",
        },
    }


def _resolved_figure_page_hint(
    note: dict[str, Any],
    args: dict[str, Any],
    *,
    papers_dir: Path | None,
) -> dict[str, Any] | None:
    label = _figure_label_from_args(args)
    if not label:
        return None
    pages_payload = _load_or_extract_paper_text(note, papers_dir=papers_dir)
    if not pages_payload.get("success"):
        return None
    matches = _search_paper_pages(pages_payload.get("pages", []), query=label, limit=3)
    if not matches:
        return None
    page = positive_int(matches[0].get("page"), default=0, maximum=100_000)
    if page < 1:
        return None
    return {
        "label": label,
        "page": page,
        "source": pages_payload.get("source", ""),
    }


def _figure_label_from_args(args: dict[str, Any]) -> str:
    for key in ("figure_label", "figure", "label", "query", "question"):
        label = _figure_label_from_text(normalize_text(args.get(key)))
        if label:
            return label
    return ""


def _figure_label_from_text(text: str) -> str:
    if not text:
        return ""
    match = re.search(r"\b(?:fig(?:ure)?\.?)\s*([0-9]+(?:\.[0-9]+)?[A-Za-z]?)\b", text, flags=re.IGNORECASE)
    if match:
        return f"Figure {match.group(1)}"
    match = re.search(r"[图圖]\s*([0-9]+|[零〇一二两三四五六七八九十百]+)([A-Za-z]?)", text)
    if not match:
        return ""
    number = match.group(1)
    if number.isdigit():
        figure_number = number
    else:
        parsed = _chinese_int(number)
        if parsed <= 0:
            return ""
        figure_number = str(parsed)
    return f"Figure {figure_number}{match.group(2)}"


def _chinese_int(text: str) -> int:
    digits = {
        "零": 0,
        "〇": 0,
        "一": 1,
        "二": 2,
        "两": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
        "七": 7,
        "八": 8,
        "九": 9,
    }
    if not text:
        return 0
    if text in digits:
        return digits[text]
    if "百" in text:
        left, _, right = text.partition("百")
        hundreds = digits.get(left, 1 if not left else 0)
        return hundreds * 100 + _chinese_int(right)
    if "十" in text:
        left, _, right = text.partition("十")
        tens = digits.get(left, 1 if not left else 0)
        ones = _chinese_int(right) if right else 0
        return tens * 10 + ones
    total = 0
    for char in text:
        if char not in digits:
            return 0
        total = total * 10 + digits[char]
    return total


def _single_requested_visual_page(args: dict[str, Any]) -> int | None:
    if args.get("page") is not None:
        return positive_int(args.get("page"), default=1, maximum=100_000)
    if args.get("page_start") is None or args.get("page_end") is None:
        return None
    start = positive_int(args.get("page_start"), default=0, maximum=100_000)
    end = positive_int(args.get("page_end"), default=0, maximum=100_000)
    return start if start > 0 and start == end else None


def _attach_figure_page_resolution(
    result: dict[str, Any],
    figure_page: dict[str, Any] | None,
    *,
    requested_page: int | None,
) -> None:
    if not isinstance(result, dict) or not figure_page:
        return
    result["resolved_figure"] = _figure_page_resolution_payload(figure_page)
    correction = _figure_page_correction_payload(figure_page, requested_page=requested_page)
    if correction:
        result["page_correction"] = correction


def _figure_page_resolution_payload(figure_page: dict[str, Any] | None) -> dict[str, Any]:
    if not figure_page:
        return {}
    return {
        "label": figure_page.get("label") or "",
        "page": figure_page.get("page"),
        "source": figure_page.get("source") or "",
    }


def _figure_page_correction_payload(
    figure_page: dict[str, Any] | None,
    *,
    requested_page: int | None,
) -> dict[str, Any]:
    if not figure_page or requested_page is None or requested_page == int(figure_page.get("page") or 0):
        return {}
    return {
        "label": figure_page.get("label") or "",
        "requested_page": requested_page,
        "resolved_page": figure_page.get("page"),
        "reason": "Numbered paper figures are not PDF page numbers.",
    }


def _safe_cache_name(value: str) -> str:
    candidate = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._-")
    return candidate or "note"


def _page_range_from_args(page_start: Any, page_end: Any, *, page_count: int) -> tuple[int, int]:
    max_page = max(page_count, 1)
    start = positive_int(page_start, default=1, maximum=max_page)
    end = positive_int(page_end, default=max_page, maximum=max_page)
    if end < start:
        start, end = end, start
    return start, end


def _safe_image_ext(value: str) -> str:
    normalized = normalize_text(value).lower().lstrip(".")
    if normalized in {"png", "jpg", "jpeg", "webp", "bmp", "tif", "tiff"}:
        return normalized
    return "png"


def _load_or_extract_paper_text(
    note: dict[str, Any],
    *,
    papers_dir: Path | None = None,
    paper_text_cache_dir: Path | None = None,
) -> dict[str, Any]:
    note_id = normalize_text(note.get("id"))
    if not note_id:
        return tool_error("note_id_required", "note_id is required")
    cache_path = _paper_text_cache_path(note_id, paper_text_cache_dir=paper_text_cache_dir)
    cached = _read_paper_text_cache(cache_path)
    if cached is not None:
        return {
            "success": True,
            "note_id": note_id,
            "pages": cached,
            "source": "cache",
        }

    pdf_path = _note_pdf_path(note, papers_dir=papers_dir)
    if pdf_path is None:
        return tool_error("paper_pdf_missing", "Note has no local PDF path.", note_id=note_id)
    if not pdf_path.exists():
        return tool_error("paper_pdf_not_found", f"PDF file was not found: {pdf_path.name}", note_id=note_id)
    extracted = _extract_pdf_text_pages(pdf_path)
    if "error" in extracted:
        return {**extracted, "note_id": note_id}
    pages = extracted["pages"]
    _write_paper_text_cache(cache_path, note_id=note_id, pdf_path=pdf_path, pages=pages)
    return {
        "success": True,
        "note_id": note_id,
        "pages": pages,
        "source": "pdf",
    }


def _paper_text_cache_path(note_id: str, *, paper_text_cache_dir: Path | None = None) -> Path:
    base_dir = paper_text_cache_dir or PAPER_TEXT_DIR
    return (base_dir / f"{_safe_cache_name(note_id)}.json").resolve()


def _read_paper_text_cache(cache_path: Path) -> list[dict[str, Any]] | None:
    try:
        raw = cache_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        text = normalize_text(raw)
        return [{"page": 1, "text": text}] if text else []
    if isinstance(payload, dict) and isinstance(payload.get("pages"), list):
        return _normalize_cached_pages(payload["pages"])
    if isinstance(payload, list):
        return _normalize_cached_pages(payload)
    return None


def _write_paper_text_cache(
    cache_path: Path,
    *,
    note_id: str,
    pdf_path: Path,
    pages: list[dict[str, Any]],
) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "noteId": note_id,
        "sourcePath": str(pdf_path),
        "pages": pages,
    }
    atomic_write_text(cache_path, json.dumps(payload, ensure_ascii=False, indent=2))


def _normalize_cached_pages(raw_pages: list[Any]) -> list[dict[str, Any]]:
    pages: list[dict[str, Any]] = []
    for index, raw_page in enumerate(raw_pages, start=1):
        if isinstance(raw_page, dict):
            page_number = positive_int(raw_page.get("page"), default=index, maximum=100_000)
            text = normalize_text(raw_page.get("text"))
        else:
            page_number = index
            text = normalize_text(raw_page)
        if text:
            pages.append({"page": page_number, "text": text})
    return pages


def _extract_pdf_text_pages(pdf_path: Path) -> dict[str, Any]:
    pymupdf = _import_pymupdf()
    if isinstance(pymupdf, dict):
        return pymupdf
    try:
        document = pymupdf.open(str(pdf_path))
        try:
            pages = [
                {"page": index + 1, "text": normalize_text(page.get_text("text") or "")}
                for index, page in enumerate(document)
            ]
        finally:
            document.close()
    except Exception as error:
        return tool_error("pdf_text_extract_failed", f"Could not extract PDF text: {type(error).__name__}: {error}")
    return {"success": True, "pages": [page for page in pages if page["text"]]}


def _paper_page_cache_path(
    note_id: str,
    *,
    page_number: int,
    scale: float,
    paper_visual_cache_dir: Path | None = None,
) -> Path:
    scale_tag = str(scale).rstrip("0").rstrip(".").replace(".", "_")
    return (
        _paper_visual_note_dir(note_id, paper_visual_cache_dir=paper_visual_cache_dir)
        / "pages"
        / f"page-{page_number:04d}-scale-{scale_tag or '1'}.png"
    ).resolve()


def _paper_visual_images_dir(note_id: str, *, paper_visual_cache_dir: Path | None = None) -> Path:
    return (_paper_visual_note_dir(note_id, paper_visual_cache_dir=paper_visual_cache_dir) / "images").resolve()


def _paper_visual_note_dir(note_id: str, *, paper_visual_cache_dir: Path | None = None) -> Path:
    base_dir = paper_visual_cache_dir or PAPER_VISUALS_DIR
    return (base_dir / _safe_cache_name(note_id)).resolve()


def _resolved_pdf_path_for_note(note: dict[str, Any], *, papers_dir: Path | None = None) -> dict[str, Any]:
    note_id = normalize_text(note.get("id"))
    if not note_id:
        return tool_error("note_id_required", "note_id is required")
    pdf_path = _note_pdf_path(note, papers_dir=papers_dir)
    if pdf_path is None:
        return tool_error("paper_pdf_missing", "Note has no local PDF path.", note_id=note_id)
    if not pdf_path.exists():
        return tool_error("paper_pdf_not_found", f"PDF file was not found: {pdf_path.name}", note_id=note_id)
    return {"success": True, "note_id": note_id, "pdf_path": pdf_path}


def _render_pdf_page(
    *,
    note_id: str,
    pdf_path: Path,
    page_number: int,
    scale: float,
    paper_visual_cache_dir: Path | None = None,
) -> dict[str, Any]:
    pymupdf = _import_pymupdf()
    if isinstance(pymupdf, dict):
        return {**pymupdf, "note_id": note_id}

    output_path = _paper_page_cache_path(
        note_id,
        page_number=page_number,
        scale=scale,
        paper_visual_cache_dir=paper_visual_cache_dir,
    )
    try:
        document = pymupdf.open(str(pdf_path))
        try:
            page_count = int(document.page_count)
            if page_number < 1 or page_number > page_count:
                return tool_error(
                    "page_out_of_range",
                    f"page must be between 1 and {page_count}.",
                    note_id=note_id,
                    page_count=page_count,
                )
            page = document.load_page(page_number - 1)
            matrix = pymupdf.Matrix(scale, scale)
            pixmap = page.get_pixmap(matrix=matrix, alpha=False)
            cached = output_path.exists()
            output_path.parent.mkdir(parents=True, exist_ok=True)
            pixmap.save(str(output_path))
            width = int(pixmap.width)
            height = int(pixmap.height)
        finally:
            document.close()
    except Exception as error:
        return tool_error(
            "pdf_page_render_failed",
            f"Could not render PDF page: {type(error).__name__}: {error}",
            note_id=note_id,
        )

    return {
        "success": True,
        "note_id": note_id,
        "page": page_number,
        "scale": scale,
        "image_path": str(output_path),
        "relative_path": relative_project_path(output_path),
        "width": width,
        "height": height,
        "source_pdf": relative_project_path(pdf_path),
        "cached": cached,
    }


def _extract_pdf_images(
    *,
    note_id: str,
    pdf_path: Path,
    page_start: Any,
    page_end: Any,
    limit: int,
    paper_visual_cache_dir: Path | None = None,
) -> dict[str, Any]:
    pymupdf = _import_pymupdf()
    if isinstance(pymupdf, dict):
        return {**pymupdf, "note_id": note_id}

    output_dir = _paper_visual_images_dir(note_id, paper_visual_cache_dir=paper_visual_cache_dir)
    images: list[dict[str, Any]] = []
    try:
        document = pymupdf.open(str(pdf_path))
        try:
            start, end = _page_range_from_args(page_start, page_end, page_count=int(document.page_count))
            output_dir.mkdir(parents=True, exist_ok=True)
            for page_index in range(start - 1, end):
                if len(images) >= limit:
                    break
                page = document.load_page(page_index)
                for image_index, image_info in enumerate(page.get_images(full=True), start=1):
                    if len(images) >= limit:
                        break
                    xref = int(image_info[0])
                    extracted = document.extract_image(xref)
                    image_bytes = extracted.get("image")
                    if not isinstance(image_bytes, bytes):
                        continue
                    ext = _safe_image_ext(normalize_text(extracted.get("ext")).lower())
                    output_path = output_dir / f"page-{page_index + 1:04d}-image-{image_index:03d}-xref-{xref}.{ext}"
                    cached = output_path.exists()
                    output_path.write_bytes(image_bytes)
                    images.append({
                        "page": page_index + 1,
                        "image_index": image_index,
                        "xref": xref,
                        "image_path": str(output_path),
                        "relative_path": relative_project_path(output_path),
                        "width": int(extracted.get("width") or 0),
                        "height": int(extracted.get("height") or 0),
                        "ext": ext,
                        "cached": cached,
                    })
        finally:
            document.close()
    except Exception as error:
        return tool_error(
            "pdf_image_extract_failed",
            f"Could not extract PDF images: {type(error).__name__}: {error}",
            note_id=note_id,
        )

    return {
        "success": True,
        "note_id": note_id,
        "page_start": start,
        "page_end": end,
        "count": len(images),
        "images": images,
        "source_pdf": relative_project_path(pdf_path),
        "limit": limit,
    }


def _import_pymupdf() -> Any:
    try:
        import pymupdf  # type: ignore[import-not-found]
    except Exception as error:
        return tool_error(
            "pdf_extractor_unavailable",
            f"PDF extraction requires pymupdf: {type(error).__name__}: {error}",
        )
    return pymupdf


def _note_pdf_path(note: dict[str, Any], *, papers_dir: Path | None = None) -> Path | None:
    href = normalize_text(note.get("href") or note.get("pdfHref") or note.get("pdfStorageKey"))
    if not href:
        return None
    base_dir = (papers_dir or PAPERS_DIR).resolve()
    raw_path = Path(unquote(href))
    if raw_path.is_absolute():
        pdf_path = raw_path.resolve()
    elif papers_dir is not None:
        parts = raw_path.parts
        if "Papers" in parts:
            rel_path = Path(*parts[parts.index("Papers") + 1:])
        else:
            rel_path = raw_path
        pdf_path = (base_dir / rel_path).resolve()
    else:
        pdf_path = (PROJECT_ROOT / raw_path).resolve()
    if not is_relative_to(pdf_path, base_dir):
        return None
    return pdf_path


def _search_paper_pages(pages: list[Any], *, query: str, limit: int) -> list[dict[str, Any]]:
    terms = [term.casefold() for term in re.findall(r"[\w\u4e00-\u9fff]+", query) if term.strip()]
    phrase = query.casefold()
    matches: list[tuple[int, int, dict[str, Any]]] = []
    for page in pages:
        if not isinstance(page, dict):
            continue
        text = normalize_text(page.get("text"))
        if not text:
            continue
        lowered = text.casefold()
        score = 0
        index = lowered.find(phrase)
        if index >= 0:
            score += 10
        else:
            index = min((lowered.find(term) for term in terms if term in lowered), default=-1)
        for term in terms:
            if term in lowered:
                score += 1
        if score <= 0:
            continue
        excerpt = _paper_excerpt(text, index=index if index >= 0 else 0)
        matches.append((score, int(page.get("page") or 0), {
            "page": int(page.get("page") or 0),
            "excerpt": excerpt,
            "score": score,
        }))
    matches.sort(key=lambda item: (-item[0], item[1]))
    return [entry for _, _, entry in matches[:limit]]


def _paper_excerpt(text: str, *, index: int, radius: int = 320) -> str:
    start = max(0, index - radius)
    end = min(len(text), index + radius)
    excerpt = text[start:end].strip()
    if start > 0:
        excerpt = f"...{excerpt}"
    if end < len(text):
        excerpt = f"{excerpt}..."
    return excerpt


def _join_page_text(pages: list[dict[str, Any]]) -> str:
    chunks = []
    for page in pages:
        chunks.append(f"[Page {page.get('page')}]\n{normalize_text(page.get('text'))}")
    return "\n\n".join(chunks).strip()
