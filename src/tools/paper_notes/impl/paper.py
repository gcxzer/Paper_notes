"""说明：实现论文 PDF 内容和图片工具动作。

作用：支持读取页面、渲染页面、提取图片和查询索引状态。
"""

from __future__ import annotations

# PDF-backed page rendering, image extraction, and cache helpers.

import re
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from app_infra.formatting import normalize_text
from app_infra.files import PAPERS_DIR, PROJECT_ROOT, is_relative_to
from tools.paper_notes.impl.artifacts import _attach_artifact
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
    "_paper_visual_images_dir",
    "_resolved_pdf_path_for_note",
    "extract_paper_images",
    "render_paper_page",
]

PAPER_VISUALS_DIR = PROJECT_ROOT / "resources" / "Paper-visuals"


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

    page_number = positive_int(args.get("page"), default=1, maximum=100_000)
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

    limit = positive_int(args.get("limit"), default=20, maximum=50)
    result = _extract_pdf_images(
        note_id=normalize_text(note.get("id")),
        pdf_path=pdf_path["pdf_path"],
        page_start=args.get("page_start"),
        page_end=args.get("page_end"),
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
    return result


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
