from __future__ import annotations

# PDF-backed paper text, page rendering, image extraction, and cache helpers.

import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from tools.paper_notes.impl.formatting import normalize_text
from tools.paper_notes.impl.paths import PAPERS_DIR, PROJECT_ROOT, is_relative_to
from tools.paper_notes.impl.storage import atomic_write_text
from tools.paper_notes.impl.artifacts import _attach_artifact
from tools.paper_notes.impl.common import (
    positive_float,
    positive_int,
    relative_project_path,
    resolve_note,
    tool_error,
)

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
        return tool_error("query_required", "query is required", note_id=note["id"])
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
    paper_page_cache_dir: Path | None = None,
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
        paper_page_cache_dir=paper_page_cache_dir,
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
    paper_image_cache_dir: Path | None = None,
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
        paper_image_cache_dir=paper_image_cache_dir,
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
    base_dir = paper_text_cache_dir or (PROJECT_ROOT / "resources" / "Paper-text")
    return (base_dir / f"{_safe_cache_name(note_id)}.json").resolve()


def _paper_page_cache_path(
    note_id: str,
    *,
    page_number: int,
    scale: float,
    paper_page_cache_dir: Path | None = None,
) -> Path:
    base_dir = paper_page_cache_dir or (PROJECT_ROOT / "resources" / "Paper-pages")
    scale_tag = str(scale).rstrip("0").rstrip(".").replace(".", "_")
    return (
        base_dir
        / _safe_cache_name(note_id)
        / f"page-{page_number:04d}-scale-{scale_tag or '1'}.png"
    ).resolve()


def _paper_image_cache_dir(note_id: str, *, paper_image_cache_dir: Path | None = None) -> Path:
    base_dir = paper_image_cache_dir or (PROJECT_ROOT / "resources" / "Paper-images")
    return (base_dir / _safe_cache_name(note_id)).resolve()


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
        if not text:
            continue
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
    paper_page_cache_dir: Path | None = None,
) -> dict[str, Any]:
    pymupdf = _import_pymupdf()
    if isinstance(pymupdf, dict):
        return {**pymupdf, "note_id": note_id}

    output_path = _paper_page_cache_path(
        note_id,
        page_number=page_number,
        scale=scale,
        paper_page_cache_dir=paper_page_cache_dir,
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
    paper_image_cache_dir: Path | None = None,
) -> dict[str, Any]:
    pymupdf = _import_pymupdf()
    if isinstance(pymupdf, dict):
        return {**pymupdf, "note_id": note_id}

    output_dir = _paper_image_cache_dir(note_id, paper_image_cache_dir=paper_image_cache_dir)
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


__all__ = [name for name in globals() if not name.startswith("__")]
