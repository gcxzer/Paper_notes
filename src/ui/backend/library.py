from __future__ import annotations

import base64
import copy
import json
from pathlib import Path
from typing import Any

from backend.core import (
    finite_number,
    get_today_label,
    normalize_text,
    note_id_from_title,
    note_title_from_pdf,
    resource_href,
    safe_file_name,
)
from backend.note_html import create_paper_note_html, update_note_html_title
from backend.paths import HTML_DIR, HTML_HREF_PREFIX, NOTES_PATH, PAPERS_DIR, PAPERS_HREF_PREFIX
from backend.storage import atomic_write_json, atomic_write_text


ALL_CATEGORY_ID = "all"
UNCATEGORIZED_ID = "uncategorized"

BASE_LIBRARY = {
    "categories": [
        {"id": ALL_CATEGORY_ID, "name": "All Notes", "parentId": None, "order": 0, "system": True},
        {"id": UNCATEGORIZED_ID, "name": "Uncategorized", "parentId": None, "order": 1, "system": True},
    ],
    "notes": [],
}


def normalize_tags(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [tag for tag in (normalize_text(item) for item in value) if tag]


def normalize_resource_href(value: Any) -> str:
    href = normalize_text(value)
    if not href:
        return ""
    if href.startswith("resources/"):
        return href
    if href.startswith(("Papers/", "Paper-html/", "Paper-annotations/")):
        return f"resources/{href}"
    return href


def sanitize_library(raw_library: Any) -> dict[str, Any]:
    raw = raw_library if isinstance(raw_library, dict) else {}
    raw_categories = raw.get("categories") if isinstance(raw.get("categories"), list) else []
    category_map: dict[str, dict[str, Any]] = {}

    for index, category in enumerate(raw_categories):
        if not isinstance(category, dict):
            continue
        category_id = normalize_text(category.get("id"))
        if not category_id or category_id in category_map:
            continue
        category_map[category_id] = {
            "id": category_id,
            "name": normalize_text(category.get("name")) or "Untitled",
            "parentId": normalize_text(category.get("parentId")) or None,
            "order": finite_number(category.get("order"), index),
            "system": bool(category.get("system")),
        }

    for category in BASE_LIBRARY["categories"]:
        category_map[category["id"]] = dict(category)

    categories = []
    for category in category_map.values():
        if category["id"] == ALL_CATEGORY_ID:
            categories.append({**category, "parentId": None, "order": 0, "system": True})
        elif category["id"] == UNCATEGORIZED_ID:
            categories.append({**category, "parentId": None, "order": 1, "system": True})
        else:
            categories.append(category)

    valid_ids = {category["id"] for category in categories}
    for category in categories:
        if category.get("parentId") and category["parentId"] not in valid_ids:
            category["parentId"] = None
        if category.get("parentId") in {ALL_CATEGORY_ID, UNCATEGORIZED_ID}:
            category["parentId"] = None

    top_level_ids = {category["id"] for category in categories if category.get("parentId") is None}
    for category in categories:
        if category.get("parentId") and category["parentId"] not in top_level_ids:
            category["parentId"] = None

    child_map: dict[str, list[dict[str, Any]]] = {}
    for category in categories:
        key = category.get("parentId") or "root"
        child_map.setdefault(key, []).append(category)

    for group in child_map.values():
        group.sort(key=lambda category: (category.get("order", 0), category.get("name", "")))
        for index, category in enumerate(group):
            if category.get("parentId") is None:
                if category["id"] == ALL_CATEGORY_ID:
                    category["order"] = 0
                elif category["id"] == UNCATEGORIZED_ID:
                    category["order"] = 1
                else:
                    category["order"] = max(index, 2)
            else:
                category["order"] = index

    parent_ids_with_children = {category["parentId"] for category in categories if category.get("parentId")}
    leaf_ids = {category["id"] for category in categories if category["id"] not in parent_ids_with_children}

    raw_notes = raw.get("notes") if isinstance(raw.get("notes"), list) else []
    notes = []
    for index, note in enumerate(raw_notes):
        if not isinstance(note, dict):
            continue
        requested_category_id = normalize_text(note.get("categoryId"))
        notes.append(
            {
                "id": normalize_text(note.get("id")) or note_id_from_title(note.get("title") or f"note-{index + 1}"),
                "title": normalize_text(note.get("title")) or "Untitled Note",
                "href": normalize_resource_href(note.get("href")),
                "htmlHref": normalize_resource_href(note.get("htmlHref")),
                "pdfStorageKey": normalize_text(note.get("pdfStorageKey")),
                "date": normalize_text(note.get("date")),
                "order": finite_number(note.get("order"), index),
                "categoryId": requested_category_id if requested_category_id in leaf_ids else UNCATEGORIZED_ID,
                "venue": normalize_text(note.get("venue")),
                "summary": normalize_text(note.get("summary")),
                "tags": normalize_tags(note.get("tags")),
            }
        )

    return {"categories": categories, "notes": notes}


def read_library(path: Path = NOTES_PATH) -> dict[str, Any]:
    try:
        return sanitize_library(json.loads(path.read_text(encoding="utf-8")))
    except Exception:
        return copy.deepcopy(BASE_LIBRARY)


def write_library(library: dict[str, Any], path: Path = NOTES_PATH) -> dict[str, Any]:
    sanitized = sanitize_library(library)
    atomic_write_json(path, sanitized)
    return sanitized


def find_note(library: dict[str, Any], note_id: str) -> dict[str, Any] | None:
    return next((entry for entry in library.get("notes", []) if entry.get("id") == note_id), None)


def import_pdf(body: dict[str, Any]) -> dict[str, Any]:
    original_name = safe_file_name(body.get("fileName"))
    if not original_name.lower().endswith(".pdf"):
        raise ValueError("Only PDF files can be imported.")

    try:
        pdf_data = base64.b64decode(str(body.get("dataBase64") or ""), validate=False)
    except Exception:
        pdf_data = b""
    if not pdf_data:
        raise ValueError("PDF file is empty.")

    PAPERS_DIR.mkdir(parents=True, exist_ok=True)
    HTML_DIR.mkdir(parents=True, exist_ok=True)

    html_name = f"{Path(original_name).stem}.html"
    title = note_title_from_pdf(original_name)
    date = get_today_label()
    pdf_href = resource_href(PAPERS_HREF_PREFIX, original_name)
    html_href = resource_href(HTML_HREF_PREFIX, html_name)
    library = read_library()
    library["categories"] = library.get("categories") if isinstance(library.get("categories"), list) else copy.deepcopy(BASE_LIBRARY["categories"])
    library["notes"] = library.get("notes") if isinstance(library.get("notes"), list) else []

    existing_notes = [entry for entry in library["notes"] if entry.get("href") != pdf_href and entry.get("htmlHref") != html_href]
    next_order = max((finite_number(note.get("order"), index) for index, note in enumerate(existing_notes)), default=-1) + 1
    note = {
        "id": note_id_from_title(title),
        "title": title,
        "href": pdf_href,
        "htmlHref": html_href,
        "pdfStorageKey": "",
        "date": date,
        "order": next_order,
        "categoryId": normalize_text(body.get("categoryId")) or UNCATEGORIZED_ID,
        "venue": "",
        "summary": "",
        "tags": [],
    }

    (PAPERS_DIR / original_name).write_bytes(pdf_data)
    atomic_write_text(HTML_DIR / html_name, create_paper_note_html(title, date, original_name))

    library["notes"] = [*existing_notes, note]
    write_library(library)
    return note


def rename_note(note_id: str, next_title: str) -> dict[str, Any] | None:
    library = read_library()
    note = find_note(library, note_id)
    if note is None:
        return None
    note["title"] = next_title
    write_library(library)
    update_note_html_title(note, next_title)
    return note


def update_note_summary(note_id: str, summary: str) -> dict[str, Any] | None:
    library = read_library()
    note = find_note(library, note_id)
    if note is None:
        return None
    note["summary"] = normalize_text(summary)
    write_library(library)
    return note
