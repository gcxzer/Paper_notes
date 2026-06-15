from __future__ import annotations

# JSON schemas for the public Paper Notes facade tools.

from typing import Any


def get_paper_context_parameters() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "note_id": {
                "type": "string",
                "description": "Specific note id to inspect. When provided, returns detailed paper/note context.",
            },
            "query": {
                "type": "string",
                "description": (
                    "Optional concise metadata search keywords. This searches library metadata, not PDF content. "
                    "Prefer English paper terms and common acronyms; "
                    "preserve important original-language terms for multilingual queries. Use '*' or omit this "
                    "only to list/count local papers when note_id is not provided."
                ),
            },
            "limit": {
                "type": "integer",
                "minimum": 1,
                "maximum": 25,
                "description": "Maximum notes to return.",
            },
            "include_html": {"type": "boolean", "description": "Include current note HTML body when true."},
            "html_mode": {"type": "string", "enum": ["body", "full"], "description": "HTML read mode."},
        },
        "required": [],
        "additionalProperties": False,
    }


def inspect_paper_visuals_parameters() -> dict[str, Any]:
    properties: dict[str, Any] = {
        "action": {
            "type": "string",
            "enum": ["render_page", "extract_images"],
        },
        "note_id": {"type": "string", "description": "The note id whose PDF visuals should be inspected."},
        "page": {"type": "integer", "minimum": 1, "description": "Page number for render_page."},
        "page_start": {"type": "integer", "minimum": 1},
        "page_end": {"type": "integer", "minimum": 1},
        "limit": {"type": "integer", "minimum": 1, "maximum": 50},
        "scale": {"type": "number", "minimum": 0.5, "maximum": 4},
    }
    return {
        "type": "object",
        "properties": properties,
        "required": ["note_id"],
        "additionalProperties": False,
    }


def query_paper_content_parameters() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "note_id": {"type": "string", "description": "The note id whose indexed PDF content should be queried."},
            "query": {
                "type": "string",
                "description": (
                    "One short, precise retrieval query for the paper's actual PDF content. Prefer exact "
                    "labels and keywords over expanded natural-language questions. For numbered references "
                    "(figures, tables, equations, algorithms, appendices, or sections), preserve the reference "
                    "label as a hard constraint and do not dilute it with broad explanatory wording. Add only "
                    "1-5 disambiguating paper keywords when the user supplied them or they are known from "
                    "current context. In paper context, generic wording such as picture/image/visual plus a "
                    "number usually means the numbered paper figure; query it as Figure N, not extracted "
                    "image index N, unless the user explicitly asks for an extracted image file/index. For "
                    "conceptual questions, use compact paper terminology rather than a full sentence. "
                    "Few-shot examples: user 'what does Figure 3 show?' -> query 'Figure 3'; user 'what is "
                    "picture 8 in the paper?' -> query 'Figure 8'; user 'results in Table 2' -> query "
                    "'Table 2'; user 'what does Equation (4) mean?' -> query 'Equation 4'; user 'difference "
                    "between active reconstruction and passive retrieval' -> query 'active reconstruction "
                    "passive retrieval memory graph'; user 'LoCoMo experiment results compared with baselines' "
                    "-> query 'LoCoMo LongMemEval MRAgent baselines results'."
                ),
            },
        },
        "required": ["note_id", "query"],
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
            "position": {
                "type": "string",
                "enum": ["append", "prepend", "after_heading", "replace_heading"],
                "description": (
                    "Optional section placement for HTML writes. Use prepend for the top of the note, "
                    "append for the end or existing section append, after_heading to insert after heading, "
                    "and replace_heading only for explicit replacement."
                ),
            },
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
            "annotation_id": {
                "type": "string",
                "description": "Annotation id for update/delete, or optional id for create.",
            },
            "annotation_type": {"type": "string", "enum": ["highlight", "underline", "area", "note"]},
            "comment": {"type": "string", "description": "Annotation comment."},
            "quote": {"type": "string", "description": "Quoted PDF text for create/update annotation."},
            "query": {
                "type": "string",
                "description": "PDF text to locate when creating an annotation without explicit coordinates.",
            },
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
    properties: dict[str, Any] = {
        "action": {"type": "string", "enum": ["insert_image"]},
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
                "Do not use Desktop/Downloads/arbitrary local paths; ask the user to move/copy local images "
                "into .paper-notes/media or a subfolder first."
            ),
        },
        "caption": {"type": "string", "description": "Figure caption for insert_image."},
        "alt": {"type": "string", "description": "Image alt text for insert_image."},
    }
    return {
        "type": "object",
        "properties": properties,
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
