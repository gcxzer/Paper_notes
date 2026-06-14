from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from langchain_core.tools import BaseTool


@dataclass(frozen=True, slots=True)
class ToolContext:
    library_path: Path | None = None
    annotations_dir: Path | None = None
    html_dir: Path | None = None
    papers_dir: Path | None = None
    paper_text_cache_dir: Path | None = None
    paper_page_cache_dir: Path | None = None
    paper_image_cache_dir: Path | None = None
    media_store: Any | None = None
    paper_image_analyzer: Any | None = None
    mcp_manager: Any | None = None


def create_tools(
    *,
    context: ToolContext | None = None,
    library_path: Path | None = None,
    annotations_dir: Path | None = None,
    html_dir: Path | None = None,
    papers_dir: Path | None = None,
    paper_text_cache_dir: Path | None = None,
    paper_page_cache_dir: Path | None = None,
    paper_image_cache_dir: Path | None = None,
    media_store: Any | None = None,
    paper_image_analyzer: Any | None = None,
    mcp_manager: Any | None = None,
) -> list[BaseTool]:
    from tools.paper_notes import create_tools as create_paper_notes_tools
    from tools.skills import create_tools as create_skills_tools

    context = context or ToolContext(
        library_path=library_path,
        annotations_dir=annotations_dir,
        html_dir=html_dir,
        papers_dir=papers_dir,
        paper_text_cache_dir=paper_text_cache_dir,
        paper_page_cache_dir=paper_page_cache_dir,
        paper_image_cache_dir=paper_image_cache_dir,
        media_store=media_store,
        paper_image_analyzer=paper_image_analyzer,
        mcp_manager=mcp_manager,
    )
    tools: list[BaseTool] = []
    tools.extend(create_paper_notes_tools(
        library_path=context.library_path,
        annotations_dir=context.annotations_dir,
        html_dir=context.html_dir,
        papers_dir=context.papers_dir,
        paper_text_cache_dir=context.paper_text_cache_dir,
        paper_page_cache_dir=context.paper_page_cache_dir,
        paper_image_cache_dir=context.paper_image_cache_dir,
        media_store=context.media_store,
        paper_image_analyzer=context.paper_image_analyzer,
    ))
    tools.extend(create_skills_tools())
    if context.mcp_manager is not None:
        get_tools = getattr(context.mcp_manager, "tools", None)
        if callable(get_tools):
            tools.extend(get_tools())
    return tools


__all__ = [
    "ToolContext",
    "create_tools",
]
