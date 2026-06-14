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
    session_id: str = ""
    provider_name: str = ""
    model: str = ""
    file_generation: dict[str, Any] | None = None
    image_generation: dict[str, Any] | None = None
    attachments: list[dict[str, Any]] | None = None


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
    session_id: str = "",
    provider_name: str = "",
    model: str = "",
    file_generation: dict[str, Any] | None = None,
    image_generation: dict[str, Any] | None = None,
    attachments: list[dict[str, Any]] | None = None,
) -> list[BaseTool]:
    from tools.generated_files import create_tools as create_generated_file_tools
    from tools.generated_images import create_tools as create_generated_image_tools
    from tools.paper_notes import create_tools as create_paper_notes_tools
    from tools.skills import create_tools as create_skills_tools
    from tools.web_fetch import create_tools as create_web_fetch_tools
    from tools.web_search import create_tools as create_web_search_tools

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
        session_id=session_id,
        provider_name=provider_name,
        model=model,
        file_generation=file_generation,
        image_generation=image_generation,
        attachments=attachments,
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
    tools.extend(create_generated_file_tools(
        media_store=context.media_store,
        session_id=context.session_id,
        provider_name=context.provider_name,
        model=context.model,
        file_generation=context.file_generation,
    ))
    tools.extend(create_generated_image_tools(
        media_store=context.media_store,
        session_id=context.session_id,
        provider_name=context.provider_name,
        model=context.model,
        image_generation=context.image_generation,
        attachments=context.attachments,
    ))
    tools.extend(create_web_search_tools())
    tools.extend(create_web_fetch_tools())
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
