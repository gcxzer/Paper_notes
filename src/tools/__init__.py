from __future__ import annotations

from pathlib import Path
from typing import Any

from langchain_core.tools import BaseTool

from tools.paper_notes import create_tools as create_paper_notes_tools


def create_tools(
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
) -> list[BaseTool]:
    return create_paper_notes_tools(
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


__all__ = [
    "create_tools",
]
