from __future__ import annotations

# JSON schemas for the public Paper Notes facade tools.

from typing import Any


def search_notes_parameters() -> dict[str, Any]:
    return {
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
                "minimum": 1,
                "maximum": 25,
                "description": "Maximum notes to return.",
            },
        },
        "required": [],
        "additionalProperties": False,
    }


def get_note_context_parameters() -> dict[str, Any]:
    return {
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
    }


def read_paper_parameters() -> dict[str, Any]:
    return {
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
    }


def write_note_parameters() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["write_section", "append_to_section", "delete_section", "update_metadata"],
                "description": (
                    "write_section replaces an existing section or creates it if missing. "
                    "append_to_section appends content to an existing section or creates it if missing."
                ),
            },
            "note_id": {"type": "string", "description": "The note id to modify."},
            "heading": {"type": "string", "description": "Section heading for HTML section changes."},
            "html": {"type": "string", "description": "Safe HTML fragment for section writes."},
            "summary": {"type": "string", "description": "Metadata summary update."},
            "tags": {"type": "array", "items": {"type": "string"}, "description": "Metadata tag update."},
            "venue": {"type": "string", "description": "Metadata venue update."},
            "date": {"type": "string", "description": "Metadata date update."},
            "category_id": {"type": "string", "description": "Metadata category id update."},
            "collection": {
                "type": "string",
                "description": "Metadata collection name or collection path. Resolved to category_id before saving.",
            },
        },
        "required": ["action", "note_id"],
        "additionalProperties": False,
    }


def manage_annotations_parameters() -> dict[str, Any]:
    rect_schema = {
        "type": "object",
        "properties": {
            "x": {"type": "number", "minimum": 0, "maximum": 1},
            "y": {"type": "number", "minimum": 0, "maximum": 1},
            "w": {"type": "number", "minimum": 0, "maximum": 1},
            "h": {"type": "number", "minimum": 0, "maximum": 1},
        },
        "required": ["x", "y", "w", "h"],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["create", "update", "delete"]},
            "note_id": {"type": "string", "description": "The note id whose annotation should change."},
            "annotation_id": {"type": "string", "description": "Annotation id for update/delete, or optional id for create."},
            "annotation_type": {"type": "string", "enum": ["highlight", "underline", "area", "note"]},
            "comment": {"type": "string", "description": "Annotation comment."},
            "quote": {"type": "string", "description": "Quoted PDF text for create/update annotation."},
            "query": {"type": "string", "description": "PDF text to locate when creating an annotation without explicit coordinates."},
            "color": {"type": "string", "enum": ["yellow", "green", "blue", "red", "purple"]},
            "page": {"type": "integer", "minimum": 1, "description": "PDF page for annotation create/update."},
            "x": {"type": "number", "minimum": 0, "maximum": 1},
            "y": {"type": "number", "minimum": 0, "maximum": 1},
            "w": {"type": "number", "minimum": 0, "maximum": 1},
            "h": {"type": "number", "minimum": 0, "maximum": 1},
            "rects": {
                "type": "array",
                "items": rect_schema,
                "description": "Normalized PDF page rectangles for create/update annotation.",
            },
        },
        "required": ["action", "note_id"],
        "additionalProperties": False,
    }


def write_note_media_parameters() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["write_from_image", "insert_image"]},
            "note_id": {"type": "string", "description": "The note id to modify."},
            "heading": {"type": "string", "description": "Heading to create, update, or insert the image near."},
            "position": {
                "type": "string",
                "enum": ["append", "prepend", "after_heading", "replace_heading"],
                "description": "Section or image placement.",
            },
            "artifact_id": {
                "type": "string",
                "description": (
                    "Image artifact id or a path anywhere under Paper_Notes/.paper-notes/media, including subfolders. "
                    "Do not use Desktop/Downloads/arbitrary local paths; ask the user to move/copy local images into .paper-notes/media or a subfolder first."
                ),
            },
            "page": {"type": "integer", "minimum": 1, "description": "PDF page for write_from_image."},
            "scale": {"type": "number", "minimum": 0.5, "maximum": 4},
            "question": {"type": "string", "description": "Image-analysis or writing focus for write_from_image."},
            "caption": {"type": "string", "description": "Figure caption for insert_image."},
            "alt": {"type": "string", "description": "Image alt text for insert_image."},
        },
        "required": ["action", "note_id"],
        "additionalProperties": False,
    }


def review_note_parameters() -> dict[str, Any]:
    return {
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
    }
