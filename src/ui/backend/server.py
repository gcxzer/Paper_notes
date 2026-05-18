from __future__ import annotations

import json
import mimetypes
import os
import re
import subprocess
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlparse

from ui.backend.agent_api import (
    AgentAPIError,
    archive_chat_session,
    branch_chat_session,
    cancel_chat_request,
    cleanup_debug_runs,
    cleanup_chat_tool_snapshots,
    compact_chat_session,
    create_chat_session,
    delete_chat_session,
    error_response,
    get_chat_context_status,
    get_chat_progress,
    get_chat_session,
    get_debug_run,
    handle_chat_request,
    handle_chat_stream_request,
    get_agent_service,
    list_chat_tool_snapshots,
    list_chat_sessions,
    list_debug_runs,
    rename_chat_session,
    redo_chat_tool_snapshot,
    list_chat_tool_approvals,
    preview_chat_tool_snapshot,
    respond_chat_tool_approval,
    undo_chat_session,
    undo_chat_tool_snapshot,
    update_chat_session_model,
    upload_chat_attachment,
)
from media import MediaStoreError
from library.annotations import read_annotations, write_annotations
from app_infra.formatting import normalize_text
from library import import_pdf, import_pdf_from_url, read_library, rename_note, sanitize_library, update_note_summary, write_library
from ui.backend.memory_api import list_memory, update_memory
from ui.backend.mcp_api import (
    connect_mcp_server,
    get_mcp_settings,
    get_mcp_stderr_log,
    reconnect_mcp_server,
    reset_mcp_server_circuit,
    test_mcp_server,
    update_mcp_settings,
)
from ui.backend.model_providers_api import get_model_providers
from app_infra.paths import (
    HOST,
    MAX_BODY_SIZE,
    PORT,
    PROJECT_ROOT,
    PUBLIC_DIR,
    is_relative_to,
)
from ui.backend.settings_api import (
    delete_ai_api_key,
    get_ai_settings,
    get_codex_auth_status,
    get_tool_settings,
    logout_codex_auth,
    poll_codex_auth,
    start_codex_auth,
    update_ai_settings,
    update_tool_settings,
)
from ui.backend.skills_api import list_skills, update_skill, update_skill_settings, view_skill


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
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".svg": "image/svg+xml",
}

DOCKER_LOCAL_FILE_OPEN_MESSAGE = (
    "Docker mode cannot open files in the host desktop. Put the file under "
    ".paper-notes/media/uploads, then use that Paper Notes media path from the app."
)


def content_disposition_attachment(file_name: str) -> str:
    display_name = Path(normalize_text(file_name) or "download").name or "download"
    fallback = re.sub(r'[^A-Za-z0-9_. -]+', "-", display_name).strip(". ")
    fallback = re.sub(r"-{2,}", "-", fallback) or "download"
    fallback = fallback.replace('"', "")
    encoded = quote(display_name, safe="")
    return f'attachment; filename="{fallback}"; filename*=UTF-8\'\'{encoded}'


def is_docker_runtime() -> bool:
    value = os.environ.get("PAPER_NOTES_DOCKER", "").strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    return Path("/.dockerenv").exists()


class PaperNotesHandler(BaseHTTPRequestHandler):
    server_version = "PaperNotesPython/1.2.1"

    def end_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Paper-Notes-Local-Action")
        self.send_header("Access-Control-Allow-Methods", "GET,HEAD,POST,DELETE,OPTIONS")
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

    def send_bytes(
        self,
        status: int,
        body: bytes,
        *,
        content_type: str,
        file_name: str = "",
        download: bool = False,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        if download:
            self.send_header("Content-Disposition", content_disposition_attachment(file_name))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

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
        if parsed.path.startswith("/api/media/"):
            self._run_api_handler(lambda: self.handle_get_media(parsed.path))
            return
        if parsed.path == "/api/library":
            self.handle_read_library()
            return
        if parsed.path == "/api/annotations":
            self.handle_read_annotations(parsed.query)
            return
        if parsed.path == "/api/chat/sessions":
            self._run_api_handler(lambda: self.handle_list_chat_sessions(parsed.query))
            return
        if parsed.path == "/api/chat/progress":
            self._run_api_handler(lambda: self.handle_get_chat_progress(parsed.query))
            return
        if parsed.path == "/api/chat/context":
            self._run_api_handler(lambda: self.handle_get_chat_context_status(parsed.query))
            return
        if parsed.path == "/api/chat/session":
            self._run_api_handler(lambda: self.handle_get_chat_session(parsed.query))
            return
        if parsed.path == "/api/chat/tool-snapshots":
            self._run_api_handler(lambda: self.handle_list_chat_tool_snapshots(parsed.query))
            return
        if parsed.path == "/api/chat/tool-snapshot-diff":
            self._run_api_handler(lambda: self.handle_preview_chat_tool_snapshot(parsed.query))
            return
        if parsed.path == "/api/chat/tool-approvals":
            self._run_api_handler(lambda: self.handle_list_chat_tool_approvals(parsed.query))
            return
        if parsed.path == "/api/debug/runs":
            self._run_api_handler(lambda: self.handle_list_debug_runs(parsed.query))
            return
        if parsed.path.startswith("/api/debug/runs/"):
            self._run_api_handler(lambda: self.handle_get_debug_run(parsed.path))
            return
        if parsed.path == "/api/memory":
            self._run_api_handler(self.handle_list_memory)
            return
        if parsed.path == "/api/settings/ai":
            self._run_api_handler(self.handle_get_ai_settings)
            return
        if parsed.path == "/api/settings/tools":
            self._run_api_handler(self.handle_get_tool_settings)
            return
        if parsed.path == "/api/settings/mcp":
            self._run_api_handler(self.handle_get_mcp_settings)
            return
        if parsed.path == "/api/settings/mcp/stderr-log":
            self._run_api_handler(lambda: self.handle_get_mcp_stderr_log(parsed.query))
            return
        if parsed.path == "/api/skills":
            self._run_api_handler(lambda: self.handle_list_skills(parsed.query))
            return
        if parsed.path == "/api/skills/view":
            self._run_api_handler(lambda: self.handle_view_skill(parsed.query))
            return
        if parsed.path == "/api/model/providers":
            self._run_api_handler(self.handle_get_model_providers)
            return
        if parsed.path == "/api/auth/codex/status":
            self._run_api_handler(self.handle_get_codex_auth_status)
            return
        self.serve_static()

    def do_POST(self) -> None:
        routes = {
            "/api/import-pdf": self.handle_import_pdf,
            "/api/import-paper-url": self.handle_import_paper_url,
            "/api/rename-note": self.handle_rename_note,
            "/api/update-note-summary": self.handle_update_note_summary,
            "/api/library": self.handle_write_library,
            "/api/annotations": self.handle_write_annotations,
            "/api/chat": self.handle_chat,
            "/api/chat/stream": self.handle_chat_stream,
            "/api/chat/attachments": self.handle_upload_chat_attachment,
            "/api/chat/cancel": self.handle_cancel_chat,
            "/api/chat/compress": self.handle_compact_chat_session,
            "/api/chat/session": self.handle_create_chat_session,
            "/api/chat/session/rename": self.handle_rename_chat_session,
            "/api/chat/session/archive": self.handle_archive_chat_session,
            "/api/chat/session/delete": self.handle_delete_chat_session,
            "/api/chat/session/branch": self.handle_branch_chat_session,
            "/api/chat/session/undo": self.handle_undo_chat_session,
            "/api/chat/tool-undo": self.handle_undo_chat_tool_snapshot,
            "/api/chat/tool-redo": self.handle_redo_chat_tool_snapshot,
            "/api/chat/tool-snapshots/cleanup": self.handle_cleanup_chat_tool_snapshots,
            "/api/chat/tool-approvals/respond": self.handle_respond_chat_tool_approval,
            "/api/chat/session/model": self.handle_update_chat_session_model,
            "/api/open-local-file": self.handle_open_local_file,
            "/api/memory": self.handle_update_memory,
            "/api/settings/ai": self.handle_update_ai_settings,
            "/api/settings/tools": self.handle_update_tool_settings,
            "/api/settings/mcp": self.handle_update_mcp_settings,
            "/api/settings/mcp/connect": self.handle_connect_mcp_server,
            "/api/settings/mcp/test": self.handle_test_mcp_server,
            "/api/settings/mcp/reconnect": self.handle_reconnect_mcp_server,
            "/api/settings/mcp/reset-circuit": self.handle_reset_mcp_server_circuit,
            "/api/skills/update": self.handle_update_skill,
            "/api/skills/settings": self.handle_update_skill_settings,
            "/api/auth/codex/start": self.handle_start_codex_auth,
            "/api/auth/codex/poll": self.handle_poll_codex_auth,
            "/api/auth/codex/logout": self.handle_logout_codex_auth,
            "/api/debug/runs/cleanup": self.handle_cleanup_debug_runs,
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
        routes = {
            "/api/settings/ai/key": self.handle_delete_ai_api_key,
        }
        parsed = urlparse(self.path)
        handler = routes.get(parsed.path)
        if handler is None:
            self.send_text(HTTPStatus.METHOD_NOT_ALLOWED, "Method not allowed")
            return
        self._run_api_handler(handler)

    def _run_api_handler(self, handler: Any) -> None:
        try:
            handler()
        except AgentAPIError as error:
            self.send_json(error.status, error_response(error))
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

    def handle_import_paper_url(self) -> None:
        note = import_pdf_from_url(self.read_json_body())
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

    def handle_chat(self) -> None:
        self.send_json(HTTPStatus.OK, handle_chat_request(self.read_json_body()))

    def handle_chat_stream(self) -> None:
        body = self.read_json_body()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Connection", "close")
        self.end_headers()

        closed = False

        def send_event(event: str, payload: dict[str, Any]) -> bool:
            nonlocal closed
            if closed:
                return False
            try:
                self.wfile.write(_sse_frame(event, payload))
                self.wfile.flush()
                return True
            except (BrokenPipeError, ConnectionResetError, OSError):
                closed = True
                return False

        try:
            handle_chat_stream_request(body, send_event=send_event)
        except Exception as error:
            print(error, file=sys.stderr)
            send_event("error", {"code": "stream_failed", "error": str(error) or "Chat stream failed."})
            send_event("done", {})
        finally:
            self.close_connection = True

    def handle_upload_chat_attachment(self) -> None:
        self.send_json(HTTPStatus.CREATED, upload_chat_attachment(self.read_json_body()))

    def handle_cancel_chat(self) -> None:
        self.send_json(HTTPStatus.OK, cancel_chat_request(self.read_json_body()))

    def handle_cleanup_debug_runs(self) -> None:
        self.send_json(HTTPStatus.OK, cleanup_debug_runs(self.read_json_body()))

    def handle_compact_chat_session(self) -> None:
        self.send_json(HTTPStatus.OK, compact_chat_session(self.read_json_body()))

    def handle_create_chat_session(self) -> None:
        self.send_json(HTTPStatus.CREATED, create_chat_session(self.read_json_body()))

    def handle_rename_chat_session(self) -> None:
        self.send_json(HTTPStatus.OK, rename_chat_session(self.read_json_body()))

    def handle_archive_chat_session(self) -> None:
        self.send_json(HTTPStatus.OK, archive_chat_session(self.read_json_body()))

    def handle_delete_chat_session(self) -> None:
        self.send_json(HTTPStatus.OK, delete_chat_session(self.read_json_body()))

    def handle_branch_chat_session(self) -> None:
        self.send_json(HTTPStatus.CREATED, branch_chat_session(self.read_json_body()))

    def handle_undo_chat_session(self) -> None:
        self.send_json(HTTPStatus.OK, undo_chat_session(self.read_json_body()))

    def handle_undo_chat_tool_snapshot(self) -> None:
        self.send_json(HTTPStatus.OK, undo_chat_tool_snapshot(self.read_json_body()))

    def handle_redo_chat_tool_snapshot(self) -> None:
        self.send_json(HTTPStatus.OK, redo_chat_tool_snapshot(self.read_json_body()))

    def handle_cleanup_chat_tool_snapshots(self) -> None:
        self.send_json(HTTPStatus.OK, cleanup_chat_tool_snapshots(self.read_json_body()))

    def handle_respond_chat_tool_approval(self) -> None:
        self.send_json(HTTPStatus.OK, respond_chat_tool_approval(self.read_json_body()))

    def handle_update_chat_session_model(self) -> None:
        self.send_json(HTTPStatus.OK, update_chat_session_model(self.read_json_body()))

    def handle_list_chat_sessions(self, query: str) -> None:
        self.send_json(HTTPStatus.OK, list_chat_sessions(parse_qs(query)))

    def handle_get_chat_session(self, query: str) -> None:
        self.send_json(HTTPStatus.OK, get_chat_session(parse_qs(query)))

    def handle_list_chat_tool_snapshots(self, query: str) -> None:
        self.send_json(HTTPStatus.OK, list_chat_tool_snapshots(parse_qs(query)))

    def handle_preview_chat_tool_snapshot(self, query: str) -> None:
        self.send_json(HTTPStatus.OK, preview_chat_tool_snapshot(parse_qs(query)))

    def handle_list_chat_tool_approvals(self, query: str) -> None:
        self.send_json(HTTPStatus.OK, list_chat_tool_approvals(parse_qs(query)))

    def handle_list_debug_runs(self, query: str) -> None:
        self.send_json(HTTPStatus.OK, list_debug_runs(parse_qs(query)))

    def handle_get_debug_run(self, path: str) -> None:
        request_id = unquote(path.rsplit("/", 1)[-1])
        self.send_json(HTTPStatus.OK, get_debug_run(request_id))

    def handle_get_chat_progress(self, query: str) -> None:
        self.send_json(HTTPStatus.OK, get_chat_progress(parse_qs(query)))

    def handle_get_chat_context_status(self, query: str) -> None:
        self.send_json(HTTPStatus.OK, get_chat_context_status(parse_qs(query)))

    def handle_list_memory(self) -> None:
        self.send_json(HTTPStatus.OK, list_memory())

    def handle_update_memory(self) -> None:
        self.send_json(HTTPStatus.OK, update_memory(self.read_json_body()))

    def handle_get_ai_settings(self) -> None:
        self.send_json(HTTPStatus.OK, get_ai_settings())

    def handle_get_tool_settings(self) -> None:
        self.send_json(HTTPStatus.OK, get_tool_settings())

    def handle_get_mcp_settings(self) -> None:
        self.send_json(HTTPStatus.OK, get_mcp_settings())

    def handle_list_skills(self, query: str) -> None:
        params = parse_qs(query)
        category = params.get("category", [""])[0]
        self.send_json(HTTPStatus.OK, list_skills(category=category))

    def handle_view_skill(self, query: str) -> None:
        params = parse_qs(query)
        name = params.get("name", [""])[0]
        file_path = params.get("filePath", params.get("file_path", [""]))[0]
        self.send_json(HTTPStatus.OK, view_skill(name=name, file_path=file_path))

    def handle_update_skill_settings(self) -> None:
        self.send_json(HTTPStatus.OK, update_skill_settings(self.read_json_body()))

    def handle_update_skill(self) -> None:
        self.send_json(HTTPStatus.OK, update_skill(self.read_json_body()))

    def handle_get_model_providers(self) -> None:
        self.send_json(HTTPStatus.OK, get_model_providers())

    def handle_open_local_file(self) -> None:
        if self.headers.get("X-Paper-Notes-Local-Action") != "open-local-file":
            raise AgentAPIError(HTTPStatus.FORBIDDEN, "missing_local_action_header", "Local file open requests require a trusted reader header.")
        body = self.read_json_body()
        if not isinstance(body, dict):
            raise AgentAPIError(HTTPStatus.BAD_REQUEST, "invalid_body", "Request body must be a JSON object.")
        raw_target = normalize_text(body.get("path") or body.get("href"))
        if not raw_target:
            raise AgentAPIError(HTTPStatus.BAD_REQUEST, "path_required", "path is required.")
        parsed = urlparse(raw_target)
        if parsed.scheme and parsed.scheme != "file":
            raise AgentAPIError(HTTPStatus.BAD_REQUEST, "unsupported_scheme", "Only local filesystem paths can be opened.")
        raw_path = unquote(parsed.path if parsed.scheme == "file" else raw_target)
        target = Path(raw_path).expanduser()
        if not target.is_absolute():
            raise AgentAPIError(HTTPStatus.BAD_REQUEST, "absolute_path_required", "Local file links must use an absolute path.")
        target = target.resolve()
        if is_docker_runtime():
            raise AgentAPIError(HTTPStatus.CONFLICT, "docker_local_file_open_unavailable", DOCKER_LOCAL_FILE_OPEN_MESSAGE)
        if not target.exists():
            raise AgentAPIError(HTTPStatus.NOT_FOUND, "file_not_found", f"File not found: {target}")
        try:
            if sys.platform == "darwin":
                subprocess.Popen(["open", str(target)])
            elif os.name == "nt":
                os.startfile(str(target))  # type: ignore[attr-defined]
            else:
                subprocess.Popen(["xdg-open", str(target)])
        except OSError as error:
            raise AgentAPIError(HTTPStatus.INTERNAL_SERVER_ERROR, "open_failed", str(error)) from error
        self.send_json(HTTPStatus.OK, {"success": True, "path": str(target)})

    def handle_get_media(self, path: str) -> None:
        parts = [part for part in path.split("/") if part]
        if len(parts) not in {3, 4} or parts[0] != "api" or parts[1] != "media":
            self.send_text(HTTPStatus.NOT_FOUND, "Media not found.")
            return
        artifact_id = unquote(parts[2])
        download = len(parts) == 4 and parts[3] == "download"
        if len(parts) == 4 and not download:
            self.send_text(HTTPStatus.NOT_FOUND, "Media not found.")
            return
        try:
            media_store = get_agent_service().media_store
            artifact = media_store.require_artifact(artifact_id)
            body = media_store.read_bytes(artifact.id)
        except MediaStoreError as error:
            raise AgentAPIError(HTTPStatus.NOT_FOUND, "media_not_found", str(error)) from error
        self.send_bytes(
            HTTPStatus.OK,
            body,
            content_type=artifact.mime_type,
            file_name=artifact.file_name,
            download=download,
        )

    def handle_update_ai_settings(self) -> None:
        self.send_json(HTTPStatus.OK, update_ai_settings(self.read_json_body()))

    def handle_update_tool_settings(self) -> None:
        self.send_json(HTTPStatus.OK, update_tool_settings(self.read_json_body()))

    def handle_update_mcp_settings(self) -> None:
        self.send_json(HTTPStatus.OK, update_mcp_settings(self.read_json_body()))

    def handle_test_mcp_server(self) -> None:
        self.send_json(HTTPStatus.OK, test_mcp_server(self.read_json_body()))

    def handle_connect_mcp_server(self) -> None:
        self.send_json(HTTPStatus.OK, connect_mcp_server(self.read_json_body()))

    def handle_reconnect_mcp_server(self) -> None:
        self.send_json(HTTPStatus.OK, reconnect_mcp_server(self.read_json_body()))

    def handle_reset_mcp_server_circuit(self) -> None:
        self.send_json(HTTPStatus.OK, reset_mcp_server_circuit(self.read_json_body()))

    def handle_get_mcp_stderr_log(self, query: str) -> None:
        params = parse_qs(query)
        try:
            max_chars = int((params.get("maxChars") or params.get("max_chars") or ["60000"])[0])
        except (TypeError, ValueError):
            max_chars = 60000
        self.send_json(HTTPStatus.OK, get_mcp_stderr_log(max_chars=max_chars))

    def handle_delete_ai_api_key(self) -> None:
        query = parse_qs(urlparse(self.path).query)
        provider = (query.get("provider") or ["openai"])[0]
        self.send_json(HTTPStatus.OK, delete_ai_api_key(provider))

    def handle_get_codex_auth_status(self) -> None:
        self.send_json(HTTPStatus.OK, get_codex_auth_status())

    def handle_start_codex_auth(self) -> None:
        self.send_json(HTTPStatus.OK, start_codex_auth())

    def handle_poll_codex_auth(self) -> None:
        self.send_json(HTTPStatus.OK, poll_codex_auth(self.read_json_body()))

    def handle_logout_codex_auth(self) -> None:
        self.send_json(HTTPStatus.OK, logout_codex_auth())

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


def _sse_frame(event: str, payload: dict[str, Any]) -> bytes:
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    lines = [f"event: {event}"]
    lines.extend(f"data: {line}" for line in body.splitlines() or ["{}"])
    return ("\n".join(lines) + "\n\n").encode("utf-8")


def main() -> None:
    server = ThreadingHTTPServer((HOST, PORT), PaperNotesHandler)
    display_host = "localhost" if HOST in {"127.0.0.1", "0.0.0.0"} else HOST
    print(f"Paper Notes is running at http://{display_host}:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping Paper Notes.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
