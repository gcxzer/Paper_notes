from __future__ import annotations

import asyncio
import json
import mimetypes
import os
import queue
import re
import subprocess
import sys
import threading
from collections.abc import AsyncIterator, Callable
from http import HTTPStatus
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote, urlparse

import uvicorn
from fastapi import FastAPI, Request, Response
from starlette.responses import StreamingResponse

from ui.backend.agent_api import (
    AgentAPIError,
    archive_chat_session,
    branch_chat_session,
    cancel_chat_request,
    cleanup_chat_tool_snapshots,
    cleanup_debug_runs,
    compact_chat_session,
    create_chat_session,
    delete_chat_session,
    error_response,
    get_agent_service,
    get_chat_context_status,
    get_chat_progress,
    get_chat_session,
    get_debug_run,
    handle_chat_request,
    handle_chat_stream_request,
    list_chat_sessions,
    list_chat_tool_approvals,
    list_chat_tool_snapshots,
    list_debug_runs,
    preview_chat_tool_snapshot,
    redo_chat_tool_snapshot,
    rename_chat_session,
    respond_chat_tool_approval,
    sync_chat_project_session_metadata,
    undo_chat_session,
    undo_chat_tool_snapshot,
    update_chat_session_model,
    update_chat_session_project,
    upload_chat_attachment,
)
from app_infra.formatting import normalize_text
from app_infra.paths import HOST, MAX_BODY_SIZE, PORT, PROJECT_ROOT, PUBLIC_DIR, is_relative_to
from library import (
    import_pdf,
    import_pdf_from_url,
    read_library,
    rename_note,
    sanitize_library,
    update_note_summary,
    write_library,
)
from library.annotations import read_annotations, write_annotations
from media import MediaStoreError
from ui.backend.chat_projects_api import create_chat_project, delete_chat_project, list_chat_projects, rename_chat_project
from ui.backend.mcp_api import (
    connect_mcp_server,
    get_mcp_settings,
    get_mcp_stderr_log,
    reconnect_mcp_server,
    reset_mcp_server_circuit,
    test_mcp_server,
    update_mcp_settings,
)
from ui.backend.memory_api import list_memory, update_memory
from ui.backend.model_providers_api import get_model_providers
from ui.backend.scratchpads_api import read_scratchpads, write_scratchpads
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
JSON_MEDIA_TYPE = "application/json; charset=utf-8"
TEXT_MEDIA_TYPE = "text/plain; charset=utf-8"
CORS_ALLOW_METHODS = "GET,HEAD,POST,DELETE,OPTIONS"
CORS_ALLOW_HEADERS = "Content-Type, X-Paper-Notes-Local-Action"


def content_disposition_attachment(file_name: str) -> str:
    display_name = Path(normalize_text(file_name) or "download").name or "download"
    fallback = re.sub(r'[^A-Za-z0-9_. -]+', "-", display_name).strip(". ")
    fallback = re.sub(r"-{2,}", "-", fallback) or "download"
    fallback = fallback.replace('"', "")
    encoded = quote(display_name, safe="")
    return f'attachment; filename="{fallback}"; filename*=UTF-8\'\'{encoded}'


def json_response(status: int | HTTPStatus, body: Any) -> Response:
    return Response(
        content=json.dumps(body, ensure_ascii=False, indent=2),
        status_code=int(status),
        media_type=JSON_MEDIA_TYPE,
    )


def text_response(
    status: int | HTTPStatus,
    body: str,
    content_type: str = TEXT_MEDIA_TYPE,
    *,
    head: bool = False,
) -> Response:
    encoded = body.encode("utf-8")
    headers = {"Content-Length": str(len(encoded))} if head else None
    return Response(
        content=b"" if head else encoded,
        status_code=int(status),
        media_type=content_type,
        headers=headers,
    )


async def read_json_body(request: Request) -> Any:
    try:
        content_length = int(request.headers.get("Content-Length") or "0")
    except ValueError as error:
        raise ValueError("Invalid Content-Length header.") from error
    if content_length > MAX_BODY_SIZE:
        raise ValueError("Request body is too large.")

    raw = await request.body()
    if len(raw) > MAX_BODY_SIZE:
        raise ValueError("Request body is too large.")
    return json.loads(raw.decode("utf-8") or "{}")


def query_params(request: Request) -> dict[str, list[str]]:
    params: dict[str, list[str]] = {}
    for key, value in request.query_params.multi_items():
        params.setdefault(key, []).append(value)
    return params


def first_param(params: dict[str, list[str]], key: str, default: str = "") -> str:
    values = params.get(key)
    if not values:
        return default
    return values[0]


def serve_static_path(pathname: str, *, head: bool = False) -> Response:
    pathname = unquote(pathname)
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
        return text_response(HTTPStatus.FORBIDDEN, "Forbidden", head=head)

    if not file_path.is_file():
        return text_response(HTTPStatus.NOT_FOUND, "Not found", head=head)

    content_type = MIME_TYPES.get(file_path.suffix.lower()) or mimetypes.guess_type(file_path.name)[0]
    content_type = content_type or "application/octet-stream"
    data = file_path.read_bytes()
    return Response(
        content=b"" if head else data,
        media_type=content_type,
        headers={"Content-Length": str(len(data))},
    )


def _sse_frame(event: str, payload: dict[str, Any]) -> bytes:
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    lines = [f"event: {event}"]
    lines.extend(f"data: {line}" for line in body.splitlines() or ["{}"])
    return ("\n".join(lines) + "\n\n").encode("utf-8")


async def sse_event_generator(body: Any, request: Request) -> AsyncIterator[bytes]:
    events: queue.Queue[bytes | None] = queue.Queue()
    closed = threading.Event()

    def send_event(event: str, payload: dict[str, Any]) -> bool:
        if closed.is_set():
            return False
        events.put(_sse_frame(event, payload))
        return True

    def run_stream() -> None:
        try:
            handle_chat_stream_request(body, send_event=send_event)
        except Exception as error:
            print(error, file=sys.stderr)
            send_event("error", {"code": "stream_failed", "error": str(error) or "Chat stream failed."})
            send_event("done", {})
        finally:
            events.put(None)

    threading.Thread(target=run_stream, daemon=True).start()
    try:
        while True:
            if await request.is_disconnected():
                closed.set()
                break
            try:
                event = events.get_nowait()
            except queue.Empty:
                await asyncio.sleep(0.05)
                continue
            if event is None:
                break
            yield event
    finally:
        closed.set()


def create_app() -> FastAPI:
    app = FastAPI(title="Paper Notes", version="2.0.1", docs_url=None, redoc_url=None)

    @app.middleware("http")
    async def add_compat_headers(request: Request, call_next: Callable[[Request], Any]) -> Response:
        response = await call_next(request)
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Headers"] = CORS_ALLOW_HEADERS
        response.headers["Access-Control-Allow-Methods"] = CORS_ALLOW_METHODS
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(AgentAPIError)
    async def handle_agent_api_error(request: Request, error: AgentAPIError) -> Response:
        return json_response(error.status, error_response(error))

    @app.exception_handler(ValueError)
    async def handle_value_error(request: Request, error: ValueError) -> Response:
        return text_response(HTTPStatus.BAD_REQUEST, str(error) or "Bad request")

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, error: Exception) -> Response:
        print(error, file=sys.stderr)
        return text_response(HTTPStatus.INTERNAL_SERVER_ERROR, str(error) or "Server error")

    @app.options("/")
    @app.options("/{path:path}")
    async def options_handler(path: str = "") -> Response:
        return Response(status_code=HTTPStatus.NO_CONTENT)

    @app.get("/api/library")
    async def api_read_library() -> Response:
        return json_response(HTTPStatus.OK, read_library())

    @app.post("/api/import-pdf")
    async def api_import_pdf(request: Request) -> Response:
        return json_response(HTTPStatus.CREATED, import_pdf(await read_json_body(request)))

    @app.post("/api/import-paper-url")
    async def api_import_paper_url(request: Request) -> Response:
        return json_response(HTTPStatus.CREATED, import_pdf_from_url(await read_json_body(request)))

    @app.post("/api/rename-note")
    async def api_rename_note(request: Request) -> Response:
        body = await read_json_body(request)
        note_id = normalize_text(body.get("id")) if isinstance(body, dict) else ""
        next_title = normalize_text(body.get("title")) if isinstance(body, dict) else ""
        if not note_id or not next_title:
            return text_response(HTTPStatus.BAD_REQUEST, "Note id and title are required.")

        note = rename_note(note_id, next_title)
        if note is None:
            return text_response(HTTPStatus.NOT_FOUND, "Note not found.")
        return json_response(HTTPStatus.OK, note)

    @app.post("/api/update-note-summary")
    async def api_update_note_summary(request: Request) -> Response:
        body = await read_json_body(request)
        note_id = normalize_text(body.get("id")) if isinstance(body, dict) else ""
        if not note_id:
            return text_response(HTTPStatus.BAD_REQUEST, "Note id is required.")

        note = update_note_summary(note_id, body.get("summary"))
        if note is None:
            return text_response(HTTPStatus.NOT_FOUND, "Note not found.")
        return json_response(HTTPStatus.OK, note)

    @app.post("/api/library")
    async def api_write_library(request: Request) -> Response:
        return json_response(HTTPStatus.OK, write_library(sanitize_library(await read_json_body(request))))

    @app.get("/api/annotations")
    async def api_read_annotations(request: Request) -> Response:
        note_id = first_param(query_params(request), "noteId")
        payload = read_annotations(note_id)
        if payload is None:
            return text_response(HTTPStatus.BAD_REQUEST, "noteId is required.")
        return json_response(HTTPStatus.OK, payload)

    @app.post("/api/annotations")
    async def api_write_annotations(request: Request) -> Response:
        body = await read_json_body(request)
        payload = write_annotations(body.get("noteId"), body.get("annotations")) if isinstance(body, dict) else None
        if payload is None:
            return text_response(HTTPStatus.BAD_REQUEST, "noteId is required.")
        return json_response(HTTPStatus.OK, payload)

    @app.post("/api/chat")
    async def api_chat(request: Request) -> Response:
        return json_response(HTTPStatus.OK, handle_chat_request(await read_json_body(request)))

    @app.post("/api/chat/stream")
    async def api_chat_stream(request: Request) -> StreamingResponse:
        body = await read_json_body(request)
        return StreamingResponse(
            sse_event_generator(body, request),
            media_type="text/event-stream; charset=utf-8",
            headers={"Connection": "close"},
        )

    @app.post("/api/chat/attachments")
    async def api_upload_chat_attachment(request: Request) -> Response:
        return json_response(HTTPStatus.CREATED, upload_chat_attachment(await read_json_body(request)))

    @app.post("/api/chat/cancel")
    async def api_cancel_chat(request: Request) -> Response:
        return json_response(HTTPStatus.OK, cancel_chat_request(await read_json_body(request)))

    @app.post("/api/debug/runs/cleanup")
    async def api_cleanup_debug_runs(request: Request) -> Response:
        return json_response(HTTPStatus.OK, cleanup_debug_runs(await read_json_body(request)))

    @app.post("/api/chat/compress")
    async def api_compact_chat_session(request: Request) -> Response:
        return json_response(HTTPStatus.OK, compact_chat_session(await read_json_body(request)))

    @app.post("/api/chat/session")
    async def api_create_chat_session(request: Request) -> Response:
        return json_response(HTTPStatus.CREATED, create_chat_session(await read_json_body(request)))

    @app.post("/api/chat/session/rename")
    async def api_rename_chat_session(request: Request) -> Response:
        return json_response(HTTPStatus.OK, rename_chat_session(await read_json_body(request)))

    @app.post("/api/chat/session/archive")
    async def api_archive_chat_session(request: Request) -> Response:
        return json_response(HTTPStatus.OK, archive_chat_session(await read_json_body(request)))

    @app.post("/api/chat/session/delete")
    async def api_delete_chat_session(request: Request) -> Response:
        return json_response(HTTPStatus.OK, delete_chat_session(await read_json_body(request)))

    @app.post("/api/chat/session/branch")
    async def api_branch_chat_session(request: Request) -> Response:
        return json_response(HTTPStatus.CREATED, branch_chat_session(await read_json_body(request)))

    @app.post("/api/chat/session/undo")
    async def api_undo_chat_session(request: Request) -> Response:
        return json_response(HTTPStatus.OK, undo_chat_session(await read_json_body(request)))

    @app.post("/api/chat/session/project")
    async def api_update_chat_session_project(request: Request) -> Response:
        return json_response(HTTPStatus.OK, update_chat_session_project(await read_json_body(request)))

    @app.get("/api/chat/projects")
    async def api_list_chat_projects() -> Response:
        return json_response(HTTPStatus.OK, list_chat_projects())

    @app.post("/api/chat/projects")
    @app.post("/api/chat/project")
    async def api_create_chat_project(request: Request) -> Response:
        return json_response(HTTPStatus.CREATED, create_chat_project(await read_json_body(request)))

    @app.post("/api/chat/project/rename")
    @app.post("/api/chat/projects/rename")
    async def api_rename_chat_project(request: Request) -> Response:
        payload = rename_chat_project(await read_json_body(request))
        sync = sync_chat_project_session_metadata(payload["project"]["id"], project_name=payload["project"]["name"])
        return json_response(HTTPStatus.OK, {**payload, **sync})

    @app.post("/api/chat/project/delete")
    @app.post("/api/chat/projects/delete")
    async def api_delete_chat_project(request: Request) -> Response:
        payload = delete_chat_project(await read_json_body(request))
        sync = sync_chat_project_session_metadata(payload["projectId"], clear=True)
        return json_response(HTTPStatus.OK, {**payload, **sync})

    @app.post("/api/chat/tool-undo")
    async def api_undo_chat_tool_snapshot(request: Request) -> Response:
        return json_response(HTTPStatus.OK, undo_chat_tool_snapshot(await read_json_body(request)))

    @app.post("/api/chat/tool-redo")
    async def api_redo_chat_tool_snapshot(request: Request) -> Response:
        return json_response(HTTPStatus.OK, redo_chat_tool_snapshot(await read_json_body(request)))

    @app.post("/api/chat/tool-snapshots/cleanup")
    async def api_cleanup_chat_tool_snapshots(request: Request) -> Response:
        return json_response(HTTPStatus.OK, cleanup_chat_tool_snapshots(await read_json_body(request)))

    @app.post("/api/chat/tool-approvals/respond")
    async def api_respond_chat_tool_approval(request: Request) -> Response:
        return json_response(HTTPStatus.OK, respond_chat_tool_approval(await read_json_body(request)))

    @app.post("/api/chat/session/model")
    async def api_update_chat_session_model(request: Request) -> Response:
        return json_response(HTTPStatus.OK, update_chat_session_model(await read_json_body(request)))

    @app.get("/api/chat/sessions")
    async def api_list_chat_sessions(request: Request) -> Response:
        return json_response(HTTPStatus.OK, list_chat_sessions(query_params(request)))

    @app.get("/api/chat/session")
    async def api_get_chat_session(request: Request) -> Response:
        return json_response(HTTPStatus.OK, get_chat_session(query_params(request)))

    @app.get("/api/chat/tool-snapshots")
    async def api_list_chat_tool_snapshots(request: Request) -> Response:
        return json_response(HTTPStatus.OK, list_chat_tool_snapshots(query_params(request)))

    @app.get("/api/chat/tool-snapshot-diff")
    async def api_preview_chat_tool_snapshot(request: Request) -> Response:
        return json_response(HTTPStatus.OK, preview_chat_tool_snapshot(query_params(request)))

    @app.get("/api/chat/tool-approvals")
    async def api_list_chat_tool_approvals(request: Request) -> Response:
        return json_response(HTTPStatus.OK, list_chat_tool_approvals(query_params(request)))

    @app.get("/api/debug/runs")
    async def api_list_debug_runs(request: Request) -> Response:
        return json_response(HTTPStatus.OK, list_debug_runs(query_params(request)))

    @app.get("/api/debug/runs/{request_id:path}")
    async def api_get_debug_run(request: Request) -> Response:
        request_id = unquote(request.url.path.rsplit("/", 1)[-1])
        return json_response(HTTPStatus.OK, get_debug_run(request_id))

    @app.get("/api/chat/progress")
    async def api_get_chat_progress(request: Request) -> Response:
        return json_response(HTTPStatus.OK, get_chat_progress(query_params(request)))

    @app.get("/api/chat/context")
    async def api_get_chat_context_status(request: Request) -> Response:
        return json_response(HTTPStatus.OK, get_chat_context_status(query_params(request)))

    @app.get("/api/memory")
    async def api_list_memory() -> Response:
        return json_response(HTTPStatus.OK, list_memory())

    @app.post("/api/memory")
    async def api_update_memory(request: Request) -> Response:
        return json_response(HTTPStatus.OK, update_memory(await read_json_body(request)))

    @app.get("/api/scratchpads")
    async def api_read_scratchpads() -> Response:
        return json_response(HTTPStatus.OK, read_scratchpads())

    @app.post("/api/scratchpads")
    async def api_write_scratchpads(request: Request) -> Response:
        return json_response(HTTPStatus.OK, write_scratchpads(await read_json_body(request)))

    @app.get("/api/settings/ai")
    async def api_get_ai_settings() -> Response:
        return json_response(HTTPStatus.OK, get_ai_settings())

    @app.post("/api/settings/ai")
    async def api_update_ai_settings(request: Request) -> Response:
        return json_response(HTTPStatus.OK, update_ai_settings(await read_json_body(request)))

    @app.delete("/api/settings/ai/key")
    async def api_delete_ai_api_key(request: Request) -> Response:
        provider = first_param(query_params(request), "provider", "openai")
        return json_response(HTTPStatus.OK, delete_ai_api_key(provider))

    @app.get("/api/settings/tools")
    async def api_get_tool_settings() -> Response:
        return json_response(HTTPStatus.OK, get_tool_settings())

    @app.post("/api/settings/tools")
    async def api_update_tool_settings(request: Request) -> Response:
        return json_response(HTTPStatus.OK, update_tool_settings(await read_json_body(request)))

    @app.get("/api/settings/mcp")
    async def api_get_mcp_settings() -> Response:
        return json_response(HTTPStatus.OK, get_mcp_settings())

    @app.post("/api/settings/mcp")
    async def api_update_mcp_settings(request: Request) -> Response:
        return json_response(HTTPStatus.OK, update_mcp_settings(await read_json_body(request)))

    @app.post("/api/settings/mcp/test")
    async def api_test_mcp_server(request: Request) -> Response:
        return json_response(HTTPStatus.OK, test_mcp_server(await read_json_body(request)))

    @app.post("/api/settings/mcp/connect")
    async def api_connect_mcp_server(request: Request) -> Response:
        return json_response(HTTPStatus.OK, connect_mcp_server(await read_json_body(request)))

    @app.post("/api/settings/mcp/reconnect")
    async def api_reconnect_mcp_server(request: Request) -> Response:
        return json_response(HTTPStatus.OK, reconnect_mcp_server(await read_json_body(request)))

    @app.post("/api/settings/mcp/reset-circuit")
    async def api_reset_mcp_server_circuit(request: Request) -> Response:
        return json_response(HTTPStatus.OK, reset_mcp_server_circuit(await read_json_body(request)))

    @app.get("/api/settings/mcp/stderr-log")
    async def api_get_mcp_stderr_log(request: Request) -> Response:
        params = query_params(request)
        try:
            max_chars = int(first_param(params, "maxChars", first_param(params, "max_chars", "60000")))
        except (TypeError, ValueError):
            max_chars = 60000
        return json_response(HTTPStatus.OK, get_mcp_stderr_log(max_chars=max_chars))

    @app.get("/api/skills")
    async def api_list_skills(request: Request) -> Response:
        category = first_param(query_params(request), "category")
        return json_response(HTTPStatus.OK, list_skills(category=category))

    @app.get("/api/skills/view")
    async def api_view_skill(request: Request) -> Response:
        params = query_params(request)
        name = first_param(params, "name")
        file_path = first_param(params, "filePath", first_param(params, "file_path"))
        return json_response(HTTPStatus.OK, view_skill(name=name, file_path=file_path))

    @app.post("/api/skills/settings")
    async def api_update_skill_settings(request: Request) -> Response:
        return json_response(HTTPStatus.OK, update_skill_settings(await read_json_body(request)))

    @app.post("/api/skills/update")
    async def api_update_skill(request: Request) -> Response:
        return json_response(HTTPStatus.OK, update_skill(await read_json_body(request)))

    @app.get("/api/model/providers")
    async def api_get_model_providers() -> Response:
        return json_response(HTTPStatus.OK, get_model_providers())

    @app.get("/api/auth/codex/status")
    async def api_get_codex_auth_status() -> Response:
        return json_response(HTTPStatus.OK, get_codex_auth_status())

    @app.post("/api/auth/codex/start")
    async def api_start_codex_auth() -> Response:
        return json_response(HTTPStatus.OK, start_codex_auth())

    @app.post("/api/auth/codex/poll")
    async def api_poll_codex_auth(request: Request) -> Response:
        return json_response(HTTPStatus.OK, poll_codex_auth(await read_json_body(request)))

    @app.post("/api/auth/codex/logout")
    async def api_logout_codex_auth() -> Response:
        return json_response(HTTPStatus.OK, logout_codex_auth())

    @app.post("/api/open-local-file")
    async def api_open_local_file(request: Request) -> Response:
        if request.headers.get("X-Paper-Notes-Local-Action") != "open-local-file":
            raise AgentAPIError(
                HTTPStatus.FORBIDDEN,
                "missing_local_action_header",
                "Local file open requests require a trusted reader header.",
            )
        body = await read_json_body(request)
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
        return json_response(HTTPStatus.OK, {"success": True, "path": str(target)})

    @app.get("/api/media/{artifact_id}")
    async def api_get_media(artifact_id: str) -> Response:
        return get_media_response(artifact_id, download=False)

    @app.get("/api/media/{artifact_id}/download")
    async def api_download_media(artifact_id: str) -> Response:
        return get_media_response(artifact_id, download=True)

    @app.get("/api/media/{artifact_id}/{tail:path}")
    async def api_unknown_media_path(artifact_id: str, tail: str) -> Response:
        return text_response(HTTPStatus.NOT_FOUND, "Media not found.")

    @app.api_route("/", methods=["POST", "PATCH", "DELETE"])
    @app.api_route("/{path:path}", methods=["POST", "PATCH", "DELETE"])
    async def method_not_allowed(path: str = "") -> Response:
        return text_response(HTTPStatus.METHOD_NOT_ALLOWED, "Method not allowed")

    @app.api_route("/", methods=["GET", "HEAD"])
    @app.api_route("/{path:path}", methods=["GET", "HEAD"])
    async def static_files(request: Request, path: str = "") -> Response:
        return serve_static_path(request.url.path, head=request.method == "HEAD")

    return app


def get_media_response(artifact_id: str, *, download: bool) -> Response:
    try:
        media_store = get_agent_service().media_store
        artifact = media_store.require_artifact(artifact_id)
        body = media_store.read_bytes(artifact.id)
    except MediaStoreError as error:
        raise AgentAPIError(HTTPStatus.NOT_FOUND, "media_not_found", str(error)) from error

    headers = {"Content-Length": str(len(body))}
    if download:
        headers["Content-Disposition"] = content_disposition_attachment(artifact.file_name)
    return Response(content=body, media_type=artifact.mime_type, headers=headers)


app = create_app()


def main() -> None:
    display_host = "localhost" if HOST in {"127.0.0.1", "0.0.0.0"} else HOST
    print(f"Paper Notes is running at http://{display_host}:{PORT}", flush=True)
    uvicorn.run(app, host=HOST, port=PORT)


if __name__ == "__main__":
    main()
