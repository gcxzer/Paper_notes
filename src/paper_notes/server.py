from __future__ import annotations

import base64
import copy
import html
import json
import mimetypes
import os
import re
import sys
import time
import uuid
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote, urlparse, parse_qs


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PUBLIC_DIR = PROJECT_ROOT / "src" / "public"
ASSETS_DIR = PROJECT_ROOT / "assets"
PORT = int(os.environ.get("PORT", "4173"))
HOST = "127.0.0.1"
MAX_BODY_SIZE = 200 * 1024 * 1024

RESOURCES_DIR = PROJECT_ROOT / "resources"
PAPERS_DIR = RESOURCES_DIR / "Papers"
HTML_DIR = RESOURCES_DIR / "Paper-html"
ANNOTATIONS_DIR = RESOURCES_DIR / "Paper-annotations"
NOTES_PATH = PROJECT_ROOT / "notes.json"
LOCAL_STATE_DIR = PROJECT_ROOT / ".paper-notes-local"
SESSIONS_DIR = LOCAL_STATE_DIR / "sessions"

PAPERS_HREF_PREFIX = "resources/Papers"
HTML_HREF_PREFIX = "resources/Paper-html"

BASE_LIBRARY = {
    "categories": [
        {"id": "all", "name": "All Notes", "parentId": None, "order": 0, "system": True},
        {"id": "uncategorized", "name": "Uncategorized", "parentId": None, "order": 1, "system": True},
    ],
    "notes": [],
}

MIME_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".svg": "image/svg+xml",
}


def normalize_text(value: Any) -> str:
    return str(value or "").strip()


def get_today_label() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def base36(value: int) -> str:
    chars = "0123456789abcdefghijklmnopqrstuvwxyz"
    if value == 0:
        return "0"
    result = ""
    while value:
        value, remainder = divmod(value, 36)
        result = chars[remainder] + result
    return result


def safe_file_name(file_name: str) -> str:
    original = Path(file_name or "Untitled Paper.pdf").name
    ext = Path(original).suffix.lower() or ".pdf"
    base = original[: -len(Path(original).suffix)] if Path(original).suffix else original
    base = re.sub(r'[\\/:*?"<>|#%{}^~\[\]`]+', "", base)
    base = re.sub(r"\s+", " ", base).strip()
    return f"{base or 'Untitled Paper'}{ext}"


def note_title_from_pdf(file_name: str) -> str:
    title = Path(file_name).stem
    title = re.sub(r"[-_]+", " ", title).strip()
    return title or "Untitled PDF"


def safe_annotation_id(note_id: str) -> str:
    safe_id = re.sub(r"[^a-z0-9\u4e00-\u9fff._-]+", "-", normalize_text(note_id), flags=re.IGNORECASE)
    return safe_id.strip("-")


def annotation_path_for(note_id: str) -> Path | None:
    safe_id = safe_annotation_id(note_id)
    if not safe_id:
        return None
    return ANNOTATIONS_DIR / f"{safe_id}.json"


def note_id_from_title(title: str) -> str:
    slug = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "-", normalize_text(title).lower(), flags=re.IGNORECASE)
    slug = slug.strip("-")[:80]
    stamp = int(time.time() * 1000)
    return f"pdf-{slug or stamp}-{base36(stamp)}"


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


def resource_href(prefix: str, file_name: str) -> str:
    return f"{prefix}/{quote(file_name)}"


def finite_number(value: Any, fallback: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return fallback
    if number != number or number in (float("inf"), float("-inf")):
        return fallback
    return number


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
        if category["id"] == "all":
            categories.append({**category, "parentId": None, "order": 0, "system": True})
        elif category["id"] == "uncategorized":
            categories.append({**category, "parentId": None, "order": 1, "system": True})
        else:
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

    child_map: dict[str, list[dict[str, Any]]] = {}
    for category in categories:
        key = category.get("parentId") or "root"
        child_map.setdefault(key, []).append(category)

    for group in child_map.values():
        group.sort(key=lambda category: (category.get("order", 0), category.get("name", "")))
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
                "href": normalize_resource_href(note.get("href")),
                "htmlHref": normalize_resource_href(note.get("htmlHref")),
                "pdfStorageKey": normalize_text(note.get("pdfStorageKey")),
                "date": normalize_text(note.get("date")),
                "order": finite_number(note.get("order"), index),
                "categoryId": requested_category_id if requested_category_id in leaf_ids else "uncategorized",
                "venue": normalize_text(note.get("venue")),
                "summary": normalize_text(note.get("summary")),
                "tags": normalize_tags(note.get("tags")),
            }
        )

    return {"categories": categories, "notes": notes}


def create_paper_note_html(title: str, date: str, file_name: str) -> str:
    safe_title = html.escape(title, quote=True)
    safe_date = html.escape(date, quote=True)
    safe_file_name = html.escape(file_name, quote=True)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{safe_title}</title>
  <script src="/scripts/theme.js"></script>
  <link rel="stylesheet" href="/styles/note.css">
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

      <section class="note-body"></section>
    </div>
  </main>
  <script src="/scripts/note.js"></script>
</body>
</html>"""


def read_library() -> dict[str, Any]:
    try:
        return sanitize_library(json.loads(NOTES_PATH.read_text(encoding="utf-8")))
    except Exception:
        return copy.deepcopy(BASE_LIBRARY)


def write_library(library: dict[str, Any]) -> None:
    NOTES_PATH.write_text(json.dumps(sanitize_library(library), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def iso_now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def safe_session_id(session_id: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]+", "-", normalize_text(session_id)).strip("-")


def session_path_for(session_id: str) -> Path | None:
    safe_id = safe_session_id(session_id)
    if not safe_id:
        return None
    return SESSIONS_DIR / f"{safe_id}.jsonl"


def title_from_message(message: str) -> str:
    title = re.sub(r"\s+", " ", normalize_text(message))
    return title[:60] or "New chat"


def summarize_session(session: dict[str, Any]) -> dict[str, Any]:
    messages = session.get("messages") if isinstance(session.get("messages"), list) else []
    preview = ""
    for message in reversed(messages):
        preview = normalize_text(message.get("text") if isinstance(message, dict) else "")
        if preview:
            break
    return {
        "id": session.get("id", ""),
        "noteId": session.get("noteId", ""),
        "title": session.get("title") or "New chat",
        "createdAt": session.get("createdAt", ""),
        "updatedAt": session.get("updatedAt", ""),
        "trashedAt": session.get("trashedAt", ""),
        "lastMessagePreview": preview[:120],
        "messageCount": len(messages),
    }


def new_session(note_id: str) -> dict[str, Any]:
    now = iso_now()
    session_id = f"session-{datetime.now().strftime('%Y-%m-%dT%H-%M-%S')}-{uuid.uuid4()}"
    return {
        "id": session_id,
        "noteId": normalize_text(note_id) or "library",
        "title": "New chat",
        "createdAt": now,
        "updatedAt": now,
        "trashedAt": "",
        "agentSessionId": session_id,
        "messages": [],
    }


def read_session(session_id: str) -> dict[str, Any] | None:
    path = session_path_for(session_id)
    if path is None or not path.is_file():
        return None

    session: dict[str, Any] | None = None
    messages: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        record_type = record.get("type")
        if record_type == "session" and isinstance(record.get("session"), dict):
            session = {**record["session"]}
        elif record_type == "message" and isinstance(record.get("message"), dict):
            messages.append(record["message"])

    if session is None:
        return None
    session["messages"] = messages
    session.setdefault("trashedAt", "")
    session.setdefault("agentSessionId", session.get("id", ""))
    return session


def write_session(session: dict[str, Any]) -> None:
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    path = session_path_for(session.get("id", ""))
    if path is None:
        raise ValueError("Invalid session id.")

    metadata = {key: value for key, value in session.items() if key != "messages"}
    lines = [json.dumps({"type": "session", "session": metadata}, ensure_ascii=False)]
    for message in session.get("messages", []):
        lines.append(json.dumps({"type": "message", "message": message}, ensure_ascii=False))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def list_sessions(note_id: str, trashed: bool = False) -> list[dict[str, Any]]:
    if not SESSIONS_DIR.is_dir():
        return []
    sessions = []
    for path in SESSIONS_DIR.glob("*.jsonl"):
        session = read_session(path.stem)
        if not session:
            continue
        if normalize_text(session.get("noteId")) != normalize_text(note_id):
            continue
        is_trashed = bool(normalize_text(session.get("trashedAt")))
        if is_trashed != trashed:
            continue
        sessions.append(summarize_session(session))
    sessions.sort(key=lambda item: item.get("updatedAt", ""), reverse=True)
    return sessions


def ensure_chat_session(session_id: str, note_id: str) -> dict[str, Any]:
    session = read_session(session_id) if session_id else None
    if session:
        return session
    session = new_session(note_id)
    write_session(session)
    return session


def append_message(session: dict[str, Any], role: str, text: str, **extra: Any) -> dict[str, Any]:
    now = iso_now()
    message = {
        "role": "user" if role == "user" else "assistant",
        "text": normalize_text(text),
        "createdAt": now,
        **extra,
    }
    messages = session.setdefault("messages", [])
    messages.append(message)
    if session.get("title") == "New chat" and role == "user":
        session["title"] = title_from_message(text)
    session["updatedAt"] = now
    write_session(session)
    return message


def note_body_html_from_document(content: str) -> str:
    match = re.search(r'<section[^>]*class="[^"]*\bnote-body\b[^"]*"[^>]*>([\s\S]*?)</section>', content, flags=re.IGNORECASE)
    return match.group(1) if match else ""


def replace_note_body_html(content: str, replacement_html: str) -> str:
    pattern = r'(<section[^>]*class="[^"]*\bnote-body\b[^"]*"[^>]*>)([\s\S]*?)(</section>)'
    if re.search(pattern, content, flags=re.IGNORECASE):
        return re.sub(pattern, lambda match: f"{match.group(1)}{replacement_html}{match.group(3)}", content, count=1, flags=re.IGNORECASE)
    return content.replace("</main>", f'<section class="note-body">{replacement_html}</section>\n  </main>', 1)


def update_note_html_title(note: dict[str, Any], next_title: str) -> None:
    html_href = normalize_text(note.get("htmlHref"))
    if not html_href:
        return
    html_path = (PROJECT_ROOT / unquote(html_href)).resolve()
    if not is_relative_to(html_path, HTML_DIR.resolve()):
        return
    try:
        safe_title = html.escape(next_title, quote=True)
        content = html_path.read_text(encoding="utf-8")
        content = re.sub(r"<title>[\s\S]*?</title>", f"<title>{safe_title}</title>", content, count=1, flags=re.IGNORECASE)
        content = re.sub(r"<h1>[\s\S]*?</h1>", f"<h1>{safe_title}</h1>", content, count=1, flags=re.IGNORECASE)
        html_path.write_text(content, encoding="utf-8")
    except Exception as error:
        print(f"Could not update note HTML title for {note.get('id')}: {error}", file=sys.stderr)


def is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


class PaperNotesHandler(BaseHTTPRequestHandler):
    server_version = "PaperNotesPython/0.1"

    def end_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET,HEAD,POST,PATCH,DELETE,OPTIONS")
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, format: str, *args: Any) -> None:
        print(f"{self.address_string()} - {format % args}")

    def send_text(self, status: int, body: str, content_type: str = "text/plain; charset=utf-8") -> None:
        encoded = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(encoded)

    def send_json(self, status: int, body: Any) -> None:
        self.send_text(status, json.dumps(body, ensure_ascii=False, indent=2), "application/json; charset=utf-8")

    def read_json_body(self) -> Any:
        content_length = int(self.headers.get("Content-Length") or "0")
        if content_length > MAX_BODY_SIZE:
            raise ValueError("Request body is too large.")
        raw = self.rfile.read(content_length)
        return json.loads(raw.decode("utf-8") or "{}")

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self.end_headers()

    def do_HEAD(self) -> None:
        self.serve_static()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/annotations":
            self.handle_read_annotations(parsed.query)
            return
        if parsed.path == "/api/chat-progress":
            self.handle_chat_progress(parsed.query)
            return
        if parsed.path == "/api/chat-sessions":
            self.handle_list_chat_sessions(parsed.query)
            return
        if parsed.path.startswith("/api/chat-sessions/"):
            self.handle_get_chat_session(parsed.path)
            return
        self.serve_static()

    def do_POST(self) -> None:
        routes = {
            "/api/import-pdf": self.handle_import_pdf,
            "/api/rename-note": self.handle_rename_note,
            "/api/update-note-summary": self.handle_update_note_summary,
            "/api/library": self.handle_write_library,
            "/api/annotations": self.handle_write_annotations,
            "/api/chat": self.handle_chat,
            "/api/chat-sessions": self.handle_create_chat_session,
            "/api/apply-note-edit": self.handle_apply_note_edit,
        }
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/chat-sessions/") and parsed.path.endswith("/restore"):
            try:
                self.handle_restore_chat_session(parsed.path)
            except Exception as error:
                print(error, file=sys.stderr)
                self.send_text(HTTPStatus.INTERNAL_SERVER_ERROR, str(error) or "Server error")
            return
        handler = routes.get(parsed.path)
        if handler is None:
            self.send_text(HTTPStatus.METHOD_NOT_ALLOWED, "Method not allowed")
            return
        try:
            handler()
        except Exception as error:
            print(error, file=sys.stderr)
            self.send_text(HTTPStatus.INTERNAL_SERVER_ERROR, str(error) or "Server error")

    def do_PATCH(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/chat-sessions/"):
            try:
                self.handle_rename_chat_session(parsed.path)
            except Exception as error:
                print(error, file=sys.stderr)
                self.send_text(HTTPStatus.INTERNAL_SERVER_ERROR, str(error) or "Server error")
            return
        self.send_text(HTTPStatus.METHOD_NOT_ALLOWED, "Method not allowed")

    def do_DELETE(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/chat-sessions/") and parsed.path.endswith("/permanent"):
            try:
                self.handle_permanent_delete_chat_session(parsed.path)
            except Exception as error:
                print(error, file=sys.stderr)
                self.send_text(HTTPStatus.INTERNAL_SERVER_ERROR, str(error) or "Server error")
            return
        if parsed.path.startswith("/api/chat-sessions/"):
            try:
                self.handle_trash_chat_session(parsed.path)
            except Exception as error:
                print(error, file=sys.stderr)
                self.send_text(HTTPStatus.INTERNAL_SERVER_ERROR, str(error) or "Server error")
            return
        self.send_text(HTTPStatus.METHOD_NOT_ALLOWED, "Method not allowed")

    def handle_import_pdf(self) -> None:
        body = self.read_json_body()
        original_name = safe_file_name(body.get("fileName"))
        if not original_name.lower().endswith(".pdf"):
            self.send_text(HTTPStatus.BAD_REQUEST, "Only PDF files can be imported.")
            return

        try:
            pdf_data = base64.b64decode(str(body.get("dataBase64") or ""), validate=False)
        except Exception:
            pdf_data = b""
        if not pdf_data:
            self.send_text(HTTPStatus.BAD_REQUEST, "PDF file is empty.")
            return

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
            "categoryId": normalize_text(body.get("categoryId")) or "uncategorized",
            "venue": "",
            "summary": "",
            "tags": [],
        }

        (PAPERS_DIR / original_name).write_bytes(pdf_data)
        (HTML_DIR / html_name).write_text(create_paper_note_html(title, date, original_name), encoding="utf-8")

        library["notes"] = [*existing_notes, note]
        write_library(library)
        self.send_json(HTTPStatus.CREATED, note)

    def handle_rename_note(self) -> None:
        body = self.read_json_body()
        note_id = normalize_text(body.get("id"))
        next_title = normalize_text(body.get("title"))
        if not note_id or not next_title:
            self.send_text(HTTPStatus.BAD_REQUEST, "Note id and title are required.")
            return

        library = read_library()
        note = next((entry for entry in library.get("notes", []) if entry.get("id") == note_id), None)
        if note is None:
            self.send_text(HTTPStatus.NOT_FOUND, "Note not found.")
            return

        note["title"] = next_title
        write_library(library)
        update_note_html_title(note, next_title)
        self.send_json(HTTPStatus.OK, note)

    def handle_update_note_summary(self) -> None:
        body = self.read_json_body()
        note_id = normalize_text(body.get("id"))
        if not note_id:
            self.send_text(HTTPStatus.BAD_REQUEST, "Note id is required.")
            return

        library = read_library()
        note = next((entry for entry in library.get("notes", []) if entry.get("id") == note_id), None)
        if note is None:
            self.send_text(HTTPStatus.NOT_FOUND, "Note not found.")
            return

        note["summary"] = normalize_text(body.get("summary"))
        write_library(library)
        self.send_json(HTTPStatus.OK, note)

    def handle_write_library(self) -> None:
        library = sanitize_library(self.read_json_body())
        write_library(library)
        self.send_json(HTTPStatus.OK, library)

    def handle_read_annotations(self, query: str) -> None:
        params = parse_qs(query)
        annotations_path = annotation_path_for(params.get("noteId", [""])[0])
        if annotations_path is None:
            self.send_text(HTTPStatus.BAD_REQUEST, "noteId is required.")
            return
        try:
            self.send_text(HTTPStatus.OK, annotations_path.read_text(encoding="utf-8"), "application/json; charset=utf-8")
        except FileNotFoundError:
            self.send_json(HTTPStatus.OK, {"annotations": []})

    def handle_write_annotations(self) -> None:
        body = self.read_json_body()
        annotations_path = annotation_path_for(body.get("noteId"))
        if annotations_path is None:
            self.send_text(HTTPStatus.BAD_REQUEST, "noteId is required.")
            return

        annotations = body.get("annotations") if isinstance(body.get("annotations"), list) else []
        ANNOTATIONS_DIR.mkdir(parents=True, exist_ok=True)
        annotations_path.write_text(json.dumps({"annotations": annotations}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        self.send_json(HTTPStatus.OK, {"annotations": annotations})

    def handle_chat_progress(self, query: str) -> None:
        request_id = parse_qs(query).get("requestId", [""])[0]
        self.send_json(HTTPStatus.OK, {
            "requestId": request_id,
            "status": "done",
            "stage": "complete",
            "detail": "The local Python server handled the request.",
            "events": [],
        })

    def handle_list_chat_sessions(self, query: str) -> None:
        params = parse_qs(query)
        note_id = normalize_text(params.get("noteId", [""])[0])
        trashed = params.get("trashed", [""])[0] in {"1", "true", "yes"}
        if not note_id:
            self.send_json(HTTPStatus.OK, {"sessions": []})
            return
        self.send_json(HTTPStatus.OK, {"sessions": list_sessions(note_id, trashed=trashed)})

    def handle_create_chat_session(self) -> None:
        body = self.read_json_body()
        session = new_session(body.get("noteId"))
        write_session(session)
        self.send_json(HTTPStatus.CREATED, session)

    def session_id_from_chat_path(self, path: str, suffix: str = "") -> str:
        value = path.removeprefix("/api/chat-sessions/")
        if suffix and value.endswith(suffix):
            value = value[: -len(suffix)]
        return safe_session_id(unquote(value.strip("/")))

    def handle_get_chat_session(self, path: str) -> None:
        if path.endswith("/export"):
            self.handle_export_chat_session(path)
            return
        session = read_session(self.session_id_from_chat_path(path))
        if not session:
            self.send_text(HTTPStatus.NOT_FOUND, "Session not found.")
            return
        self.send_json(HTTPStatus.OK, session)

    def handle_export_chat_session(self, path: str) -> None:
        session_id = self.session_id_from_chat_path(path, "/export")
        file_path = session_path_for(session_id)
        if file_path is None or not file_path.is_file():
            self.send_text(HTTPStatus.NOT_FOUND, "Session not found.")
            return
        data = file_path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/jsonl; charset=utf-8")
        self.send_header("Content-Disposition", f'attachment; filename="{file_path.name}"')
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def handle_rename_chat_session(self, path: str) -> None:
        session = read_session(self.session_id_from_chat_path(path))
        if not session:
            self.send_text(HTTPStatus.NOT_FOUND, "Session not found.")
            return
        title = normalize_text(self.read_json_body().get("title"))
        if not title:
            self.send_text(HTTPStatus.BAD_REQUEST, "Session title is required.")
            return
        session["title"] = title[:80]
        session["updatedAt"] = iso_now()
        write_session(session)
        self.send_json(HTTPStatus.OK, session)

    def handle_trash_chat_session(self, path: str) -> None:
        session = read_session(self.session_id_from_chat_path(path))
        if not session:
            self.send_text(HTTPStatus.NOT_FOUND, "Session not found.")
            return
        session["trashedAt"] = iso_now()
        session["updatedAt"] = session["trashedAt"]
        write_session(session)
        self.send_json(HTTPStatus.OK, session)

    def handle_restore_chat_session(self, path: str) -> None:
        session = read_session(self.session_id_from_chat_path(path, "/restore"))
        if not session:
            self.send_text(HTTPStatus.NOT_FOUND, "Session not found.")
            return
        session["trashedAt"] = ""
        session["updatedAt"] = iso_now()
        write_session(session)
        self.send_json(HTTPStatus.OK, session)

    def handle_permanent_delete_chat_session(self, path: str) -> None:
        file_path = session_path_for(self.session_id_from_chat_path(path, "/permanent"))
        if file_path and file_path.is_file():
            file_path.unlink()
        self.send_json(HTTPStatus.OK, {"ok": True})

    def handle_chat(self) -> None:
        body = self.read_json_body()
        message = normalize_text(body.get("message"))
        context = body.get("context") if isinstance(body.get("context"), dict) else {}
        note_id = normalize_text(context.get("selectedNoteId")) or normalize_text(body.get("noteId")) or "library"
        if not message:
            self.send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "Message is required."})
            return

        session = ensure_chat_session(body.get("sessionId"), note_id)
        append_message(session, "user", message)

        answer = (
            "The local Python backend is running and saved this chat session. "
            "An AI provider is not configured on this branch yet, so I cannot generate a real answer here."
        )
        assistant_message = append_message(session, "assistant", answer)
        self.send_json(HTTPStatus.OK, {
            "ok": True,
            "sessionId": session["id"],
            "answer": assistant_message["text"],
            "sources": [],
        })

    def handle_apply_note_edit(self) -> None:
        body = self.read_json_body()
        note_id = normalize_text(body.get("noteId"))
        replacement_html = str(body.get("replacementHtml") or "").strip()
        if not note_id or not replacement_html:
            self.send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "noteId and replacementHtml are required."})
            return

        library = read_library()
        note = next((entry for entry in library.get("notes", []) if entry.get("id") == note_id), None)
        if not note:
            self.send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "Note not found."})
            return

        html_href = normalize_text(note.get("htmlHref"))
        html_path = (PROJECT_ROOT / unquote(html_href)).resolve()
        if not html_href or not is_relative_to(html_path, HTML_DIR.resolve()) or not html_path.is_file():
            self.send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "Note HTML not found."})
            return

        content = html_path.read_text(encoding="utf-8")
        updated = replace_note_body_html(content, replacement_html)
        html_path.write_text(updated, encoding="utf-8")
        self.send_json(HTTPStatus.OK, {
            "ok": True,
            "note": note,
            "noteBodyHtml": note_body_html_from_document(updated),
        })

    def serve_static(self) -> None:
        parsed = urlparse(self.path)
        pathname = unquote(parsed.path)
        if pathname == "/":
            pathname = "/index.html"

        base_dir = PUBLIC_DIR
        relative_path = pathname.lstrip("/")

        if pathname.startswith("/assets/scripts/"):
            base_dir = PUBLIC_DIR
            relative_path = pathname.removeprefix("/assets/")
        elif pathname.startswith("/assets/styles/"):
            base_dir = PUBLIC_DIR
            relative_path = pathname.removeprefix("/assets/")
        elif pathname.startswith("/resources/"):
            base_dir = PROJECT_ROOT
        elif pathname.startswith("/node_modules/"):
            base_dir = PROJECT_ROOT
        elif pathname.startswith("/assets/"):
            base_dir = PROJECT_ROOT
        elif pathname == "/notes.json":
            base_dir = PROJECT_ROOT

        file_path = (base_dir / relative_path).resolve()
        if not is_relative_to(file_path, base_dir.resolve()):
            self.send_text(HTTPStatus.FORBIDDEN, "Forbidden")
            return

        if not file_path.is_file():
            self.send_text(HTTPStatus.NOT_FOUND, "Not found")
            return

        content_type = MIME_TYPES.get(file_path.suffix.lower()) or mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
        data = file_path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)


def main() -> None:
    server = ThreadingHTTPServer((HOST, PORT), PaperNotesHandler)
    print(f"Paper Notes is running at http://localhost:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping Paper Notes.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
