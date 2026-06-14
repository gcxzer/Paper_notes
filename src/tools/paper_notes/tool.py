from __future__ import annotations

from pathlib import Path
from typing import Any

from langchain_core.tools import StructuredTool

import tools.paper_notes.impl.facade as facade
from tools.paper_notes.schemas import (
    get_note_context_parameters,
    manage_annotations_parameters,
    read_paper_parameters,
    review_note_parameters,
    search_paper_rag_parameters,
    search_notes_parameters,
    write_note_media_parameters,
    write_note_parameters,
)


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
) -> list[StructuredTool]:
    return [
        StructuredTool(
            name="search_notes",
            description=(
                "Search or list local Paper Notes metadata by title, summary, venue, date, and tags. Use concise "
                "English-first paper keywords; for non-English user requests, include likely English terms "
                "and important original-language terms. Omit query, pass an empty query, or pass '*' only when "
                "the user asks to list/count the library."
            ),
            args_schema=search_notes_parameters(),
            func=lambda **kwargs: facade.search_notes(dict(kwargs), library_path=library_path),
        ),
        StructuredTool(
            name="get_note_context",
            description=(
                "Build a compact writing context for one note: metadata, current sections, annotations, "
                "optional note HTML, and optional PDF text snippets."
            ),
            args_schema=get_note_context_parameters(),
            func=lambda **kwargs: facade.get_note_context(
                dict(kwargs),
                library_path=library_path,
                annotations_dir=annotations_dir,
                html_dir=html_dir,
                papers_dir=papers_dir,
                paper_text_cache_dir=paper_text_cache_dir,
            ),
        ),
        StructuredTool(
            name="read_paper",
            description=(
                "Read paper source material for a note. Use action=search_text for focused snippets, read_pages for "
                "page text, render_page for a page image, extract_images for figures, or analyze_image for a registered artifact."
            ),
            args_schema=read_paper_parameters(),
            func=lambda **kwargs: facade.read_paper(
                dict(kwargs),
                library_path=library_path,
                papers_dir=papers_dir,
                paper_text_cache_dir=paper_text_cache_dir,
                paper_page_cache_dir=paper_page_cache_dir,
                paper_image_cache_dir=paper_image_cache_dir,
                media_store=media_store,
                paper_image_analyzer=paper_image_analyzer,
            ),
        ),
        StructuredTool(
            name="search_paper_rag",
            description=(
                "Semantically search a note's PDF only when its local RAG index is ready. Prefer read_paper when "
                "the PDF has not been indexed yet or when exact text/page access is needed."
            ),
            args_schema=search_paper_rag_parameters(),
            func=lambda **kwargs: facade.search_paper_rag(dict(kwargs), library_path=library_path),
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
            name="write_note_media",
            description=(
                "Write note content from a paper image or insert an existing image artifact into a note. "
                "Use action=write_from_image or insert_image."
            ),
            args_schema=write_note_media_parameters(),
            func=lambda **kwargs: facade.write_note_media(
                dict(kwargs),
                library_path=library_path,
                html_dir=html_dir,
                papers_dir=papers_dir,
                paper_page_cache_dir=paper_page_cache_dir,
                media_store=media_store,
                paper_image_analyzer=paper_image_analyzer,
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


__all__ = ["create_tools"]
