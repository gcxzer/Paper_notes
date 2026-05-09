from __future__ import annotations

import json
import mimetypes
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from backend.annotations import read_annotations, write_annotations
from backend.core import normalize_text
from backend.library import import_pdf, read_library, rename_note, sanitize_library, update_note_summary, write_library
from backend.paths import (
    HOST,
    MAX_BODY_SIZE,
    PORT,
    PROJECT_ROOT,
    PUBLIC_DIR,
    is_relative_to,
)


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


class PaperNotesHandler(BaseHTTPRequestHandler):
    server_version = "PaperNotesPython/0.1"

    def end_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET,HEAD,POST,OPTIONS")
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
        if parsed.path == "/api/library":
            self.handle_read_library()
            return
        if parsed.path == "/api/annotations":
            self.handle_read_annotations(parsed.query)
            return
        self.serve_static()

    def do_POST(self) -> None:
        routes = {
            "/api/import-pdf": self.handle_import_pdf,
            "/api/rename-note": self.handle_rename_note,
            "/api/update-note-summary": self.handle_update_note_summary,
            "/api/library": self.handle_write_library,
            "/api/annotations": self.handle_write_annotations,
        }
        parsed = urlparse(self.path)
        handler = routes.get(parsed.path)
        if handler is None:
            self.send_text(HTTPStatus.METHOD_NOT_ALLOWED, "Method not allowed")
            return
        self._run_api_handler(handler)

    def do_PATCH(self) -> None:
        self.send_text(HTTPStatus.METHOD_NOT_ALLOWED, "Method not allowed")

    def do_DELETE(self) -> None:
        self.send_text(HTTPStatus.METHOD_NOT_ALLOWED, "Method not allowed")

    def _run_api_handler(self, handler: Any) -> None:
        try:
            handler()
        except ValueError as error:
            self.send_text(HTTPStatus.BAD_REQUEST, str(error) or "Bad request")
        except Exception as error:
            print(error, file=sys.stderr)
            self.send_text(HTTPStatus.INTERNAL_SERVER_ERROR, str(error) or "Server error")

    def handle_read_library(self) -> None:
        self.send_json(HTTPStatus.OK, read_library())

    def handle_import_pdf(self) -> None:
        note = import_pdf(self.read_json_body())
        self.send_json(HTTPStatus.CREATED, note)

    def handle_rename_note(self) -> None:
        body = self.read_json_body()
        note_id = normalize_text(body.get("id"))
        next_title = normalize_text(body.get("title"))
        if not note_id or not next_title:
            self.send_text(HTTPStatus.BAD_REQUEST, "Note id and title are required.")
            return

        note = rename_note(note_id, next_title)
        if note is None:
            self.send_text(HTTPStatus.NOT_FOUND, "Note not found.")
            return
        self.send_json(HTTPStatus.OK, note)

    def handle_update_note_summary(self) -> None:
        body = self.read_json_body()
        note_id = normalize_text(body.get("id"))
        if not note_id:
            self.send_text(HTTPStatus.BAD_REQUEST, "Note id is required.")
            return

        note = update_note_summary(note_id, body.get("summary"))
        if note is None:
            self.send_text(HTTPStatus.NOT_FOUND, "Note not found.")
            return
        self.send_json(HTTPStatus.OK, note)

    def handle_write_library(self) -> None:
        library = write_library(sanitize_library(self.read_json_body()))
        self.send_json(HTTPStatus.OK, library)

    def handle_read_annotations(self, query: str) -> None:
        note_id = parse_qs(query).get("noteId", [""])[0]
        payload = read_annotations(note_id)
        if payload is None:
            self.send_text(HTTPStatus.BAD_REQUEST, "noteId is required.")
            return
        self.send_json(HTTPStatus.OK, payload)

    def handle_write_annotations(self) -> None:
        body = self.read_json_body()
        payload = write_annotations(body.get("noteId"), body.get("annotations"))
        if payload is None:
            self.send_text(HTTPStatus.BAD_REQUEST, "noteId is required.")
            return
        self.send_json(HTTPStatus.OK, payload)

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
