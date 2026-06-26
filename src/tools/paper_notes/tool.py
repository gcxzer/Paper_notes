"""说明：创建 LangChain 可调用的 Paper Notes 工具。

作用：把 schema、上下文和 facade 函数包装成 agent 可以调用的工具对象。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from langchain_core.tools import StructuredTool

from app_config import load_app_config
import tools.paper_notes.impl.facade as facade
from tools.paper_notes.schemas import (
    get_paper_context_parameters,
    inspect_paper_visuals_parameters,
    manage_annotations_parameters,
    query_paper_content_parameters,
    read_paper_parameters,
    review_note_parameters,
    write_note_media_parameters,
    write_note_parameters,
)

__all__ = [
    "create_tools",
]

def create_tools(
    *,
    library_path: Path | None = None,
    annotations_dir: Path | None = None,
    html_dir: Path | None = None,
    papers_dir: Path | None = None,
    paper_visual_cache_dir: Path | None = None,
    media_store: Any | None = None,
    visual_inspection_available: bool = True,
    paper_image_analyzer: Any | None = None,
) -> list[StructuredTool]:
    can_inspect_visuals = bool(visual_inspection_available)
    rag_query_enabled = _rag_query_enabled()
    visual_actions = (
        "render_page for a PDF page image, extract_images only for embedded raster images, "
        "or analyze_image for visual Q&A"
    )
    query_visual_guidance = (
        "Use inspect_paper_visuals only for page rendering, embedded image extraction, or visual image analysis. "
        if can_inspect_visuals
        else "This model cannot inspect paper images, so answer figure/table questions from retrieved text and captions. "
    )
    content_tool = (
        StructuredTool(
            name="query_paper_content",
            description=(
                "Semantic RAG tool for reading and answering questions about a paper's actual PDF content "
                "when RAG querying is enabled and the paper index is ready. Use it for semantic questions "
                "about claims, methods, equations, experiments, results, figures/tables in context, related "
                "work, limitations, conclusions, or what any section says. Use get_paper_context instead only "
                "when the user explicitly asks about library metadata, note HTML/sections, annotations, tags, "
                f"or index status. {query_visual_guidance}Send one short retrieval query using exact paper "
                "labels and keywords. Preserve numbered references such as Figure 3, Table 2, Equation 4, "
                "Algorithm 1, Appendix C, or Section 5.2 instead of expanding them into broad explanatory "
                "questions. In paper context, generic picture/image/visual N phrasing should usually be "
                "queried as Figure N, not extracted image index N."
            ),
            args_schema=query_paper_content_parameters(),
            func=lambda **kwargs: facade.query_paper_content(dict(kwargs), library_path=library_path),
        )
        if rag_query_enabled
        else StructuredTool(
            name="read_paper",
            description=(
                "Directly read local PDF text without RAG. Use action=search_text for exact text snippets, "
                "or action=read_pages for page text. Use this when RAG querying is disabled or when the user "
                "asks for specific pages or raw/local PDF text."
            ),
            args_schema=read_paper_parameters(),
            func=lambda **kwargs: facade.read_paper(
                dict(kwargs),
                library_path=library_path,
                papers_dir=papers_dir,
            ),
        )
    )
    tools = [
        StructuredTool(
            name="get_paper_context",
            description=(
                "Find papers by local metadata or inspect one paper's note context. Pass note_id for detailed "
                "metadata, sections, annotations, optional note HTML, and local paper index status. Without "
                "note_id, pass query/limit to search or list the local library."
            ),
            args_schema=get_paper_context_parameters(),
            func=lambda **kwargs: facade.get_paper_context(
                dict(kwargs),
                library_path=library_path,
                annotations_dir=annotations_dir,
                html_dir=html_dir,
            ),
        ),
        content_tool,
        StructuredTool(
            name="manage_annotations",
            description=(
                "Create, update, or delete Paper Notes annotations. For create, provide either quote/query text that "
                "can be located in the PDF or explicit normalized rects/coordinates."
            ),
            args_schema=manage_annotations_parameters(),
            func=lambda **kwargs: facade.manage_annotations(
                dict(kwargs),
                library_path=library_path,
                annotations_dir=annotations_dir,
                papers_dir=papers_dir,
            ),
        ),
        StructuredTool(
            name="write_note",
            description=(
                "Modify note HTML sections or note metadata. Use action=append_to_section for normal additions, "
                "write_section for replacing or creating a section, delete_section, or update_metadata."
            ),
            args_schema=write_note_parameters(),
            func=lambda **kwargs: facade.write_note(
                dict(kwargs),
                library_path=library_path,
                html_dir=html_dir,
                media_store=media_store,
            ),
        ),
        StructuredTool(
            name="write_note_media",
            description=(
                "Write visual media into a note. Use action=insert_image for an existing image artifact."
            ),
            args_schema=write_note_media_parameters(),
            func=lambda **kwargs: facade.write_note_media(
                dict(kwargs),
                library_path=library_path,
                html_dir=html_dir,
                media_store=media_store,
            ),
        ),
        StructuredTool(
            name="review_note",
            description="Validate a note or preview a safe HTML section diff without saving changes.",
            args_schema=review_note_parameters(),
            func=lambda **kwargs: facade.review_note(
                dict(kwargs),
                library_path=library_path,
                html_dir=html_dir,
                media_store=media_store,
            ),
        ),
    ]
    if can_inspect_visuals:
        tools.insert(
            1,
            StructuredTool(
                name="inspect_paper_visuals",
                description=(
                    f"Inspect visual paper source material for a note. Use action={visual_actions}. "
                    "For a numbered paper figure, Figure N/图N is not PDF page N; first resolve the actual PDF "
                    "page with read_paper, or pass figure_label/query so this tool can correct a guessed page. "
                    "For explaining what a figure shows, prefer action=analyze_image over extract_images."
                ),
                args_schema=inspect_paper_visuals_parameters(),
                func=lambda **kwargs: facade.inspect_paper_visuals(
                    dict(kwargs),
                    library_path=library_path,
                    papers_dir=papers_dir,
                    paper_visual_cache_dir=paper_visual_cache_dir,
                    media_store=media_store,
                    paper_image_analyzer=paper_image_analyzer,
                ),
            ),
        )
    return tools


def _rag_query_enabled() -> bool:
    try:
        return bool(load_app_config().rag.query_enabled())
    except Exception:
        return True
