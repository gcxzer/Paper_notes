from __future__ import annotations

import copy
import html
import json
import re
import time
from datetime import date
from pathlib import Path
from urllib.parse import quote, unquote

from . import config


BASE_LIBRARY = {
    "categories": [
        {"id": "all", "name": "All Notes", "parentId": None, "order": 0, "system": True},
        {"id": "uncategorized", "name": "Uncategorized", "parentId": None, "order": 1, "system": True},
    ],
    "notes": [],
}


def normalize_text(value: object) -> str:
    return str(value or "").strip()


def escape_html(value: object) -> str:
    return html.escape(str(value or ""), quote=True)


def _base36(value: int) -> str:
    alphabet = "0123456789abcdefghijklmnopqrstuvwxyz"
    if value <= 0:
        return "0"
    chars: list[str] = []
    while value:
        value, remainder = divmod(value, 36)
        chars.append(alphabet[remainder])
    return "".join(reversed(chars))


def get_today_label() -> str:
    return date.today().isoformat()


def safe_file_name(file_name: object) -> str:
    raw = normalize_text(file_name)
    leaf = re.split(r"[\\/]+", raw)[-1]
    suffix = Path(leaf).suffix.lower() or ".pdf"
    stem = Path(leaf).stem
    stem = re.sub(r"""[\\/:*?"<>|#%{}^~\[\]`]+""", "", stem)
    stem = re.sub(r"\s+", " ", stem).strip()
    return f"{stem or 'Untitled Paper'}{suffix}"


def note_title_from_pdf(file_name: str) -> str:
    title = Path(file_name).stem.replace("-", " ").replace("_", " ").strip()
    return title or "Untitled PDF"


def safe_annotation_id(note_id: object) -> str:
    safe_id = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff._-]+", "-", normalize_text(note_id))
    return safe_id.strip("-")


def annotation_path_for(note_id: object) -> Path | None:
    safe_id = safe_annotation_id(note_id)
    if not safe_id:
        return None
    return config.ANNOTATIONS_DIR / f"{safe_id}.json"


def note_id_from_title(title: object) -> str:
    slug = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff]+", "-", normalize_text(title).lower()).strip("-")[:80]
    now_ms = int(time.time() * 1000)
    return f"pdf-{slug or now_ms}-{_base36(now_ms)}"


def normalize_tags(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [tag for tag in (normalize_text(tag) for tag in value) if tag]


def sanitize_library(raw_library: object) -> dict:
    raw = raw_library if isinstance(raw_library, dict) else {}
    raw_categories = raw.get("categories") if isinstance(raw.get("categories"), list) else []
    category_map: dict[str, dict] = {}

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
            "order": float(category.get("order")) if _is_finite_number(category.get("order")) else index,
            "system": bool(category.get("system")),
        }

    for category in BASE_LIBRARY["categories"]:
        category_map[category["id"]] = copy.deepcopy(category)

    categories = []
    for category in category_map.values():
        if category["id"] == "all":
            category = {**category, "parentId": None, "order": 0, "system": True}
        elif category["id"] == "uncategorized":
            category = {**category, "parentId": None, "order": 1, "system": True}
        categories.append(category)

    valid_ids = {category["id"] for category in categories}
    for category in categories:
        if category.get("parentId") and category["parentId"] not in valid_ids:
            category["parentId"] = None
        if category.get("parentId") in {"all", "uncategorized"}:
            category["parentId"] = None

    top_level_ids = {category["id"] for category in categories if category.get("parentId") is None}
    for category in categories:
        if category.get("parentId") and category["parentId"] not in top_level_ids:
            category["parentId"] = None

    child_map: dict[str, list[dict]] = {}
    for category in categories:
        key = category.get("parentId") or "root"
        child_map.setdefault(key, []).append(category)

    for group in child_map.values():
        group.sort(key=lambda item: (item.get("order", 0), item.get("name", "")))
        for index, category in enumerate(group):
            if category.get("parentId") is None:
                if category["id"] == "all":
                    category["order"] = 0
                elif category["id"] == "uncategorized":
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
                "href": normalize_text(note.get("href")),
                "htmlHref": normalize_text(note.get("htmlHref")),
                "pdfStorageKey": normalize_text(note.get("pdfStorageKey")),
                "pdfS3Key": normalize_text(note.get("pdfS3Key")),
                "noteS3Key": normalize_text(note.get("noteS3Key")),
                "annotationS3Key": normalize_text(note.get("annotationS3Key")),
                "kbPaperS3Key": normalize_text(note.get("kbPaperS3Key")),
                "kbNoteS3Key": normalize_text(note.get("kbNoteS3Key")),
                "kbAnnotationsS3Key": normalize_text(note.get("kbAnnotationsS3Key")),
                "kbMetadataS3Key": normalize_text(note.get("kbMetadataS3Key")),
                "kbSyncStatus": normalize_text(note.get("kbSyncStatus")),
                "kbIngestionJobId": normalize_text(note.get("kbIngestionJobId")),
                "kbSyncError": normalize_text(note.get("kbSyncError")),
                "date": normalize_text(note.get("date")),
                "order": float(note.get("order")) if _is_finite_number(note.get("order")) else index,
                "categoryId": requested_category_id if requested_category_id in leaf_ids else "uncategorized",
                "venue": normalize_text(note.get("venue")),
                "summary": normalize_text(note.get("summary")),
                "tags": normalize_tags(note.get("tags")),
            }
        )

    return {"categories": categories, "notes": notes}


def _is_finite_number(value: object) -> bool:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return number == number and number not in (float("inf"), float("-inf"))


def create_paper_note_html(title: str, date_label: str, file_name: str, body_html: str = "") -> str:
    safe_title = escape_html(title)
    safe_date = escape_html(date_label)
    safe_file_name = escape_html(file_name)
    note_body = body_html or "<p>No extracted text is available yet.</p>"
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{safe_title}</title>
  <script src="../assets/scripts/theme.js"></script>
  <link rel="stylesheet" href="../assets/styles/note.css">
</head>
<body>
  <main class="note">
    <header class="note-section">
      <p class="eyebrow note-eyebrow">Paper Note</p>
      <h1>{safe_title}</h1>
      <p class="meta note-meta">{safe_date} · {safe_file_name}</p>
    </header>

    <div class="note-workspace">
      <aside class="note-menu" aria-label="Note sections">
        <nav data-note-menu></nav>
      </aside>

      <section class="note-body">
        {note_body}
      </section>
    </div>
  </main>
  <script src="../assets/scripts/note.js"></script>
</body>
</html>"""


def read_library() -> dict:
    try:
        return sanitize_library(json.loads(config.NOTES_PATH.read_text(encoding="utf-8")))
    except Exception:
        return copy.deepcopy(BASE_LIBRARY)


def write_library(library: object) -> dict:
    sanitized = sanitize_library(library)
    config.NOTES_PATH.write_text(f"{json.dumps(sanitized, ensure_ascii=False, indent=2)}\n", encoding="utf-8")
    return sanitized


def encoded_project_path(directory: str, file_name: str) -> str:
    return f"{directory}/{quote(file_name, safe='')}"


def project_path_from_href(href: str) -> Path:
    return (config.ROOT / unquote(href)).resolve(strict=False)


def is_within(path: Path, parent: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(parent.resolve(strict=False))
        return True
    except ValueError:
        return False


def create_annotations_markdown(note: dict, annotations: object) -> str:
    def safe_int(value: object, default: int = 1) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def safe_float(value: object) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    raw_annotations = annotations if isinstance(annotations, list) else []
    title = normalize_text(note.get("title")) or "Untitled Paper"
    date_label = normalize_text(note.get("date"))
    lines = [
        f"# Annotations for {title}",
        "",
        f"- Note ID: {normalize_text(note.get('id'))}",
    ]
    if date_label:
        lines.append(f"- Date: {date_label}")
    lines.append("")

    normalized = []
    for annotation in raw_annotations:
        if not isinstance(annotation, dict):
            continue
        comment = normalize_text(annotation.get("comment") or annotation.get("text"))
        quote_text = normalize_text(annotation.get("quote"))
        annotation_type = normalize_text(annotation.get("type")) or "annotation"
        page = safe_int(annotation.get("page") or 1)
        if not comment and not quote_text:
            continue
        normalized.append(
            {
                "page": page,
                "y": safe_float(annotation.get("y") or 0),
                "x": safe_float(annotation.get("x") or 0),
                "type": annotation_type,
                "quote": quote_text,
                "comment": comment,
                "createdAt": normalize_text(annotation.get("createdAt")),
            }
        )

    normalized.sort(key=lambda item: (item["page"], item["y"], item["x"], item["createdAt"]))
    if not normalized:
        lines.extend(["No annotations yet.", ""])
        return "\n".join(lines)

    current_page = None
    for annotation in normalized:
        if annotation["page"] != current_page:
            current_page = annotation["page"]
            lines.extend([f"## Page {current_page}", ""])
        lines.append(f"### {annotation['type'].title()}")
        if annotation["quote"]:
            lines.extend(["> " + annotation["quote"].replace("\n", "\n> "), ""])
        if annotation["comment"]:
            lines.extend([annotation["comment"], ""])
        if annotation["createdAt"]:
            lines.extend([f"_Created at: {annotation['createdAt']}_", ""])

    return "\n".join(lines).rstrip() + "\n"
