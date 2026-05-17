from __future__ import annotations

from typing import Any

from app_infra.formatting import normalize_text


def read_paper_progress_detail(args: dict[str, Any], *, suffix: str = "...") -> str:
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
        query = _short_text(args.get("query"), max_chars=72)
        return f"Searching paper text{f': {query}' if query else ''}{suffix}"
    if action == "read_pages":
        page_label = _page_range_label(args.get("page_start"), args.get("page_end"))
        return f"Reading paper {page_label}{suffix}"
    if action == "render_page":
        page = _positive_page(args.get("page"))
        return f"Rendering paper page {page}{suffix}" if page else f"Rendering paper page{suffix}"
    if action == "extract_images":
        page_label = _page_range_label(args.get("page_start"), args.get("page_end"), fallback="")
        return f"Extracting paper images{f' from {page_label}' if page_label else ''}{suffix}"
    if action == "analyze_image":
        return f"Analyzing paper image{suffix}"
    return f"Reading paper source ({action}){suffix}"


def _page_range_label(start_value: Any, end_value: Any, *, fallback: str = "pages") -> str:
    start = _positive_page(start_value)
    end = _positive_page(end_value)
    if start and end:
        if start == end:
            return f"page {start}"
        return f"pages {min(start, end)}-{max(start, end)}"
    if start:
        return f"page {start}"
    if end:
        return f"page {end}"
    return fallback


def _positive_page(value: Any) -> int | None:
    try:
        page = int(value)
    except (TypeError, ValueError):
        return None
    return page if page > 0 else None


def _short_text(value: Any, *, max_chars: int) -> str:
    text = normalize_text(value).replace("\n", " ")
    return f"{text[:max_chars - 1]}..." if len(text) > max_chars else text
