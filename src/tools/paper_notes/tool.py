from __future__ import annotations

import html as html_lib
import json
import re
import time
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from library.annotations import read_annotations as read_note_annotations, write_annotations
from app_infra.formatting import normalize_text
from library import find_note, normalize_tags, read_library, write_library
from app_infra.paths import HTML_DIR, PAPERS_DIR, PROJECT_ROOT, is_relative_to
from app_infra.storage import atomic_write_text
from tools.paper_notes.manifest import TOOL_GROUP
from tools.registry import ToolDefinition, ToolRegistry


PAPER_NOTES_TOOLSET = "paper_notes"
PAPER_NOTES_INTERNAL_TOOLSET = "paper_notes_internal"
SAFE_HTML_TAGS = {
    "a",
    "blockquote",
    "code",
    "em",
    "figcaption",
    "figure",
    "h2",
    "h3",
    "h4",
    "img",
    "li",
    "ol",
    "p",
    "pre",
    "strong",
    "table",
    "tbody",
    "td",
    "th",
    "thead",
    "tr",
    "ul",
}
SAFE_ATTRS_BY_TAG = {
    "a": {"href", "title"},
    "figure": {"class"},
    "h2": {"id"},
    "h3": {"id"},
    "h4": {"id"},
    "img": {"src", "alt", "title", "width", "height", "loading"},
    "td": {"colspan", "rowspan"},
    "th": {"colspan", "rowspan"},
}
ANNOTATION_COLORS = {"yellow", "green", "blue", "red", "purple"}
ANNOTATION_TYPES = {"highlight", "underline", "area", "note"}
_NOTE_BODY_RE = re.compile(
    r"(?is)(<(?P<tag>section|div|main)\b(?=[^>]*\bclass=[\"'][^\"']*\bnote-body\b[^\"']*[\"'])[^>]*>)"
    r"(?P<body>.*?)"
    r"(</(?P=tag)>)"
)
_HEADING_RE = re.compile(r"(?is)<h([2-4])\b[^>]*>(.*?)</h\1>")
_HEADING_WITH_ATTRS_RE = re.compile(r"(?is)<h([2-4])([^>]*)>(.*?)</h\1>")


def create_paper_notes_registry(
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
) -> ToolRegistry:
    registry = ToolRegistry()
    register_paper_notes_tools(
        registry,
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
    return registry


def register_paper_notes_tools(
    registry: ToolRegistry,
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
) -> None:
    registry.register_group(TOOL_GROUP)
    _register_paper_notes_facade_tools(
        registry,
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
    registry.register(ToolDefinition(
        name="search_library",
        description=(
            "Search or list local Paper Notes metadata by title, summary, venue, date, and tags. Use concise "
            "English-first paper keywords; for non-English user requests, include likely English terms "
            "and important original-language terms. Omit query, pass an empty query, or pass '*' only when "
            "the user asks to list/count the library."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "Optional concise metadata search keywords. Prefer English paper terms and common acronyms; "
                        "preserve important original-language terms for multilingual queries. Use '*' or omit this "
                        "only to list/count local notes."
                    ),
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of notes to return.",
                    "minimum": 1,
                    "maximum": 25,
                },
            },
            "required": [],
            "additionalProperties": False,
        },
        handler=lambda args: paper_notes_search(args, library_path=library_path),
        toolset=PAPER_NOTES_INTERNAL_TOOLSET,
        read_only=True,
        risk="read",
        kind="search",
    ))
    registry.register(ToolDefinition(
        name="get_note",
        description="Get one Paper Notes library entry by note id.",
        parameters={
            "type": "object",
            "properties": {
                "note_id": {
                    "type": "string",
                    "description": "The note id to retrieve.",
                },
            },
            "required": ["note_id"],
            "additionalProperties": False,
        },
        handler=lambda args: get_note(args, library_path=library_path),
        toolset=PAPER_NOTES_INTERNAL_TOOLSET,
        read_only=True,
        risk="read",
        kind="read",
    ))
    registry.register(ToolDefinition(
        name="read_annotations",
        description="Read annotations for a Paper Notes entry by note id.",
        parameters={
            "type": "object",
            "properties": {
                "note_id": {
                    "type": "string",
                    "description": "The note id whose annotations should be read.",
                },
            },
            "required": ["note_id"],
            "additionalProperties": False,
        },
        handler=lambda args: read_annotations_tool(args, annotations_dir=annotations_dir),
        toolset=PAPER_NOTES_INTERNAL_TOOLSET,
        read_only=True,
        risk="read",
        kind="read",
        result_max_chars=12_000,
    ))
    registry.register(ToolDefinition(
        name="read_note_html",
        description="Read the generated HTML note for one Paper Notes entry.",
        parameters={
            "type": "object",
            "properties": {
                "note_id": {"type": "string", "description": "The note id to read."},
                "mode": {
                    "type": "string",
                    "enum": ["body", "full"],
                    "description": "body returns only .note-body content; full returns the full HTML document.",
                },
            },
            "required": ["note_id"],
            "additionalProperties": False,
        },
        handler=lambda args: read_note_html(args, library_path=library_path, html_dir=html_dir),
        toolset=PAPER_NOTES_INTERNAL_TOOLSET,
        read_only=True,
        risk="read",
        kind="read",
        result_max_chars=14_000,
    ))
    registry.register(ToolDefinition(
        name="list_note_sections",
        description="List h2-h4 sections in a generated Paper Notes HTML note.",
        parameters={
            "type": "object",
            "properties": {
                "note_id": {"type": "string", "description": "The note id whose HTML outline should be read."},
            },
            "required": ["note_id"],
            "additionalProperties": False,
        },
        handler=lambda args: list_note_sections(args, library_path=library_path, html_dir=html_dir),
        toolset=PAPER_NOTES_INTERNAL_TOOLSET,
        read_only=True,
        risk="read",
        kind="read",
    ))
    registry.register(ToolDefinition(
        name="search_paper_text",
        description="Search cached or locally extracted PDF text for a Paper Notes entry.",
        parameters={
            "type": "object",
            "properties": {
                "note_id": {"type": "string", "description": "The note id whose PDF text should be searched."},
                "query": {"type": "string", "description": "Keyword or phrase to search in the PDF text."},
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 10,
                    "description": "Maximum matching snippets to return.",
                },
            },
            "required": ["note_id", "query"],
            "additionalProperties": False,
        },
        handler=lambda args: search_paper_text(
            args,
            library_path=library_path,
            papers_dir=papers_dir,
            paper_text_cache_dir=paper_text_cache_dir,
        ),
        toolset=PAPER_NOTES_INTERNAL_TOOLSET,
        read_only=True,
        risk="read",
        kind="search",
        result_max_chars=12_000,
    ))
    registry.register(ToolDefinition(
        name="read_paper_text",
        description="Read cached or locally extracted PDF text for a Paper Notes entry by page range.",
        parameters={
            "type": "object",
            "properties": {
                "note_id": {"type": "string", "description": "The note id whose PDF text should be read."},
                "page_start": {"type": "integer", "minimum": 1, "description": "First page to read, 1-indexed."},
                "page_end": {"type": "integer", "minimum": 1, "description": "Last page to read, inclusive."},
                "max_chars": {
                    "type": "integer",
                    "minimum": 500,
                    "maximum": 20000,
                    "description": "Maximum text characters to return.",
                },
            },
            "required": ["note_id"],
            "additionalProperties": False,
        },
        handler=lambda args: read_paper_text(
            args,
            library_path=library_path,
            papers_dir=papers_dir,
            paper_text_cache_dir=paper_text_cache_dir,
        ),
        toolset=PAPER_NOTES_INTERNAL_TOOLSET,
        read_only=True,
        risk="read",
        kind="read",
        result_max_chars=16_000,
    ))
    registry.register(ToolDefinition(
        name="render_paper_page",
        description="Render one PDF page for a Paper Notes entry into a cached PNG image.",
        parameters={
            "type": "object",
            "properties": {
                "note_id": {"type": "string", "description": "The note id whose PDF page should be rendered."},
                "page": {"type": "integer", "minimum": 1, "description": "PDF page number to render, 1-indexed."},
                "scale": {
                    "type": "number",
                    "minimum": 0.5,
                    "maximum": 4,
                    "description": "Render scale. 2 is a good default for readable page images.",
                },
            },
            "required": ["note_id", "page"],
            "additionalProperties": False,
        },
        handler=lambda args: render_paper_page(
            args,
            library_path=library_path,
            papers_dir=papers_dir,
            paper_page_cache_dir=paper_page_cache_dir,
            media_store=media_store,
        ),
        toolset=PAPER_NOTES_INTERNAL_TOOLSET,
        read_only=True,
        risk="read",
        kind="read",
        result_max_chars=4_000,
    ))
    registry.register(ToolDefinition(
        name="extract_paper_images",
        description="Extract embedded images and figures from a Paper Notes PDF into a local cache.",
        parameters={
            "type": "object",
            "properties": {
                "note_id": {"type": "string", "description": "The note id whose PDF images should be extracted."},
                "page_start": {"type": "integer", "minimum": 1, "description": "First page to inspect, 1-indexed."},
                "page_end": {"type": "integer", "minimum": 1, "description": "Last page to inspect, inclusive."},
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 50,
                    "description": "Maximum extracted images to return.",
                },
            },
            "required": ["note_id"],
            "additionalProperties": False,
        },
        handler=lambda args: extract_paper_images(
            args,
            library_path=library_path,
            papers_dir=papers_dir,
            paper_image_cache_dir=paper_image_cache_dir,
            media_store=media_store,
        ),
        toolset=PAPER_NOTES_INTERNAL_TOOLSET,
        read_only=True,
        risk="read",
        kind="read",
        result_max_chars=8_000,
    ))
    registry.register(ToolDefinition(
        name="analyze_paper_image",
        description=(
            "Analyze a registered paper image artifact with the current vision-capable model. "
            "Use this after render_paper_page or extract_paper_images when a figure, chart, table, or scanned text "
            "needs visual interpretation before writing notes."
        ),
        parameters={
            "type": "object",
            "properties": {
                "artifact_id": {"type": "string", "description": "Registered image artifact id to analyze."},
                "path": {
                    "type": "string",
                    "description": "Optional local path for a previously registered image artifact.",
                },
                "question": {
                    "type": "string",
                    "description": "Specific analysis question for the image.",
                },
            },
            "additionalProperties": False,
        },
        handler=lambda args: paper_image_analyzer(args) if callable(paper_image_analyzer) else {
            "success": False,
            "error": "Image analysis is not available in this registry.",
            "code": "image_analysis_unavailable",
        },
        toolset=PAPER_NOTES_INTERNAL_TOOLSET,
        read_only=True,
        risk="read",
        kind="read",
        result_max_chars=8_000,
    ))
    registry.register(ToolDefinition(
        name="build_note_context",
        description=(
            "Build a compact writing context for one note: metadata, current note sections, annotations, "
            "and optional PDF text snippets matching a query."
        ),
        parameters={
            "type": "object",
            "properties": {
                "note_id": {"type": "string", "description": "The note id to build context for."},
                "query": {"type": "string", "description": "Optional PDF text query for focused snippets."},
                "max_paper_matches": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 8,
                    "description": "Maximum PDF text snippets to include when query is provided.",
                },
            },
            "required": ["note_id"],
            "additionalProperties": False,
        },
        handler=lambda args: build_note_context(
            args,
            library_path=library_path,
            annotations_dir=annotations_dir,
            html_dir=html_dir,
            papers_dir=papers_dir,
            paper_text_cache_dir=paper_text_cache_dir,
        ),
        toolset=PAPER_NOTES_INTERNAL_TOOLSET,
        read_only=True,
        risk="read",
        kind="read",
        result_max_chars=18_000,
    ))
    registry.register(ToolDefinition(
        name="validate_note_html",
        description="Validate a generated Paper Notes HTML note for .note-body, unsafe HTML, and heading structure.",
        parameters={
            "type": "object",
            "properties": {
                "note_id": {"type": "string", "description": "The note id whose HTML note should be validated."},
            },
            "required": ["note_id"],
            "additionalProperties": False,
        },
        handler=lambda args: validate_note_html(args, library_path=library_path, html_dir=html_dir),
        toolset=PAPER_NOTES_INTERNAL_TOOLSET,
        read_only=True,
        risk="read",
        kind="read",
    ))
    registry.register(ToolDefinition(
        name="preview_note_diff",
        description="Preview how a safe HTML note-section write would change a note without saving the file.",
        parameters={
            "type": "object",
            "properties": {
                "note_id": {"type": "string", "description": "The note id to preview."},
                "heading": {"type": "string", "description": "New or target heading."},
                "html": {"type": "string", "description": "Safe HTML fragment to preview."},
                "position": {
                    "type": "string",
                    "enum": ["append", "prepend", "after_heading", "replace_heading"],
                    "description": "Where to place the section.",
                },
            },
            "required": ["note_id", "heading", "html"],
            "additionalProperties": False,
        },
        handler=lambda args: preview_note_diff(args, library_path=library_path, html_dir=html_dir),
        toolset=PAPER_NOTES_INTERNAL_TOOLSET,
        read_only=True,
        risk="read",
        kind="read",
    ))
    registry.register(ToolDefinition(
        name="write_note_from_paper_image",
        description=(
            "Analyze a rendered PDF page or registered image artifact, convert the analysis into a safe HTML note "
            "section, preview the change, write it to the local note, and validate the saved HTML. Use this when "
            "the user asks you to write notes from a figure, chart, scanned page, or PDF page image."
        ),
        parameters={
            "type": "object",
            "properties": {
                "note_id": {"type": "string", "description": "The note id to modify."},
                "heading": {"type": "string", "description": "Heading for the note section to write."},
                "question": {
                    "type": "string",
                    "description": "Specific question or writing focus for the image analysis.",
                },
                "artifact_id": {
                    "type": "string",
                    "description": "Existing registered image artifact id. If omitted, page is rendered from the note PDF.",
                },
                "page": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "PDF page number to render when artifact_id is not provided.",
                },
                "scale": {
                    "type": "number",
                    "minimum": 0.5,
                    "maximum": 4,
                    "description": "Render scale for PDF pages. 2 is a good default.",
                },
                "position": {
                    "type": "string",
                    "enum": ["append", "prepend", "after_heading", "replace_heading"],
                    "description": "Where to place the section in the note.",
                },
            },
            "required": ["note_id", "heading"],
            "additionalProperties": False,
        },
        handler=lambda args: write_note_from_paper_image(
            args,
            library_path=library_path,
            html_dir=html_dir,
            papers_dir=papers_dir,
            paper_page_cache_dir=paper_page_cache_dir,
            media_store=media_store,
            paper_image_analyzer=paper_image_analyzer,
        ),
        toolset=PAPER_NOTES_INTERNAL_TOOLSET,
        mutating=True,
        risk="write",
        kind="write",
        supports_snapshot=True,
        supports_rollback=True,
        approval_scope="note",
        affected_resources=lambda args: [f"note-html:{normalize_text(args.get('note_id'))}"],
        result_max_chars=10_000,
    ))
    registry.register(ToolDefinition(
        name="write_note_section",
        description=(
            "Write a safe HTML section into a generated Paper Notes note. Directly saves the local HTML file. "
            "Allowed HTML tags are h2, h3, h4, p, ul, ol, li, blockquote, code, pre, table, thead, tbody, tr, th, td, "
            "a, strong, and em."
        ),
        parameters={
            "type": "object",
            "properties": {
                "note_id": {"type": "string", "description": "The note id to modify."},
                "heading": {
                    "type": "string",
                    "description": "New heading for append/prepend, or target heading for after_heading/replace_heading.",
                },
                "html": {"type": "string", "description": "Safe HTML fragment to write."},
                "position": {
                    "type": "string",
                    "enum": ["append", "prepend", "after_heading", "replace_heading"],
                    "description": "Where to place the section.",
                },
            },
            "required": ["note_id", "heading", "html"],
            "additionalProperties": False,
        },
        handler=lambda args: write_note_section(args, library_path=library_path, html_dir=html_dir, media_store=media_store),
        toolset=PAPER_NOTES_INTERNAL_TOOLSET,
        mutating=True,
        risk="write",
        kind="write",
        supports_snapshot=True,
        supports_rollback=True,
        approval_scope="note",
        affected_resources=lambda args: [f"note-html:{normalize_text(args.get('note_id'))}"],
        result_max_chars=8_000,
    ))
    registry.register(ToolDefinition(
        name="append_note_section",
        description="Append a safe HTML section to a generated Paper Notes note and save it immediately.",
        parameters={
            "type": "object",
            "properties": {
                "note_id": {"type": "string", "description": "The note id to modify."},
                "heading": {"type": "string", "description": "Heading for the new section."},
                "html": {"type": "string", "description": "Safe HTML fragment to append."},
            },
            "required": ["note_id", "heading", "html"],
            "additionalProperties": False,
        },
        handler=lambda args: append_note_section(args, library_path=library_path, html_dir=html_dir, media_store=media_store),
        toolset=PAPER_NOTES_INTERNAL_TOOLSET,
        mutating=True,
        risk="write",
        kind="write",
        supports_snapshot=True,
        supports_rollback=True,
        approval_scope="note",
        affected_resources=lambda args: [f"note-html:{normalize_text(args.get('note_id'))}"],
        result_max_chars=8_000,
    ))
    registry.register(ToolDefinition(
        name="replace_note_section",
        description="Replace an existing h2-h4 section in a generated Paper Notes note and save it immediately.",
        parameters={
            "type": "object",
            "properties": {
                "note_id": {"type": "string", "description": "The note id to modify."},
                "heading": {"type": "string", "description": "Existing heading text to replace."},
                "html": {"type": "string", "description": "Safe replacement HTML fragment."},
            },
            "required": ["note_id", "heading", "html"],
            "additionalProperties": False,
        },
        handler=lambda args: replace_note_section(args, library_path=library_path, html_dir=html_dir, media_store=media_store),
        toolset=PAPER_NOTES_INTERNAL_TOOLSET,
        mutating=True,
        risk="write",
        kind="write",
        supports_snapshot=True,
        supports_rollback=True,
        approval_scope="note",
        affected_resources=lambda args: [f"note-html:{normalize_text(args.get('note_id'))}"],
        result_max_chars=8_000,
    ))
    registry.register(ToolDefinition(
        name="update_note_metadata",
        description="Update allowed Paper Notes metadata fields in notes.json for one note.",
        parameters={
            "type": "object",
            "properties": {
                "note_id": {"type": "string", "description": "The note id to update."},
                "summary": {"type": "string", "description": "Short note summary."},
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Tags for the note.",
                },
                "venue": {"type": "string", "description": "Publication venue or source."},
                "date": {"type": "string", "description": "Publication or imported date label."},
                "category_id": {"type": "string", "description": "Target category id."},
                "collection": {
                    "type": "string",
                    "description": "Target collection name or collection path. Resolved to category_id before saving.",
                },
            },
            "required": ["note_id"],
            "additionalProperties": False,
        },
        handler=lambda args: update_note_metadata(args, library_path=library_path),
        toolset=PAPER_NOTES_INTERNAL_TOOLSET,
        mutating=True,
        risk="write",
        kind="write",
        supports_snapshot=True,
        supports_rollback=True,
        approval_scope="library",
        affected_resources=lambda args: ["notes.json", f"note-metadata:{normalize_text(args.get('note_id'))}"],
    ))

def _register_paper_notes_facade_tools(
    registry: ToolRegistry,
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
) -> None:
    registry.register(ToolDefinition(
        name="paper_notes_search",
        description=(
            "Search or list local Paper Notes metadata by title, summary, venue, date, and tags. Use concise "
            "English-first paper keywords; for non-English user requests, include likely English terms "
            "and important original-language terms. Omit query, pass an empty query, or pass '*' only when "
            "the user asks to list/count the library."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "Optional concise metadata search keywords. Prefer English paper terms and common acronyms; "
                        "preserve important original-language terms for multilingual queries. Use '*' or omit this "
                        "only to list/count local notes."
                    ),
                },
                "limit": {"type": "integer", "minimum": 1, "maximum": 25, "description": "Maximum notes to return."},
            },
            "required": [],
            "additionalProperties": False,
        },
        handler=lambda args: search_library(args, library_path=library_path),
        toolset=PAPER_NOTES_TOOLSET,
        read_only=True,
        risk="read",
        kind="search",
        result_max_chars=10_000,
        metadata={"facade": True, "internal_tools": ["search_library"]},
    ))
    registry.register(ToolDefinition(
        name="paper_notes_context",
        description=(
            "Build a compact writing context for one note: metadata, current sections, annotations, "
            "optional note HTML, and optional PDF text snippets."
        ),
        parameters={
            "type": "object",
            "properties": {
                "note_id": {"type": "string", "description": "The note id to inspect."},
                "query": {"type": "string", "description": "Optional PDF text query for focused snippets."},
                "include_html": {"type": "boolean", "description": "Include current note HTML body when true."},
                "html_mode": {"type": "string", "enum": ["body", "full"], "description": "HTML read mode."},
                "max_paper_matches": {"type": "integer", "minimum": 0, "maximum": 8},
            },
            "required": ["note_id"],
            "additionalProperties": False,
        },
        handler=lambda args: paper_notes_context(
            args,
            library_path=library_path,
            annotations_dir=annotations_dir,
            html_dir=html_dir,
            papers_dir=papers_dir,
            paper_text_cache_dir=paper_text_cache_dir,
        ),
        toolset=PAPER_NOTES_TOOLSET,
        read_only=True,
        risk="read",
        kind="read",
        result_max_chars=18_000,
        metadata={"facade": True, "internal_tools": ["get_note", "read_note_html", "list_note_sections", "read_annotations", "build_note_context"]},
    ))
    registry.register(ToolDefinition(
        name="paper_notes_read_paper",
        description=(
            "Read paper source material for a note. Use action=search_text for focused snippets, read_pages for "
            "page text, render_page for a page image, extract_images for figures, or analyze_image for a registered artifact."
        ),
        parameters={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["search_text", "read_pages", "render_page", "extract_images", "analyze_image"],
                },
                "note_id": {"type": "string", "description": "The note id whose PDF should be read."},
                "query": {"type": "string", "description": "Search or image-analysis question."},
                "page": {"type": "integer", "minimum": 1, "description": "Page number for render_page."},
                "page_start": {"type": "integer", "minimum": 1},
                "page_end": {"type": "integer", "minimum": 1},
                "limit": {"type": "integer", "minimum": 1, "maximum": 50},
                "max_chars": {"type": "integer", "minimum": 500, "maximum": 20000},
                "scale": {"type": "number", "minimum": 0.5, "maximum": 4},
                "artifact_id": {"type": "string", "description": "Registered image artifact id for analyze_image."},
                "path": {"type": "string", "description": "Optional registered artifact path for analyze_image."},
            },
            "required": ["note_id"],
            "additionalProperties": False,
        },
        handler=lambda args: paper_notes_read_paper(
            args,
            library_path=library_path,
            papers_dir=papers_dir,
            paper_text_cache_dir=paper_text_cache_dir,
            paper_page_cache_dir=paper_page_cache_dir,
            paper_image_cache_dir=paper_image_cache_dir,
            media_store=media_store,
            paper_image_analyzer=paper_image_analyzer,
        ),
        toolset=PAPER_NOTES_TOOLSET,
        read_only=True,
        risk="read",
        kind="read",
        result_max_chars=16_000,
        metadata={
            "facade": True,
            "internal_tools": ["search_paper_text", "read_paper_text", "render_paper_page", "extract_paper_images", "analyze_paper_image"],
        },
    ))
    registry.register(ToolDefinition(
        name="paper_notes_edit",
        description=(
            "Modify local Paper Notes content. Use this only when the user clearly wants notes, metadata, "
            "or annotations changed. HTML writes are validated after saving."
        ),
        parameters={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "write_section",
                        "append_section",
                        "replace_section",
                        "delete_section",
                        "update_metadata",
                        "create_annotation",
                        "update_annotation",
                        "delete_annotation",
                        "write_from_image",
                        "insert_image",
                    ],
                },
                "note_id": {"type": "string", "description": "The note id to modify."},
                "heading": {"type": "string", "description": "Heading to create, append after, replace, delete, write from image, or insert an image into."},
                "html": {"type": "string", "description": "Safe HTML fragment for section writes."},
                "position": {
                    "type": "string",
                    "enum": ["append", "prepend", "after_heading", "replace_heading"],
                    "description": "Section placement for write_section, write_from_image, or insert_image.",
                },
                "summary": {"type": "string", "description": "Metadata summary update."},
                "tags": {"type": "array", "items": {"type": "string"}, "description": "Metadata tag update."},
                "venue": {"type": "string", "description": "Metadata venue update."},
                "date": {"type": "string", "description": "Metadata date update."},
                "category_id": {"type": "string", "description": "Metadata category id update."},
                "collection": {
                    "type": "string",
                    "description": "Metadata collection name or path update. Resolved to category_id before saving.",
                },
                "annotation_id": {"type": "string", "description": "Annotation id for update/delete, or optional id for create."},
                "annotation_type": {
                    "type": "string",
                    "enum": ["highlight", "underline", "area", "note"],
                    "description": "Annotation type for create_annotation.",
                },
                "comment": {"type": "string", "description": "Annotation comment."},
                "quote": {"type": "string", "description": "Quoted PDF text for create/update annotation."},
                "query": {
                    "type": "string",
                    "description": "PDF text to locate when creating an annotation without explicit coordinates.",
                },
                "color": {"type": "string", "enum": ["yellow", "green", "blue", "red", "purple"]},
                "x": {"type": "number", "minimum": 0, "maximum": 1},
                "y": {"type": "number", "minimum": 0, "maximum": 1},
                "w": {"type": "number", "minimum": 0, "maximum": 1},
                "h": {"type": "number", "minimum": 0, "maximum": 1},
                "rects": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "x": {"type": "number", "minimum": 0, "maximum": 1},
                            "y": {"type": "number", "minimum": 0, "maximum": 1},
                            "w": {"type": "number", "minimum": 0, "maximum": 1},
                            "h": {"type": "number", "minimum": 0, "maximum": 1},
                        },
                        "required": ["x", "y", "w", "h"],
                        "additionalProperties": False,
                    },
                    "description": "Normalized PDF page rectangles for create/update annotation.",
                },
                "artifact_id": {
                    "type": "string",
                    "description": "Image artifact id for write_from_image or insert_image. For insert_image, a registered media path or file name is also accepted.",
                },
                "page": {"type": "integer", "minimum": 1, "description": "PDF page for write_from_image or annotation create/update."},
                "scale": {"type": "number", "minimum": 0.5, "maximum": 4},
                "question": {"type": "string", "description": "Image-analysis or writing focus for write_from_image."},
                "caption": {"type": "string", "description": "Figure caption for insert_image."},
                "alt": {"type": "string", "description": "Image alt text for insert_image."},
            },
            "required": ["action", "note_id"],
            "additionalProperties": False,
        },
        handler=lambda args: paper_notes_edit(
            args,
            library_path=library_path,
            annotations_dir=annotations_dir,
            html_dir=html_dir,
            papers_dir=papers_dir,
            paper_page_cache_dir=paper_page_cache_dir,
            media_store=media_store,
            paper_image_analyzer=paper_image_analyzer,
        ),
        toolset=PAPER_NOTES_TOOLSET,
        mutating=True,
        risk="write",
        kind="write",
        supports_snapshot=True,
        supports_rollback=True,
        approval_scope="note",
        affected_resources=lambda args: [f"paper-notes:{normalize_text(args.get('note_id'))}:{normalize_text(args.get('action'))}"],
        result_max_chars=10_000,
        metadata={
            "facade": True,
            "internal_tools": [
                "write_note_section",
                "append_note_section",
                "replace_note_section",
                "delete_note_section",
                "update_note_metadata",
                "create_annotation",
                "update_annotation",
                "delete_annotation",
                "write_note_from_paper_image",
                "insert_note_image",
            ],
        },
    ))
    registry.register(ToolDefinition(
        name="paper_notes_review",
        description="Validate a note or preview a safe HTML section diff without saving changes.",
        parameters={
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["validate_html", "preview_note_diff"]},
                "note_id": {"type": "string", "description": "The note id to review."},
                "heading": {"type": "string", "description": "Heading for preview_note_diff."},
                "html": {"type": "string", "description": "Safe HTML fragment for preview_note_diff."},
                "position": {
                    "type": "string",
                    "enum": ["append", "prepend", "after_heading", "replace_heading"],
                },
            },
            "required": ["action", "note_id"],
            "additionalProperties": False,
        },
        handler=lambda args: paper_notes_review(args, library_path=library_path, html_dir=html_dir, media_store=media_store),
        toolset=PAPER_NOTES_TOOLSET,
        read_only=True,
        risk="read",
        kind="read",
        result_max_chars=10_000,
        metadata={"facade": True, "internal_tools": ["validate_note_html", "preview_note_diff"]},
    ))


def paper_notes_context(
    args: dict[str, Any],
    *,
    library_path: Path | None = None,
    annotations_dir: Path | None = None,
    html_dir: Path | None = None,
    papers_dir: Path | None = None,
    paper_text_cache_dir: Path | None = None,
) -> dict[str, Any]:
    payload = build_note_context(
        args,
        library_path=library_path,
        annotations_dir=annotations_dir,
        html_dir=html_dir,
        papers_dir=papers_dir,
        paper_text_cache_dir=paper_text_cache_dir,
    )
    if not payload.get("success"):
        return payload
    if _truthy(args.get("include_html")):
        html_payload = read_note_html(
            {**args, "mode": normalize_text(args.get("html_mode") or "body") or "body"},
            library_path=library_path,
            html_dir=html_dir,
        )
        payload["html"] = html_payload if html_payload.get("success") else {"error": html_payload.get("error"), "code": html_payload.get("code")}
    return payload


def paper_notes_search(args: dict[str, Any], *, library_path: Path | None = None) -> dict[str, Any]:
    return search_library(args, library_path=library_path)


def paper_notes_read_paper(
    args: dict[str, Any],
    *,
    library_path: Path | None = None,
    papers_dir: Path | None = None,
    paper_text_cache_dir: Path | None = None,
    paper_page_cache_dir: Path | None = None,
    paper_image_cache_dir: Path | None = None,
    media_store: Any | None = None,
    paper_image_analyzer: Any | None = None,
) -> dict[str, Any]:
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
        return search_paper_text(args, library_path=library_path, papers_dir=papers_dir, paper_text_cache_dir=paper_text_cache_dir)
    if action == "read_pages":
        return read_paper_text(args, library_path=library_path, papers_dir=papers_dir, paper_text_cache_dir=paper_text_cache_dir)
    if action == "render_page":
        return render_paper_page(args, library_path=library_path, papers_dir=papers_dir, paper_page_cache_dir=paper_page_cache_dir, media_store=media_store)
    if action == "extract_images":
        return extract_paper_images(args, library_path=library_path, papers_dir=papers_dir, paper_image_cache_dir=paper_image_cache_dir, media_store=media_store)
    if action == "analyze_image":
        if not callable(paper_image_analyzer):
            return _tool_error("image_analysis_unavailable", "Image analysis is not available in this registry.", note_id=normalize_text(args.get("note_id")))
        return paper_image_analyzer({
            "artifact_id": args.get("artifact_id"),
            "path": args.get("path"),
            "question": args.get("query") or args.get("question") or "Analyze this paper image.",
        })
    return _tool_error("invalid_action", "action must be search_text, read_pages, render_page, extract_images, or analyze_image.", note_id=normalize_text(args.get("note_id")))


def paper_notes_edit(
    args: dict[str, Any],
    *,
    library_path: Path | None = None,
    annotations_dir: Path | None = None,
    html_dir: Path | None = None,
    papers_dir: Path | None = None,
    paper_page_cache_dir: Path | None = None,
    media_store: Any | None = None,
    paper_image_analyzer: Any | None = None,
) -> dict[str, Any]:
    action = normalize_text(args.get("action")).lower()
    if action == "write_section":
        result = write_note_section(args, library_path=library_path, html_dir=html_dir, media_store=media_store)
        return _with_html_validation(result, library_path=library_path, html_dir=html_dir)
    if action == "append_section":
        result = append_note_section(args, library_path=library_path, html_dir=html_dir, media_store=media_store)
        return _with_html_validation(result, library_path=library_path, html_dir=html_dir)
    if action == "replace_section":
        result = replace_note_section(args, library_path=library_path, html_dir=html_dir, media_store=media_store)
        return _with_html_validation(result, library_path=library_path, html_dir=html_dir)
    if action == "delete_section":
        result = delete_note_section(args, library_path=library_path, html_dir=html_dir)
        return _with_html_validation(result, library_path=library_path, html_dir=html_dir)
    if action == "update_metadata":
        return update_note_metadata(_without_action(args), library_path=library_path)
    if action == "create_annotation":
        return create_annotation(_without_action(args), library_path=library_path, annotations_dir=annotations_dir, papers_dir=papers_dir)
    if action == "update_annotation":
        return update_annotation(_without_action(args), annotations_dir=annotations_dir)
    if action == "delete_annotation":
        return delete_annotation(_without_action(args), annotations_dir=annotations_dir)
    if action == "write_from_image":
        return write_note_from_paper_image(
            args,
            library_path=library_path,
            html_dir=html_dir,
            papers_dir=papers_dir,
            paper_page_cache_dir=paper_page_cache_dir,
            media_store=media_store,
            paper_image_analyzer=paper_image_analyzer,
        )
    if action == "insert_image":
        result = insert_note_image(
            args,
            library_path=library_path,
            html_dir=html_dir,
            media_store=media_store,
        )
        return _with_html_validation(result, library_path=library_path, html_dir=html_dir)
    return _tool_error(
        "invalid_action",
        "action must be write_section, append_section, replace_section, delete_section, update_metadata, create_annotation, update_annotation, delete_annotation, write_from_image, or insert_image.",
        note_id=normalize_text(args.get("note_id")),
    )


def _without_action(args: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in args.items() if key != "action"}


def paper_notes_review(
    args: dict[str, Any],
    *,
    library_path: Path | None = None,
    html_dir: Path | None = None,
    media_store: Any | None = None,
) -> dict[str, Any]:
    action = normalize_text(args.get("action") or "validate_html").lower()
    if action == "validate_html":
        return validate_note_html(args, library_path=library_path, html_dir=html_dir)
    if action == "preview_note_diff":
        resolved_args, error = _resolve_media_source_args(args, media_store)
        if error:
            return error
        return preview_note_diff(resolved_args, library_path=library_path, html_dir=html_dir)
    return _tool_error("invalid_action", "action must be validate_html or preview_note_diff.", note_id=normalize_text(args.get("note_id")))


def _with_html_validation(
    result: dict[str, Any],
    *,
    library_path: Path | None,
    html_dir: Path | None,
) -> dict[str, Any]:
    if not result.get("success"):
        return result
    note_id = normalize_text(result.get("note_id"))
    validation = validate_note_html({"note_id": note_id}, library_path=library_path, html_dir=html_dir)
    return {
        **result,
        "validation": validation,
        "success": bool(validation.get("success") and validation.get("valid") is not False),
    }


def search_library(args: dict[str, Any], *, library_path: Path | None = None) -> dict[str, Any]:
    query = normalize_text(args.get("query")).lower()
    limit = _positive_int(args.get("limit"), default=10, maximum=25)
    library = read_library(library_path) if library_path is not None else read_library()
    notes_source = [note for note in library.get("notes", []) if isinstance(note, dict)]
    if not query or query in {"*", "all"}:
        sorted_notes = sorted(
            notes_source,
            key=lambda note: (
                str(note.get("date") or ""),
                str(note.get("title") or "").lower(),
            ),
            reverse=True,
        )
        notes = [_note_summary(note) for note in sorted_notes[:limit]]
        return {
            "query": query,
            "mode": "list",
            "total": len(notes_source),
            "count": len(notes),
            "notes": notes,
        }

    scored_notes = []
    for note in notes_source:
        score = _note_score(note, query)
        if score > 0:
            scored_notes.append((score, note))

    scored_notes.sort(key=lambda item: (-item[0], str(item[1].get("title") or "").lower()))
    notes = [_note_summary(note) for _, note in scored_notes[:limit]]
    return {
        "query": query,
        "count": len(notes),
        "notes": notes,
    }


def get_note(args: dict[str, Any], *, library_path: Path | None = None) -> dict[str, Any]:
    note_id = normalize_text(args.get("note_id") or args.get("id"))
    if not note_id:
        return {"error": "note_id is required"}

    library = read_library(library_path) if library_path is not None else read_library()
    note = find_note(library, note_id)
    if note is None:
        return {"error": f"Note not found: {note_id}"}
    return {"note": _note_detail(note, library)}


def read_annotations_tool(args: dict[str, Any], *, annotations_dir: Path | None = None) -> dict[str, Any]:
    note_id = normalize_text(args.get("note_id") or args.get("id"))
    if not note_id:
        return {"error": "note_id is required"}

    payload = (
        read_note_annotations(note_id, annotations_dir)
        if annotations_dir is not None
        else read_note_annotations(note_id)
    )
    if payload is None:
        return {"error": "note_id is required"}
    annotations = payload.get("annotations") if isinstance(payload, dict) else []
    return {
        "note_id": note_id,
        "annotations": annotations if isinstance(annotations, list) else [],
    }


def read_note_html(
    args: dict[str, Any],
    *,
    library_path: Path | None = None,
    html_dir: Path | None = None,
) -> dict[str, Any]:
    note_result = _resolve_note(args, library_path=library_path)
    if "error" in note_result:
        return note_result
    note = note_result["note"]
    html_path = _note_html_path(note, html_dir=html_dir)
    if html_path is None:
        return _tool_error("note_html_missing", "Note has no local HTML path.", note_id=note["id"])
    try:
        document = html_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return _tool_error("note_html_not_found", f"HTML note file was not found: {html_path.name}", note_id=note["id"])

    mode = normalize_text(args.get("mode") or "body").lower()
    if mode not in {"body", "full"}:
        return _tool_error("invalid_mode", "mode must be body or full.", note_id=note["id"])
    if mode == "body":
        match = _note_body_match(document)
        if match is None:
            return _tool_error("note_body_missing", "HTML note does not contain a .note-body element.", note_id=note["id"])
        content = match.group("body").strip()
    else:
        content = document
    return {
        "success": True,
        "note_id": note["id"],
        "mode": mode,
        "html": content,
        "chars": len(content),
    }


def list_note_sections(
    args: dict[str, Any],
    *,
    library_path: Path | None = None,
    html_dir: Path | None = None,
) -> dict[str, Any]:
    payload = read_note_html({**args, "mode": "body"}, library_path=library_path, html_dir=html_dir)
    if not payload.get("success"):
        return payload
    sections = _collect_headings(str(payload.get("html") or ""))
    return {
        "success": True,
        "note_id": payload["note_id"],
        "count": len(sections),
        "sections": sections,
    }


def search_paper_text(
    args: dict[str, Any],
    *,
    library_path: Path | None = None,
    papers_dir: Path | None = None,
    paper_text_cache_dir: Path | None = None,
) -> dict[str, Any]:
    note_result = _resolve_note(args, library_path=library_path)
    if "error" in note_result:
        return note_result
    note = note_result["note"]
    query = normalize_text(args.get("query"))
    if not query:
        return _tool_error("query_required", "query is required", note_id=note["id"])
    pages_payload = _load_or_extract_paper_text(
        note,
        papers_dir=papers_dir,
        paper_text_cache_dir=paper_text_cache_dir,
    )
    if not pages_payload.get("success"):
        return pages_payload
    limit = _positive_int(args.get("limit"), default=5, maximum=10)
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
    note_result = _resolve_note(args, library_path=library_path)
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
    page_start = _positive_int(args.get("page_start"), default=1, maximum=max(len(pages), 1))
    page_end = _positive_int(args.get("page_end"), default=len(pages) or 1, maximum=max(len(pages), 1))
    if page_end < page_start:
        page_start, page_end = page_end, page_start
    selected = [
        page for page in pages
        if page_start <= int(page.get("page") or 0) <= page_end
    ]
    max_chars = _positive_int(args.get("max_chars"), default=12_000, maximum=20_000)
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
    note_result = _resolve_note(args, library_path=library_path)
    if "error" in note_result:
        return note_result
    note = note_result["note"]
    pdf_path = _resolved_pdf_path_for_note(note, papers_dir=papers_dir)
    if "error" in pdf_path:
        return pdf_path

    page_number = _positive_int(args.get("page"), default=1, maximum=100_000)
    scale = _positive_float(args.get("scale"), default=2.0, minimum=0.5, maximum=4.0)
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
    note_result = _resolve_note(args, library_path=library_path)
    if "error" in note_result:
        return note_result
    note = note_result["note"]
    pdf_path = _resolved_pdf_path_for_note(note, papers_dir=papers_dir)
    if "error" in pdf_path:
        return pdf_path

    limit = _positive_int(args.get("limit"), default=20, maximum=50)
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


def build_note_context(
    args: dict[str, Any],
    *,
    library_path: Path | None = None,
    annotations_dir: Path | None = None,
    html_dir: Path | None = None,
    papers_dir: Path | None = None,
    paper_text_cache_dir: Path | None = None,
) -> dict[str, Any]:
    note_result = get_note(args, library_path=library_path)
    if "error" in note_result:
        return note_result
    note = note_result["note"]
    sections_payload = list_note_sections(args, library_path=library_path, html_dir=html_dir)
    annotations_payload = read_annotations_tool(args, annotations_dir=annotations_dir)
    query = normalize_text(args.get("query"))
    paper_matches: list[dict[str, Any]] = []
    if query:
        max_matches = _positive_int(args.get("max_paper_matches"), default=5, maximum=8)
        paper_payload = search_paper_text(
            {**args, "query": query, "limit": max_matches},
            library_path=library_path,
            papers_dir=papers_dir,
            paper_text_cache_dir=paper_text_cache_dir,
        )
        if paper_payload.get("success"):
            paper_matches = paper_payload.get("matches", [])
    return {
        "success": True,
        "note_id": note["id"],
        "note": note,
        "sections": sections_payload.get("sections", []) if sections_payload.get("success") else [],
        "annotations": annotations_payload.get("annotations", []) if not annotations_payload.get("error") else [],
        "paper_matches": paper_matches,
    }


def validate_note_html(
    args: dict[str, Any],
    *,
    library_path: Path | None = None,
    html_dir: Path | None = None,
) -> dict[str, Any]:
    note_result = _resolve_note(args, library_path=library_path)
    if "error" in note_result:
        return note_result
    note = note_result["note"]
    html_path = _note_html_path(note, html_dir=html_dir)
    if html_path is None:
        return _tool_error("note_html_missing", "Note has no local HTML path.", note_id=note["id"])
    try:
        document = html_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return _tool_error("note_html_not_found", f"HTML note file was not found: {html_path.name}", note_id=note["id"])
    issues = _validate_html_document(document)
    match = _note_body_match(document)
    body = match.group("body") if match else ""
    sections = _collect_headings(body)
    return {
        "success": True,
        "valid": not issues,
        "note_id": note["id"],
        "issues": issues,
        "section_count": len(sections),
        "body_chars": len(body),
        "path": str(html_path),
    }


def preview_note_diff(
    args: dict[str, Any],
    *,
    library_path: Path | None = None,
    html_dir: Path | None = None,
) -> dict[str, Any]:
    note_result = _resolve_note(args, library_path=library_path)
    if "error" in note_result:
        return note_result
    note = note_result["note"]
    html_path = _note_html_path(note, html_dir=html_dir)
    if html_path is None:
        return _tool_error("note_html_missing", "Note has no local HTML path.", note_id=note["id"])
    try:
        document = html_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return _tool_error("note_html_not_found", f"HTML note file was not found: {html_path.name}", note_id=note["id"])
    match = _note_body_match(document)
    if match is None:
        return _tool_error("note_body_missing", "HTML note does not contain a .note-body element.", note_id=note["id"])
    heading = normalize_text(args.get("heading"))
    raw_html = str(args.get("html") or "")
    position = normalize_text(args.get("position") or "append").lower()
    if position not in {"append", "prepend", "after_heading", "replace_heading"}:
        return _tool_error("invalid_position", "position must be append, prepend, after_heading, or replace_heading.", note_id=note["id"])
    fragment = _section_fragment(heading=heading, raw_html=raw_html)
    if not fragment:
        return _tool_error("empty_html", "html must contain safe note content.", note_id=note["id"])
    current_body = match.group("body").strip()
    next_body, changed = _apply_body_update(current_body, fragment=fragment, heading=heading, position=position)
    if not changed:
        return _tool_error("heading_not_found", f"Could not find heading: {heading}", note_id=note["id"])
    before_headings = _collect_headings(current_body)
    after_headings = _collect_headings(next_body)
    return {
        "success": True,
        "changed": next_body != current_body,
        "note_id": note["id"],
        "position": position,
        "path": str(html_path),
        "before": {
            "section_count": len(before_headings),
            "body_chars": len(current_body),
        },
        "after": {
            "section_count": len(after_headings),
            "body_chars": len(next_body),
        },
        "added_headings": _added_heading_names(before_headings, after_headings),
        "summary": _diff_summary(current_body, next_body),
        "snapshot_id": "",
    }


def write_note_from_paper_image(
    args: dict[str, Any],
    *,
    library_path: Path | None = None,
    html_dir: Path | None = None,
    papers_dir: Path | None = None,
    paper_page_cache_dir: Path | None = None,
    media_store: Any | None = None,
    paper_image_analyzer: Any | None = None,
) -> dict[str, Any]:
    note_result = _resolve_note(args, library_path=library_path)
    if "error" in note_result:
        return note_result
    note = note_result["note"]
    note_id = normalize_text(note.get("id"))
    heading = normalize_text(args.get("heading"))
    if not heading:
        return _tool_error("heading_required", "heading is required.", note_id=note_id)
    position = normalize_text(args.get("position") or "append").lower()
    if position not in {"append", "prepend", "after_heading", "replace_heading"}:
        return _tool_error("invalid_position", "position must be append, prepend, after_heading, or replace_heading.", note_id=note_id)
    if not callable(paper_image_analyzer):
        return _tool_error("image_analysis_unavailable", "Image analysis is not available in this registry.", note_id=note_id)

    image_payload = _resolve_workflow_image(
        args,
        note_id=note_id,
        library_path=library_path,
        papers_dir=papers_dir,
        paper_page_cache_dir=paper_page_cache_dir,
        media_store=media_store,
    )
    if not image_payload.get("success"):
        return image_payload

    question = _paper_image_note_question(
        heading=heading,
        user_question=normalize_text(args.get("question")),
    )
    analysis_payload = paper_image_analyzer({
        "artifact_id": image_payload.get("artifact_id"),
        "question": question,
    })
    if not isinstance(analysis_payload, dict):
        return _tool_error("image_analysis_failed", "Image analysis returned an invalid result.", note_id=note_id)
    if analysis_payload.get("success") is False or analysis_payload.get("error"):
        return {
            **_tool_error(
                str(analysis_payload.get("code") or "image_analysis_failed"),
                str(analysis_payload.get("error") or "Image analysis failed."),
                note_id=note_id,
            ),
            "image": image_payload,
            "analysis": analysis_payload,
        }

    analysis_text = str(analysis_payload.get("analysis") or analysis_payload.get("content") or "").strip()
    html_fragment = _analysis_to_note_html(analysis_text)
    if not html_fragment:
        return _tool_error("empty_image_analysis", "Image analysis did not produce note content.", note_id=note_id)

    write_args = {
        "note_id": note_id,
        "heading": heading,
        "html": html_fragment,
        "position": position,
    }
    preview = preview_note_diff(write_args, library_path=library_path, html_dir=html_dir)
    if not preview.get("success"):
        return {
            **_tool_error(str(preview.get("code") or "preview_failed"), str(preview.get("error") or "Preview failed."), note_id=note_id),
            "image": image_payload,
            "analysis": _limit_text(analysis_text, 4_000),
            "preview": preview,
        }

    write = write_note_section(write_args, library_path=library_path, html_dir=html_dir)
    if not write.get("success"):
        return {
            **_tool_error(str(write.get("code") or "write_failed"), str(write.get("error") or "Write failed."), note_id=note_id),
            "image": image_payload,
            "analysis": _limit_text(analysis_text, 4_000),
            "preview": preview,
            "write": write,
        }

    validation = validate_note_html({"note_id": note_id}, library_path=library_path, html_dir=html_dir)
    return {
        "success": bool(validation.get("success") and validation.get("valid") is not False),
        "changed": bool(write.get("changed")),
        "note_id": note_id,
        "heading": heading,
        "position": position,
        "message": "Analyzed paper image and updated the note section.",
        "image": image_payload,
        "analysis": _limit_text(analysis_text, 4_000),
        "preview": {
            "changed": bool(preview.get("changed")),
            "before": preview.get("before") or {},
            "after": preview.get("after") or {},
            "added_headings": preview.get("added_headings") or [],
            "summary": preview.get("summary") or "",
        },
        "write": {
            "changed": bool(write.get("changed")),
            "before": write.get("before") or {},
            "after": write.get("after") or {},
            "message": write.get("message") or "",
        },
        "validation": validation,
    }


def write_note_section(
    args: dict[str, Any],
    *,
    library_path: Path | None = None,
    html_dir: Path | None = None,
    media_store: Any | None = None,
) -> dict[str, Any]:
    args, media_error = _resolve_media_source_args(args, media_store)
    if media_error:
        return media_error
    note_result = _resolve_note(args, library_path=library_path)
    if "error" in note_result:
        return note_result
    note = note_result["note"]
    html_path = _note_html_path(note, html_dir=html_dir)
    if html_path is None:
        return _tool_error("note_html_missing", "Note has no local HTML path.", note_id=note["id"])
    try:
        document = html_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return _tool_error("note_html_not_found", f"HTML note file was not found: {html_path.name}", note_id=note["id"])

    match = _note_body_match(document)
    if match is None:
        return _tool_error("note_body_missing", "HTML note does not contain a .note-body element.", note_id=note["id"])

    heading = normalize_text(args.get("heading"))
    raw_html = str(args.get("html") or "")
    position = normalize_text(args.get("position") or "append").lower()
    if position not in {"append", "prepend", "after_heading", "replace_heading"}:
        return _tool_error("invalid_position", "position must be append, prepend, after_heading, or replace_heading.", note_id=note["id"])

    fragment = _section_fragment(heading=heading, raw_html=raw_html)
    if not fragment:
        return _tool_error("empty_html", "html must contain safe note content.", note_id=note["id"])

    current_body = match.group("body").strip()
    before = {
        "section_count": len(_collect_headings(current_body)),
        "body_chars": len(current_body),
    }
    next_body, changed = _apply_body_update(current_body, fragment=fragment, heading=heading, position=position)
    if not changed:
        return _tool_error("heading_not_found", f"Could not find heading: {heading}", note_id=note["id"])

    next_document = document[:match.start("body")] + _with_surrounding_newlines(next_body) + document[match.end("body"):]
    atomic_write_text(html_path, next_document)
    return {
        "success": True,
        "changed": next_document != document,
        "note_id": note["id"],
        "message": f"Updated HTML note section using {position}.",
        "section_count": len(_collect_headings(next_body)),
        "html_chars": len(next_document),
        "before": before,
        "after": {
            "section_count": len(_collect_headings(next_body)),
            "body_chars": len(next_body),
        },
    }


def append_note_section(
    args: dict[str, Any],
    *,
    library_path: Path | None = None,
    html_dir: Path | None = None,
    media_store: Any | None = None,
) -> dict[str, Any]:
    return write_note_section({**args, "position": "append"}, library_path=library_path, html_dir=html_dir, media_store=media_store)


def replace_note_section(
    args: dict[str, Any],
    *,
    library_path: Path | None = None,
    html_dir: Path | None = None,
    media_store: Any | None = None,
) -> dict[str, Any]:
    return write_note_section({**args, "position": "replace_heading"}, library_path=library_path, html_dir=html_dir, media_store=media_store)


def delete_note_section(
    args: dict[str, Any],
    *,
    library_path: Path | None = None,
    html_dir: Path | None = None,
) -> dict[str, Any]:
    note_result = _resolve_note(args, library_path=library_path)
    if "error" in note_result:
        return note_result
    note = note_result["note"]
    html_path = _note_html_path(note, html_dir=html_dir)
    if html_path is None:
        return _tool_error("note_html_missing", "Note has no local HTML path.", note_id=note["id"])
    heading = normalize_text(args.get("heading"))
    if not heading:
        return _tool_error("heading_required", "heading is required.", note_id=note["id"])
    try:
        document = html_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return _tool_error("note_html_not_found", f"HTML note file was not found: {html_path.name}", note_id=note["id"])

    match = _note_body_match(document)
    if match is None:
        return _tool_error("note_body_missing", "HTML note does not contain a .note-body element.", note_id=note["id"])

    current_body = match.group("body").strip()
    before = {
        "section_count": len(_collect_headings(current_body)),
        "body_chars": len(current_body),
    }
    next_body, changed = _delete_heading_section(current_body, heading)
    if not changed:
        return _tool_error("heading_not_found", f"Could not find heading: {heading}", note_id=note["id"])

    next_document = document[:match.start("body")] + _with_surrounding_newlines(next_body) + document[match.end("body"):]
    atomic_write_text(html_path, next_document)
    return {
        "success": True,
        "changed": next_document != document,
        "note_id": note["id"],
        "heading": heading,
        "message": "Deleted HTML note section.",
        "section_count": len(_collect_headings(next_body)),
        "html_chars": len(next_document),
        "before": before,
        "after": {
            "section_count": len(_collect_headings(next_body)),
            "body_chars": len(next_body),
        },
    }


def insert_note_image(
    args: dict[str, Any],
    *,
    library_path: Path | None = None,
    html_dir: Path | None = None,
    media_store: Any | None = None,
) -> dict[str, Any]:
    note_result = _resolve_note(args, library_path=library_path)
    if "error" in note_result:
        return note_result
    note = note_result["note"]
    html_path = _note_html_path(note, html_dir=html_dir)
    if html_path is None:
        return _tool_error("note_html_missing", "Note has no local HTML path.", note_id=note["id"])
    if media_store is None:
        return _tool_error("media_store_unavailable", "Media store is not available.", note_id=note["id"])

    artifact_ref = normalize_text(args.get("artifact_id"))
    if not artifact_ref:
        return _tool_error("artifact_id_required", "artifact_id is required.", note_id=note["id"])
    artifact = _resolve_image_artifact_payload(media_store, artifact_ref)
    if not artifact or not normalize_text(artifact.get("url")):
        return _tool_error("image_artifact_not_found", f"Image artifact was not found: {artifact_ref}", note_id=note["id"])
    if normalize_text(artifact.get("kind") or "image") != "image":
        return _tool_error("image_artifact_required", "insert_image requires an image artifact.", note_id=note["id"], artifact_id=artifact_ref)
    artifact_id = normalize_text(artifact.get("id") or artifact_ref)

    try:
        document = html_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return _tool_error("note_html_not_found", f"HTML note file was not found: {html_path.name}", note_id=note["id"])

    match = _note_body_match(document)
    if match is None:
        return _tool_error("note_body_missing", "HTML note does not contain a .note-body element.", note_id=note["id"])

    heading = normalize_text(args.get("heading"))
    position = normalize_text(args.get("position") or ("after_heading" if heading else "append")).lower()
    if position not in {"append", "prepend", "after_heading", "replace_heading"}:
        return _tool_error("invalid_position", "position must be append, prepend, after_heading, or replace_heading.", note_id=note["id"])

    figure_html = _image_figure_html(
        artifact=artifact,
        caption=normalize_text(args.get("caption")),
        alt=normalize_text(args.get("alt")),
    )
    current_body = match.group("body").strip()
    before = {
        "section_count": len(_collect_headings(current_body)),
        "body_chars": len(current_body),
    }
    next_body, changed = _apply_body_update(
        current_body,
        fragment=figure_html,
        heading=heading,
        position=position,
    )
    if not changed:
        return _tool_error("heading_not_found", f"Could not find heading: {heading}", note_id=note["id"])

    next_document = document[:match.start("body")] + _with_surrounding_newlines(next_body) + document[match.end("body"):]
    atomic_write_text(html_path, next_document)
    return {
        "success": True,
        "changed": next_document != document,
        "note_id": note["id"],
        "heading": heading,
        "artifact_id": artifact_id,
        "message": "Inserted image into HTML note.",
        "image": artifact,
        "before": before,
        "after": {
            "section_count": len(_collect_headings(next_body)),
            "body_chars": len(next_body),
        },
    }


def update_note_metadata(args: dict[str, Any], *, library_path: Path | None = None) -> dict[str, Any]:
    note_id = normalize_text(args.get("note_id") or args.get("id"))
    if not note_id:
        return _tool_error("note_id_required", "note_id is required")

    allowed_input_keys = {
        "note_id",
        "id",
        "summary",
        "tags",
        "venue",
        "date",
        "category_id",
        "categoryId",
        "collection",
        "collection_name",
        "collectionName",
        "collection_path",
        "collectionPath",
    }
    unknown = sorted(key for key in args if key not in allowed_input_keys)
    if unknown:
        return _tool_error("unknown_metadata_fields", f"Unsupported metadata fields: {', '.join(unknown)}", note_id=note_id)

    path = library_path if library_path is not None else None
    library = read_library(path) if path is not None else read_library()
    note = find_note(library, note_id)
    if note is None:
        return _tool_error("note_not_found", f"Note not found: {note_id}", note_id=note_id)

    before = _note_detail(note, library)
    updates: dict[str, Any] = {}
    if "summary" in args:
        updates["summary"] = normalize_text(args.get("summary"))
    if "tags" in args:
        raw_tags = args.get("tags")
        if isinstance(raw_tags, str):
            raw_tags = [tag for tag in re.split(r"[,，]", raw_tags)]
        updates["tags"] = normalize_tags(raw_tags)
    if "venue" in args:
        updates["venue"] = normalize_text(args.get("venue"))
    if "date" in args:
        updates["date"] = normalize_text(args.get("date"))
    if "category_id" in args or "categoryId" in args:
        updates["categoryId"] = normalize_text(args.get("category_id") or args.get("categoryId"))
    collection_value = normalize_text(
        args.get("collection")
        or args.get("collection_name")
        or args.get("collectionName")
        or args.get("collection_path")
        or args.get("collectionPath")
    )
    if collection_value:
        resolved_category_id = _resolve_collection_id(library, collection_value)
        if not resolved_category_id:
            return _tool_error("collection_not_found", f"Collection not found: {collection_value}", note_id=note_id)
        updates["categoryId"] = resolved_category_id

    if not updates:
        return _tool_error("no_metadata_updates", "Provide at least one metadata field to update.", note_id=note_id)

    note.update(updates)
    saved = write_library(library, path) if path is not None else write_library(library)
    after_note = find_note(saved, note_id) or note
    return {
        "success": True,
        "changed": before != _note_detail(after_note, saved),
        "note_id": note_id,
        "message": "Updated note metadata.",
        "before": before,
        "after": _note_detail(after_note, saved),
    }


def create_annotation(
    args: dict[str, Any],
    *,
    library_path: Path | None = None,
    annotations_dir: Path | None = None,
    papers_dir: Path | None = None,
) -> dict[str, Any]:
    note_id = normalize_text(args.get("note_id") or args.get("id"))
    if not note_id:
        return _tool_error("note_id_required", "note_id is required")
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
        return _tool_error("annotation_exists", f"Annotation already exists: {annotation_id}", note_id=note_id)
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
        return _tool_error("note_id_required", "note_id is required")
    if not annotation_id:
        return _tool_error("annotation_id_required", "annotation_id is required", note_id=note_id)

    annotations = _read_annotation_list(note_id, annotations_dir=annotations_dir)
    annotation = next(
        (entry for entry in annotations if isinstance(entry, dict) and normalize_text(entry.get("id")) == annotation_id),
        None,
    )
    if annotation is None:
        return _tool_error("annotation_not_found", f"Annotation not found: {annotation_id}", note_id=note_id)

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
        return _tool_error("note_id_required", "note_id is required")
    if not annotation_id:
        return _tool_error("annotation_id_required", "annotation_id is required", note_id=note_id)

    annotations = _read_annotation_list(note_id, annotations_dir=annotations_dir)
    index = next(
        (idx for idx, entry in enumerate(annotations) if isinstance(entry, dict) and normalize_text(entry.get("id")) == annotation_id),
        -1,
    )
    if index < 0:
        return _tool_error("annotation_not_found", f"Annotation not found: {annotation_id}", note_id=note_id)
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
        return _tool_error("invalid_annotation_type", f"annotation_type must be one of: {', '.join(sorted(ANNOTATION_TYPES))}")
    if args.get("page") is None:
        return _tool_error("page_required", "page is required for annotation changes.")
    page = _positive_int(args.get("page"), default=1, maximum=100_000)
    rects_payload = _annotation_rects_from_args(args, require_geometry=require_geometry)
    if "error" in rects_payload:
        return rects_payload
    rects = rects_payload["rects"]
    bounds = _annotation_bounds(rects) if rects else {"x": 0, "y": 0, "w": 0, "h": 0}
    color = normalize_text(args.get("color") or "yellow").lower()
    if color not in ANNOTATION_COLORS:
        return _tool_error("invalid_color", f"color must be one of: {', '.join(sorted(ANNOTATION_COLORS))}")
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
    note_result = _resolve_note(args, library_path=library_path)
    if "error" in note_result:
        return note_result
    note = note_result["note"]
    note_id = normalize_text(note.get("id"))
    target_text = normalize_text(args.get("query") or args.get("quote"))
    if not target_text:
        return _tool_error("annotation_target_required", "Provide quote/query or normalized coordinates for create_annotation.", note_id=note_id)
    pdf_path = _resolved_pdf_path_for_note(note, papers_dir=papers_dir)
    if "error" in pdf_path:
        return pdf_path
    page_hint = args.get("page")
    page_number = _positive_int(page_hint, default=0, maximum=100_000) if page_hint is not None else 0
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
                return _tool_error("page_out_of_range", f"page must be between 1 and {page_count}.", note_id=note_id, page_count=page_count)
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
                        "source_pdf": _relative_project_path(pdf_path),
                    }
        finally:
            document.close()
    except Exception as error:
        return _tool_error("annotation_locate_failed", f"Could not locate annotation text: {type(error).__name__}: {error}", note_id=note_id)
    scope = f" on page {page_number}" if page_number else ""
    return _tool_error("annotation_target_not_found", f"Could not find quote/query in PDF{scope}: {target_text}", note_id=note_id)


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
            return _tool_error("invalid_annotation_type", f"annotation_type must be one of: {', '.join(sorted(ANNOTATION_TYPES))}")
        update["type"] = annotation_type
    if "page" in args:
        page = _positive_int(args.get("page"), default=0, maximum=100_000)
        if page < 1:
            return _tool_error("invalid_page", "page must be a positive integer.")
        update["page"] = page
    if "comment" in args:
        update["comment"] = normalize_text(args.get("comment"))
    if "quote" in args:
        update["quote"] = normalize_text(args.get("quote"))
    if "color" in args:
        color = normalize_text(args.get("color")).lower()
        if color not in ANNOTATION_COLORS:
            return _tool_error("invalid_color", f"color must be one of: {', '.join(sorted(ANNOTATION_COLORS))}")
        update["color"] = color
    if any(key in args for key in ("x", "y", "w", "h", "rects")):
        rects_payload = _annotation_rects_from_args(args, require_geometry=True)
        if "error" in rects_payload:
            return rects_payload
        rects = rects_payload["rects"]
        bounds = _annotation_bounds(rects)
        update.update({"x": bounds["x"], "y": bounds["y"], "w": bounds["w"], "h": bounds["h"], "rects": rects})
    if not update:
        return _tool_error("no_annotation_updates", "Provide at least one annotation field to update.")
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
                return _tool_error("invalid_rects", "rects must contain normalized x, y, w, h values between 0 and 1.")
            rects.append(rect)
    elif any(key in args for key in ("x", "y", "w", "h")):
        rect = _normalize_annotation_rect(args)
        if rect is None:
            return _tool_error("invalid_geometry", "x, y, w, and h must be normalized values between 0 and 1.")
        rects.append(rect)
    if require_geometry and not rects:
        return _tool_error("geometry_required", "Provide rects or normalized x, y, w, h for create_annotation.")
    return {"rects": rects}


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


def _resolve_workflow_image(
    args: dict[str, Any],
    *,
    note_id: str,
    library_path: Path | None = None,
    papers_dir: Path | None = None,
    paper_page_cache_dir: Path | None = None,
    media_store: Any | None = None,
) -> dict[str, Any]:
    artifact_id = normalize_text(args.get("artifact_id") or args.get("artifactId"))
    if artifact_id:
        artifact_payload = _artifact_payload(media_store, artifact_id)
        return {
            "success": True,
            "source": "artifact",
            "artifact_id": artifact_id,
            "artifact": artifact_payload,
        }

    if args.get("page") is None:
        return _tool_error(
            "image_source_required",
            "Provide artifact_id or page so the workflow knows which image to analyze.",
            note_id=note_id,
        )

    page = _positive_int(args.get("page"), default=1, maximum=100_000)
    scale = _positive_float(args.get("scale"), default=2.0, minimum=0.5, maximum=4.0)
    rendered = render_paper_page(
        {"note_id": note_id, "page": page, "scale": scale},
        library_path=library_path,
        papers_dir=papers_dir,
        paper_page_cache_dir=paper_page_cache_dir,
        media_store=media_store,
    )
    if not rendered.get("success"):
        return rendered
    rendered_artifact_id = normalize_text(rendered.get("artifact_id"))
    if not rendered_artifact_id:
        return _tool_error(
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
        "artifact_id": rendered_artifact_id,
        "artifact": rendered.get("artifact") or _artifact_payload(media_store, rendered_artifact_id),
        "rendered": {
            "width": rendered.get("width"),
            "height": rendered.get("height"),
            "relative_path": rendered.get("relative_path") or "",
            "preview_url": rendered.get("preview_url") or "",
            "download_url": rendered.get("download_url") or "",
        },
    }


def _artifact_payload(media_store: Any | None, artifact_id: str) -> dict[str, Any]:
    if media_store is None:
        return {"id": artifact_id}
    public_artifact = getattr(media_store, "public_artifact", None)
    if callable(public_artifact):
        try:
            payload = public_artifact(artifact_id)
        except Exception:
            return {"id": artifact_id}
        return payload if isinstance(payload, dict) else {"id": artifact_id}
    return {"id": artifact_id}


def _resolve_image_artifact_payload(media_store: Any | None, artifact_ref: str) -> dict[str, Any]:
    ref = normalize_text(artifact_ref)
    if not ref:
        return {}

    direct = _artifact_payload(media_store, ref)
    if normalize_text(direct.get("url")) and normalize_text(direct.get("kind") or "image") == "image":
        return direct

    candidate_paths = _candidate_media_paths(ref, media_store)
    find_by_path = getattr(media_store, "find_by_path", None)
    if callable(find_by_path):
        for candidate in candidate_paths:
            try:
                artifact = find_by_path(candidate)
            except Exception:
                artifact = None
            payload = _artifact_to_payload(artifact)
            if normalize_text(payload.get("url")) and normalize_text(payload.get("kind") or "image") == "image":
                return payload

    public_artifact = getattr(media_store, "public_artifact", None)
    if callable(public_artifact):
        for artifact_id in _candidate_artifact_ids(ref):
            try:
                payload = public_artifact(artifact_id)
            except Exception:
                payload = {}
            if (
                isinstance(payload, dict)
                and normalize_text(payload.get("url"))
                and normalize_text(payload.get("kind") or "image") == "image"
            ):
                return payload
    return {}


def _candidate_artifact_ids(ref: str) -> list[str]:
    candidates = [ref]
    parsed = urlparse(ref)
    raw_path = unquote(parsed.path if parsed.scheme == "file" else ref)
    path = Path(raw_path)
    if path.name:
        candidates.append(path.stem)
        candidates.append(path.name)
    seen: set[str] = set()
    result: list[str] = []
    for candidate in candidates:
        normalized = normalize_text(candidate)
        if normalized and normalized not in seen:
            result.append(normalized)
            seen.add(normalized)
    return result


def _candidate_media_paths(ref: str, media_store: Any | None) -> list[Path]:
    parsed = urlparse(ref)
    if parsed.scheme and parsed.scheme != "file":
        return []
    raw_path = unquote(parsed.path if parsed.scheme == "file" else ref)
    path = Path(raw_path).expanduser()
    candidates: list[Path] = []
    if path.is_absolute():
        candidates.append(path.resolve())
    else:
        candidates.append((PROJECT_ROOT / path).resolve())
        root = getattr(media_store, "root", None)
        if root is not None:
            media_root = Path(root).resolve()
            candidates.append((media_root / path).resolve())
            if path.parts and path.parts[0] not in {"generated", "uploads"}:
                candidates.append((media_root / "generated" / path).resolve())
                candidates.append((media_root / "uploads" / path).resolve())
    seen: set[str] = set()
    result: list[Path] = []
    for candidate in candidates:
        key = str(candidate)
        if key not in seen:
            result.append(candidate)
            seen.add(key)
    return result


def _paper_image_note_question(*, heading: str, user_question: str) -> str:
    focus = user_question or "Identify the main claim, visual evidence, important numbers, axes, labels, and caveats."
    return (
        "You are helping write a local paper note from a paper image. "
        "Analyze only what is visible in the image and avoid inventing missing details. "
        "Return concise safe HTML for the body of a note section, without markdown fences and without a top-level heading. "
        "Use only p, ul, ol, li, blockquote, code, pre, table, thead, tbody, tr, th, td, a, strong, and em tags. "
        f"Target section heading: {heading}. "
        f"Writing focus: {focus}"
    )


def _analysis_to_note_html(analysis_text: str) -> str:
    raw = _strip_markdown_fence(str(analysis_text or "").strip())
    if not raw:
        return ""
    if _looks_like_allowed_html(raw):
        return _sanitize_html_fragment(raw)
    return _sanitize_html_fragment(_plain_text_to_note_html(raw))


def _strip_markdown_fence(value: str) -> str:
    stripped = value.strip()
    stripped = re.sub(r"(?is)^```(?:html)?\s*", "", stripped)
    stripped = re.sub(r"(?is)\s*```\s*$", "", stripped)
    return stripped.strip()


def _looks_like_allowed_html(value: str) -> bool:
    return re.search(
        r"(?is)<\s*(?:a|blockquote|code|em|h[2-4]|li|ol|p|pre|strong|table|tbody|td|th|thead|tr|ul)\b",
        value,
    ) is not None


def _plain_text_to_note_html(value: str) -> str:
    parts: list[str] = []
    paragraph_lines: list[str] = []
    bullet_lines: list[str] = []

    def flush_paragraph() -> None:
        if paragraph_lines:
            text = normalize_text(" ".join(paragraph_lines))
            if text:
                parts.append(f"<p>{html_lib.escape(text)}</p>")
            paragraph_lines.clear()

    def flush_bullets() -> None:
        if bullet_lines:
            items = "".join(f"<li>{html_lib.escape(item)}</li>" for item in bullet_lines if item)
            if items:
                parts.append(f"<ul>{items}</ul>")
            bullet_lines.clear()

    for raw_line in value.splitlines():
        line = normalize_text(raw_line)
        if not line:
            flush_paragraph()
            flush_bullets()
            continue
        bullet_match = re.match(r"^[-*]\s+(.+)$", line)
        if bullet_match:
            flush_paragraph()
            bullet_lines.append(normalize_text(bullet_match.group(1)))
            continue
        flush_bullets()
        paragraph_lines.append(line)

    flush_paragraph()
    flush_bullets()
    return "\n".join(parts)


def _limit_text(value: str, max_chars: int) -> str:
    text = str(value or "")
    limit = max(100, int(max_chars))
    if len(text) <= limit:
        return text
    return f"{text[:limit].rstrip()}...[truncated]"


def _attach_artifact(
    payload: dict[str, Any],
    *,
    media_store: Any | None,
    path_key: str,
    source: str,
    metadata: dict[str, Any],
) -> None:
    if media_store is None or not isinstance(payload, dict):
        return
    image_path = payload.get(path_key)
    if not image_path:
        return
    register_existing = getattr(media_store, "register_existing", None)
    if not callable(register_existing):
        return
    try:
        artifact = register_existing(
            image_path,
            source=source,
            metadata={key: value for key, value in metadata.items() if value is not None and value != ""},
        )
    except Exception:
        return
    to_dict = getattr(artifact, "to_dict", None)
    artifact_payload = to_dict() if callable(to_dict) else dict(artifact)
    payload["artifact"] = artifact_payload
    payload["artifact_id"] = artifact_payload.get("id", "")
    payload["preview_url"] = artifact_payload.get("url", "")
    payload["download_url"] = artifact_payload.get("downloadUrl", "")


def _load_or_extract_paper_text(
    note: dict[str, Any],
    *,
    papers_dir: Path | None = None,
    paper_text_cache_dir: Path | None = None,
) -> dict[str, Any]:
    note_id = normalize_text(note.get("id"))
    if not note_id:
        return _tool_error("note_id_required", "note_id is required")
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
        return _tool_error("paper_pdf_missing", "Note has no local PDF path.", note_id=note_id)
    if not pdf_path.exists():
        return _tool_error("paper_pdf_not_found", f"PDF file was not found: {pdf_path.name}", note_id=note_id)
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
            page_number = _positive_int(raw_page.get("page"), default=index, maximum=100_000)
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
        return _tool_error("pdf_text_extract_failed", f"Could not extract PDF text: {type(error).__name__}: {error}")
    return {"success": True, "pages": [page for page in pages if page["text"]]}


def _resolved_pdf_path_for_note(note: dict[str, Any], *, papers_dir: Path | None = None) -> dict[str, Any]:
    note_id = normalize_text(note.get("id"))
    if not note_id:
        return _tool_error("note_id_required", "note_id is required")
    pdf_path = _note_pdf_path(note, papers_dir=papers_dir)
    if pdf_path is None:
        return _tool_error("paper_pdf_missing", "Note has no local PDF path.", note_id=note_id)
    if not pdf_path.exists():
        return _tool_error("paper_pdf_not_found", f"PDF file was not found: {pdf_path.name}", note_id=note_id)
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
                return _tool_error(
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
        return _tool_error(
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
        "relative_path": _relative_project_path(output_path),
        "width": width,
        "height": height,
        "source_pdf": _relative_project_path(pdf_path),
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
                        "relative_path": _relative_project_path(output_path),
                        "width": int(extracted.get("width") or 0),
                        "height": int(extracted.get("height") or 0),
                        "ext": ext,
                        "cached": cached,
                    })
        finally:
            document.close()
    except Exception as error:
        return _tool_error(
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
        "source_pdf": _relative_project_path(pdf_path),
        "limit": limit,
    }


def _import_pymupdf() -> Any:
    try:
        import pymupdf  # type: ignore[import-not-found]
    except Exception as error:
        return _tool_error(
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


def _validate_html_document(document: str) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    match = _note_body_match(document)
    if match is None:
        issues.append({"code": "note_body_missing", "message": "HTML note does not contain .note-body."})
        content_to_validate = document
    else:
        content_to_validate = match.group("body")
    dangerous_patterns = {
        "script_tag": r"(?is)<\s*script\b",
        "style_tag": r"(?is)<\s*style\b",
        "event_handler": r"(?is)\son[a-z]+\s*=",
        "javascript_href": r"(?is)href\s*=\s*['\"]\s*javascript:",
        "data_href": r"(?is)href\s*=\s*['\"]\s*data:",
    }
    for code, pattern in dangerous_patterns.items():
        if re.search(pattern, content_to_validate):
            issues.append({"code": code, "message": f"Unsafe HTML pattern detected: {code}."})
    return issues


def _added_heading_names(before: list[dict[str, Any]], after: list[dict[str, Any]]) -> list[str]:
    before_names = {normalize_text(item.get("heading")).casefold() for item in before}
    return [
        normalize_text(item.get("heading"))
        for item in after
        if normalize_text(item.get("heading")).casefold() not in before_names
    ]


def _diff_summary(before: str, after: str) -> str:
    delta = len(after) - len(before)
    if delta == 0:
        return "No text-length change."
    direction = "Added" if delta > 0 else "Removed"
    return f"{direction} {abs(delta)} HTML body characters."


def _safe_cache_name(value: str) -> str:
    candidate = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._-")
    return candidate or "note"


def _note_score(note: dict[str, Any], query: str) -> int:
    score = 0
    title = str(note.get("title") or "").lower()
    summary = str(note.get("summary") or "").lower()
    venue = str(note.get("venue") or "").lower()
    date = str(note.get("date") or "").lower()
    tags = " ".join(str(tag).lower() for tag in note.get("tags", []) if tag)
    haystack = {
        "title": title,
        "tags": tags,
        "summary": summary,
        "venue": venue,
        "date": date,
    }

    if query in title:
        score += 10
    if query in tags:
        score += 6
    if query in summary:
        score += 4
    if query in venue:
        score += 2
    if query in date:
        score += 1
    terms = [
        term for term in re.findall(r"[\w\u4e00-\u9fff]+", query.casefold())
        if term and len(term) > 1
    ]
    for term in terms:
        if term in title:
            score += 5
        if term in tags:
            score += 3
        if term in summary:
            score += 2
        if term in venue or term in date:
            score += 1
    if terms and all(any(term in value for value in haystack.values()) for term in terms):
        score += 2
    return score


def _note_summary(note: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": note.get("id", ""),
        "title": note.get("title", ""),
        "summary": note.get("summary", ""),
        "venue": note.get("venue", ""),
        "date": note.get("date", ""),
        "tags": note.get("tags", []),
        "categoryId": note.get("categoryId", ""),
        "href": note.get("href", ""),
        "htmlHref": note.get("htmlHref", ""),
    }


def _note_detail(note: dict[str, Any], library: dict[str, Any] | None = None) -> dict[str, Any]:
    collection = _collection_metadata(library, note.get("categoryId", "")) if library else {}
    return {
        "id": note.get("id", ""),
        "title": note.get("title", ""),
        "summary": note.get("summary", ""),
        "venue": note.get("venue", ""),
        "date": note.get("date", ""),
        "tags": note.get("tags", []),
        "categoryId": note.get("categoryId", ""),
        **collection,
        "href": note.get("href", ""),
        "htmlHref": note.get("htmlHref", ""),
        "pdfStorageKey": note.get("pdfStorageKey", ""),
    }


def _collection_metadata(library: dict[str, Any] | None, category_id: Any) -> dict[str, str]:
    category = _category_by_id(library, normalize_text(category_id))
    if not category:
        return {"collectionName": "", "collectionPath": ""}
    return {
        "collectionName": normalize_text(category.get("name")),
        "collectionPath": _collection_path(library, normalize_text(category.get("id"))),
    }


def _resolve_collection_id(library: dict[str, Any], value: str) -> str:
    target = _normalize_collection_lookup(value)
    if not target:
        return ""
    for category in _leaf_categories(library):
        if normalize_text(category.get("id")) == value:
            return normalize_text(category.get("id"))
    exact_matches = [
        normalize_text(category.get("id"))
        for category in _leaf_categories(library)
        if _normalize_collection_lookup(category.get("name")) == target
        or _normalize_collection_lookup(_collection_path(library, category.get("id"))) == target
    ]
    return exact_matches[0] if len(exact_matches) == 1 else ""


def _collection_path(library: dict[str, Any] | None, category_id: Any) -> str:
    category = _category_by_id(library, normalize_text(category_id))
    if not category:
        return ""
    parent_id = normalize_text(category.get("parentId"))
    if not parent_id:
        return normalize_text(category.get("name"))
    parent = _category_by_id(library, parent_id)
    return f"{normalize_text(parent.get('name'))} / {normalize_text(category.get('name'))}" if parent else normalize_text(category.get("name"))


def _category_by_id(library: dict[str, Any] | None, category_id: str) -> dict[str, Any] | None:
    if not library or not category_id:
        return None
    return next((category for category in library.get("categories", []) if category.get("id") == category_id), None)


def _leaf_categories(library: dict[str, Any]) -> list[dict[str, Any]]:
    categories = [category for category in library.get("categories", []) if isinstance(category, dict)]
    parent_ids = {normalize_text(category.get("parentId")) for category in categories if normalize_text(category.get("parentId"))}
    return [category for category in categories if normalize_text(category.get("id")) not in parent_ids]


def _normalize_collection_lookup(value: Any) -> str:
    return re.sub(r"\s*/\s*", "/", normalize_text(value).lower())


def _positive_int(value: Any, *, default: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return min(max(parsed, 1), maximum)


def _positive_float(value: Any, *, default: float, minimum: float, maximum: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return min(max(parsed, minimum), maximum)


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


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _page_range_from_args(page_start: Any, page_end: Any, *, page_count: int) -> tuple[int, int]:
    max_page = max(page_count, 1)
    start = _positive_int(page_start, default=1, maximum=max_page)
    end = _positive_int(page_end, default=max_page, maximum=max_page)
    if end < start:
        start, end = end, start
    return start, end


def _safe_image_ext(value: str) -> str:
    normalized = normalize_text(value).lower().lstrip(".")
    if normalized in {"png", "jpg", "jpeg", "webp", "bmp", "tif", "tiff"}:
        return normalized
    return "png"


def _relative_project_path(path: Path) -> str:
    resolved = Path(path).resolve()
    project_root = PROJECT_ROOT.resolve()
    if is_relative_to(resolved, project_root):
        return str(resolved.relative_to(project_root))
    return str(resolved)


def _resolve_note(args: dict[str, Any], *, library_path: Path | None = None) -> dict[str, Any]:
    note_id = normalize_text(args.get("note_id") or args.get("id"))
    if not note_id:
        return _tool_error("note_id_required", "note_id is required")
    library = read_library(library_path) if library_path is not None else read_library()
    note = find_note(library, note_id)
    if note is None:
        return _tool_error("note_not_found", f"Note not found: {note_id}", note_id=note_id)
    return {"note": note}


def _note_html_path(note: dict[str, Any], *, html_dir: Path | None = None) -> Path | None:
    html_href = normalize_text(note.get("htmlHref"))
    if not html_href:
        return None
    base_dir = (html_dir or HTML_DIR).resolve()
    raw_path = Path(unquote(html_href))
    if raw_path.is_absolute():
        html_path = raw_path.resolve()
    elif html_dir is not None:
        parts = raw_path.parts
        if "Paper-html" in parts:
            rel_path = Path(*parts[parts.index("Paper-html") + 1:])
        else:
            rel_path = raw_path
        html_path = (base_dir / rel_path).resolve()
    else:
        html_path = (PROJECT_ROOT / raw_path).resolve()
    if not is_relative_to(html_path, base_dir):
        return None
    return html_path


def _note_body_match(document: str) -> re.Match[str] | None:
    return _NOTE_BODY_RE.search(document)


def _section_fragment(*, heading: str, raw_html: str) -> str:
    sanitized = _sanitize_html_fragment(raw_html)
    if not sanitized:
        return ""
    if _starts_with_heading(sanitized):
        return _ensure_heading_ids(sanitized)
    if not heading:
        return _ensure_heading_ids(sanitized)
    return _ensure_heading_ids(f"<h2>{html_lib.escape(heading)}</h2>\n{sanitized}")


def _image_figure_html(*, artifact: dict[str, Any], caption: str, alt: str) -> str:
    src = normalize_text(artifact.get("url"))
    if not src:
        src = f"/api/media/{html_lib.escape(normalize_text(artifact.get('id')), quote=True)}"
    rendered_alt = alt or normalize_text(artifact.get("fileName")) or "Generated note image"
    attrs = [
        f'src="{html_lib.escape(src, quote=True)}"',
        f'alt="{html_lib.escape(rendered_alt, quote=True)}"',
        'loading="lazy"',
    ]
    width = _positive_int(artifact.get("width"), default=0, maximum=100_000)
    height = _positive_int(artifact.get("height"), default=0, maximum=100_000)
    if width:
        attrs.append(f'width="{width}"')
    if height:
        attrs.append(f'height="{height}"')
    parts = [
        '<figure class="note-figure">',
        f"<img {' '.join(attrs)}>",
    ]
    if caption:
        parts.append(f"<figcaption>{html_lib.escape(caption, quote=False)}</figcaption>")
    parts.append("</figure>")
    return "\n".join(parts)


def _with_resolved_media_sources(args: dict[str, Any], media_store: Any | None) -> dict[str, Any]:
    resolved_args, _ = _resolve_media_source_args(args, media_store)
    return resolved_args


def _resolve_media_source_args(args: dict[str, Any], media_store: Any | None) -> tuple[dict[str, Any], dict[str, Any] | None]:
    raw_html = str(args.get("html") or "")
    if not raw_html:
        return args, None
    if media_store is None:
        if _html_has_local_image_source(raw_html):
            return args, _tool_error(
                "media_store_unavailable",
                "Image paths in note HTML require the media store so they can be converted to /api/media URLs.",
                note_id=normalize_text(args.get("note_id")),
            )
        return args, None
    rewritten, unresolved = _rewrite_media_image_sources(raw_html, media_store)
    if unresolved:
        return args, _tool_error(
            "image_source_unresolved",
            "Could not resolve one or more local image paths to registered media artifacts. Use insert_image with artifact_id.",
            note_id=normalize_text(args.get("note_id")),
            unresolved_sources=unresolved[:5],
        )
    if rewritten == raw_html:
        return args, None
    return {**args, "html": rewritten}, None


def _rewrite_media_image_sources(raw_html: str, media_store: Any) -> tuple[str, list[str]]:
    unresolved: list[str] = []

    def replace(match: re.Match[str]) -> str:
        prefix = match.group("prefix")
        quote = match.group("quote")
        src = html_lib.unescape(match.group("src"))
        resolved = _media_url_for_image_source(src, media_store)
        if not resolved and not _safe_src(src):
            unresolved.append(src)
        return f"{prefix}{quote}{html_lib.escape(resolved or src, quote=True)}{quote}"

    rewritten = re.sub(
        r"(?is)(?P<prefix><img\b[^>]*?\bsrc\s*=\s*)(?P<quote>['\"])(?P<src>.*?)(?P=quote)",
        replace,
        raw_html,
    )
    return rewritten, unresolved


def _html_has_local_image_source(raw_html: str) -> bool:
    for match in re.finditer(r"(?is)<img\b[^>]*?\bsrc\s*=\s*(['\"])(.*?)\1", raw_html or ""):
        src = html_lib.unescape(match.group(2))
        if src and not _safe_src(src):
            return True
    return False


def _media_url_for_image_source(src: str, media_store: Any) -> str:
    value = normalize_text(src)
    if not value or _safe_src(value):
        return value

    parsed = urlparse(value)
    if parsed.scheme and parsed.scheme != "file":
        return ""
    raw_path = unquote(parsed.path if parsed.scheme == "file" else value)
    candidate = Path(raw_path).expanduser()
    if not candidate.is_absolute():
        candidate = (PROJECT_ROOT / candidate).resolve()
    else:
        candidate = candidate.resolve()

    root = getattr(media_store, "root", None)
    try:
        media_root = Path(root).resolve() if root is not None else None
    except OSError:
        media_root = None
    if media_root is not None and not is_relative_to(candidate, media_root):
        return ""

    find_by_path = getattr(media_store, "find_by_path", None)
    if callable(find_by_path):
        try:
            artifact = find_by_path(candidate)
        except Exception:
            artifact = None
        payload = _artifact_to_payload(artifact)
        if normalize_text(payload.get("kind") or "image") == "image" and normalize_text(payload.get("url")):
            return normalize_text(payload.get("url"))

    public_artifact = getattr(media_store, "public_artifact", None)
    if callable(public_artifact):
        artifact_id = candidate.stem
        try:
            payload = public_artifact(artifact_id)
        except Exception:
            payload = {}
        if (
            isinstance(payload, dict)
            and normalize_text(payload.get("kind") or "image") == "image"
            and normalize_text(payload.get("url"))
        ):
            return normalize_text(payload.get("url"))
    return ""


def _artifact_to_payload(artifact: Any) -> dict[str, Any]:
    if artifact is None:
        return {}
    to_dict = getattr(artifact, "to_dict", None)
    if callable(to_dict):
        payload = to_dict()
        return payload if isinstance(payload, dict) else {}
    return artifact if isinstance(artifact, dict) else {}


def _starts_with_heading(fragment: str) -> bool:
    return re.match(r"(?is)^\s*<h[2-4]\b", fragment) is not None


def _apply_body_update(
    current_body: str,
    *,
    fragment: str,
    heading: str,
    position: str,
) -> tuple[str, bool]:
    if position == "append":
        existing = _find_heading_section(current_body, heading)
        if heading and existing is not None:
            _start, end = existing
            return _join_fragments(current_body[:end].strip(), _fragment_without_leading_matching_heading(fragment, heading), current_body[end:].strip()), True
        return _join_fragments(current_body, fragment), True
    if position == "prepend":
        return _join_fragments(fragment, current_body), True

    target = _find_heading_section(current_body, heading)
    if target is None:
        return current_body, False
    start, end = target
    if position == "replace_heading":
        return _join_fragments(current_body[:start].strip(), fragment, current_body[end:].strip()), True
    if position == "after_heading":
        return _join_fragments(current_body[:end].strip(), fragment, current_body[end:].strip()), True
    return current_body, False


def _delete_heading_section(current_body: str, heading: str) -> tuple[str, bool]:
    target = _find_heading_section(current_body, heading)
    if target is None:
        return current_body, False
    start, end = target
    return _join_fragments(current_body[:start].strip(), current_body[end:].strip()), True


def _fragment_without_leading_matching_heading(fragment: str, heading: str) -> str:
    normalized_heading = normalize_text(heading).casefold()
    if not normalized_heading:
        return fragment
    match = _HEADING_RE.match(fragment.strip())
    if match is None:
        return fragment
    text = normalize_text(_strip_html(match.group(2))).casefold()
    if text != normalized_heading:
        return fragment
    return fragment.strip()[match.end():].strip()


def _find_heading_section(body: str, heading: str) -> tuple[int, int] | None:
    normalized_heading = normalize_text(heading).casefold()
    if not normalized_heading:
        return None
    matches = list(_HEADING_RE.finditer(body))
    for index, match in enumerate(matches):
        text = normalize_text(_strip_html(match.group(2))).casefold()
        if text != normalized_heading:
            continue
        level = int(match.group(1))
        end = len(body)
        for later in matches[index + 1:]:
            if int(later.group(1)) <= level:
                end = later.start()
                break
        return match.start(), end
    return None


def _join_fragments(*fragments: str) -> str:
    return "\n\n".join(fragment.strip() for fragment in fragments if fragment and fragment.strip())


def _with_surrounding_newlines(body: str) -> str:
    return f"\n{body.strip()}\n" if body.strip() else ""


def _strip_html(value: str) -> str:
    return re.sub(r"<[^>]+>", "", html_lib.unescape(value or ""))


def _ensure_heading_ids(fragment: str) -> str:
    used_ids = set()
    for match in _HEADING_WITH_ATTRS_RE.finditer(fragment):
        existing_id = _extract_id(match.group(2))
        if existing_id:
            used_ids.add(existing_id)

    def replace(match: re.Match[str]) -> str:
        level = match.group(1)
        attrs = match.group(2)
        body = match.group(3)
        if _extract_id(attrs):
            return match.group(0)
        heading_id = _unique_heading_id(_heading_id_from_text(_strip_html(body)), used_ids)
        return f'<h{level} id="{html_lib.escape(heading_id, quote=True)}"{attrs}>{body}</h{level}>'

    return _HEADING_WITH_ATTRS_RE.sub(replace, fragment)


def _extract_id(attrs: str) -> str:
    match = re.search(r"""\bid\s*=\s*["']([^"']+)["']""", attrs or "", re.IGNORECASE)
    return normalize_text(match.group(1)) if match else ""


def _heading_id_from_text(text: str) -> str:
    candidate = re.sub(r"\s+", "-", normalize_text(text).casefold())
    candidate = re.sub(r"[^a-z0-9\u4e00-\u9fff._-]+", "", candidate, flags=re.IGNORECASE).strip("-._")
    return candidate or "section"


def _unique_heading_id(candidate: str, used_ids: set[str]) -> str:
    heading_id = candidate
    suffix = 2
    while heading_id in used_ids:
        heading_id = f"{candidate}-{suffix}"
        suffix += 1
    used_ids.add(heading_id)
    return heading_id


def _collect_headings(body: str) -> list[dict[str, Any]]:
    parser = _HeadingCollector()
    parser.feed(body or "")
    parser.close()
    return parser.headings


def _sanitize_html_fragment(raw_html: str) -> str:
    parser = _SafeHTMLFragmentParser()
    parser.feed(str(raw_html or ""))
    parser.close()
    return parser.rendered.strip()


def _tool_error(code: str, message: str, **extra: Any) -> dict[str, Any]:
    return {"success": False, "error": message, "code": code, **extra}


class _SafeHTMLFragmentParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.parts: list[str] = []
        self._skip_depth = 0

    @property
    def rendered(self) -> str:
        return "".join(self.parts)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "iframe", "object", "embed"}:
            self._skip_depth += 1
            return
        if self._skip_depth or tag not in SAFE_HTML_TAGS:
            return
        rendered_attrs = self._safe_attrs(tag, attrs)
        suffix = f" {rendered_attrs}" if rendered_attrs else ""
        self.parts.append(f"<{tag}{suffix}>")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "iframe", "object", "embed"} and self._skip_depth:
            self._skip_depth -= 1
            return
        if self._skip_depth or tag not in SAFE_HTML_TAGS:
            return
        self.parts.append(f"</{tag}>")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self.parts.append(html_lib.escape(data, quote=False))

    def handle_entityref(self, name: str) -> None:
        if not self._skip_depth:
            self.parts.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        if not self._skip_depth:
            self.parts.append(f"&#{name};")

    @staticmethod
    def _safe_attrs(tag: str, attrs: list[tuple[str, str | None]]) -> str:
        allowed = SAFE_ATTRS_BY_TAG.get(tag, set())
        rendered: list[str] = []
        for raw_name, raw_value in attrs:
            name = raw_name.lower()
            if name not in allowed:
                continue
            value = normalize_text(raw_value)
            if name == "href" and not _safe_href(value):
                continue
            if name == "src" and not _safe_src(value):
                continue
            if name == "class" and value != "note-figure":
                continue
            if name == "loading" and value not in {"lazy", "eager"}:
                continue
            if name in {"width", "height"} and (not value.isdigit() or int(value) <= 0):
                continue
            if name in {"colspan", "rowspan"} and not value.isdigit():
                continue
            rendered.append(f'{name}="{html_lib.escape(value, quote=True)}"')
        return " ".join(rendered)


def _safe_href(value: str) -> bool:
    if not value:
        return False
    lowered = value.lower()
    return (
        lowered.startswith(("https://", "http://", "mailto:", "#", "/", "resources/"))
        and not lowered.startswith(("javascript:", "data:", "file:"))
    )


def _safe_src(value: str) -> bool:
    if not value:
        return False
    lowered = value.lower()
    return (
        lowered.startswith(("/api/media/", "resources/", "https://", "http://"))
        and not lowered.startswith(("javascript:", "data:", "file:"))
    )


class _HeadingCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.headings: list[dict[str, Any]] = []
        self._current: dict[str, Any] | None = None
        self._chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag not in {"h2", "h3", "h4"}:
            return
        attr_map = {name.lower(): value for name, value in attrs if value is not None}
        self._current = {
            "level": int(tag[1]),
            "id": normalize_text(attr_map.get("id")),
        }
        self._chunks = []

    def handle_endtag(self, tag: str) -> None:
        if self._current is None or tag.lower() not in {"h2", "h3", "h4"}:
            return
        text = normalize_text(html_lib.unescape("".join(self._chunks)))
        self.headings.append({**self._current, "heading": text})
        self._current = None
        self._chunks = []

    def handle_data(self, data: str) -> None:
        if self._current is not None:
            self._chunks.append(data)

    def handle_entityref(self, name: str) -> None:
        if self._current is not None:
            self._chunks.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        if self._current is not None:
            self._chunks.append(f"&#{name};")
