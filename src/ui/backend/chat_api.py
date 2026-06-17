from __future__ import annotations

import asyncio
import json
import queue
import threading
from dataclasses import dataclass
from http import HTTPStatus
from typing import Any, AsyncIterator

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse

from agent_runtime import AgentService, AgentServiceRequest
from agent_sessions import SessionNotFoundError
from media import MediaStore, MediaStoreError
from ui.backend.agent_api import get_agent_service, _metadata_payload
from ui.backend.api_errors import ChatAPIError, chat_error_response as _chat_error_response
from ui.backend.chat_payloads import (
    bool_value as _bool,
    chat_result_payload,
    context_payload as _context_payload,
    empty_context_payload as _empty_context_payload,
    last_compaction_marker_message as _last_compaction_marker_message,
    model_options_from_body as _model_options_from_body,
    optional_text as _optional_text,
    optional_text_list as _optional_text_list,
    public_chat_message as _public_chat_message,
    query_value as _query_value,
)
from ui.backend.chat_preparation import (
    persist_latest_user_request_metadata as _persist_latest_user_request_metadata,
    prepare_chat_run as _prepare_chat_run,
    prepare_stream_body as _prepare_stream_body,
)


_MEDIA_STORE: MediaStore | None = None
_STREAM_QUEUE_DONE = object()


@dataclass(slots=True)
class _QueuedSSE:
    event: str
    payload: dict[str, Any]


def get_media_store() -> MediaStore:
    global _MEDIA_STORE
    if _MEDIA_STORE is None:
        _MEDIA_STORE = MediaStore()
    return _MEDIA_STORE


def set_media_store(store: MediaStore | None) -> None:
    global _MEDIA_STORE
    _MEDIA_STORE = store


def register_chat_routes(app: FastAPI) -> None:
    @app.post("/api/chat")
    async def api_chat(request: Request) -> JSONResponse:
        try:
            return JSONResponse(handle_chat_request(await _json_body(request)))
        except Exception as error:
            return _chat_error_response(error)

    @app.post("/api/chat/stream")
    async def api_chat_stream(request: Request) -> StreamingResponse:
        body = await _json_body(request)
        return StreamingResponse(
            _chat_sse_events(body),
            media_type="text/event-stream; charset=utf-8",
            headers={"Cache-Control": "no-store", "Connection": "close"},
        )

    @app.post("/api/chat/attachments")
    async def api_upload_chat_attachment(request: Request) -> JSONResponse:
        try:
            return JSONResponse(upload_chat_attachment(await _json_body(request)), status_code=HTTPStatus.CREATED)
        except Exception as error:
            return _chat_error_response(error)

    @app.get("/api/chat/context")
    async def api_chat_context(request: Request) -> JSONResponse:
        try:
            return JSONResponse(chat_context_status(request.query_params))
        except Exception as error:
            return _chat_error_response(error)

    @app.post("/api/chat/compress")
    async def api_chat_compress(request: Request) -> JSONResponse:
        try:
            return JSONResponse(compact_chat_session(await _json_body(request)))
        except Exception as error:
            return _chat_error_response(error)

    @app.get("/api/media/{artifact_id}")
    async def api_get_media(artifact_id: str) -> Response:
        try:
            return media_response(artifact_id, download=False)
        except Exception as error:
            return _chat_error_response(error)

    @app.get("/api/media/{artifact_id}/download")
    async def api_download_media(artifact_id: str) -> Response:
        try:
            return media_response(artifact_id, download=True)
        except Exception as error:
            return _chat_error_response(error)


def handle_chat_request(
    body: Any,
    *,
    service: AgentService | None = None,
    media_store: MediaStore | None = None,
) -> dict[str, Any]:
    prepared = _prepare_chat_run(
        body,
        service=service,
        media_store=media_store or get_media_store(),
    )
    agent_service = prepared.service
    request = prepared.request
    try:
        result = agent_service.run(request)
    except SessionNotFoundError as error:
        raise ChatAPIError(HTTPStatus.NOT_FOUND, "session_not_found", str(error)) from error
    except ValueError as error:
        raise ChatAPIError(HTTPStatus.BAD_REQUEST, "invalid_request", str(error)) from error

    session = _persist_latest_user_request_metadata(
        agent_service,
        result.session_id,
        attachments=prepared.attachments,
        visible_text=prepared.visible_text,
        body=body,
    )
    result.session = session
    result.messages = session.messages
    return chat_result_payload(
        result,
        request_id=_optional_text(body.get("requestId")),
        session_payload=_metadata_payload(result.session.metadata),
    )


def upload_chat_attachment(
    body: Any,
    *,
    media_store: MediaStore | None = None,
) -> dict[str, Any]:
    if not isinstance(body, dict):
        raise ChatAPIError(HTTPStatus.BAD_REQUEST, "invalid_body", "Request body must be a JSON object.")
    attachment_data = _optional_text(body.get("data"))
    if not attachment_data:
        raise ChatAPIError(HTTPStatus.BAD_REQUEST, "attachment_required", "Attachment data is required.")
    file_name = _optional_text(body.get("fileName"))
    mime_type = _optional_text(body.get("mimeType"))
    scope = _optional_text(body.get("sessionId") or body.get("requestId"))
    metadata = dict(body.get("metadata")) if isinstance(body.get("metadata"), dict) else {}
    try:
        artifact = (media_store or get_media_store()).create_upload(
            attachment_data,
            file_name=file_name,
            scope=scope,
            mime_type=mime_type,
            metadata=metadata,
        )
    except (MediaStoreError, ValueError) as error:
        raise ChatAPIError(HTTPStatus.BAD_REQUEST, "invalid_attachment", str(error)) from error
    return {"success": True, "artifact": artifact.to_dict()}


def chat_context_status(
    query: Any,
    *,
    service: AgentService | None = None,
) -> dict[str, Any]:
    agent_service = service or get_agent_service()
    session_id = _optional_text(_query_value(query, "sessionId"))
    if not session_id:
        return {"success": True, "context": _empty_context_payload(query)}
    try:
        status = agent_service.context_status(
            session_id=session_id,
            provider=_optional_text(_query_value(query, "provider")),
            model=_optional_text(_query_value(query, "model")),
            enable_tools=_bool(_query_value(query, "enableTools"), default=True),
        )
        session = agent_service.session_store.require_session(session_id)
    except SessionNotFoundError as error:
        raise ChatAPIError(HTTPStatus.NOT_FOUND, "session_not_found", str(error)) from error
    return {
        "success": True,
        "context": _context_payload(status.to_dict(), session.messages),
    }


def compact_chat_session(
    body: Any,
    *,
    service: AgentService | None = None,
) -> dict[str, Any]:
    if not isinstance(body, dict):
        raise ChatAPIError(HTTPStatus.BAD_REQUEST, "invalid_body", "Request body must be a JSON object.")
    session_id = _optional_text(body.get("sessionId"))
    if not session_id:
        raise ChatAPIError(HTTPStatus.BAD_REQUEST, "session_required", "sessionId is required.")
    agent_service = service or get_agent_service()
    try:
        result = agent_service.compact_session(
            session_id=session_id,
            focus=_optional_text(body.get("focus")),
            provider=_optional_text(body.get("provider")),
            model=_optional_text(body.get("model")),
            enable_tools=_bool(body.get("enableTools"), default=True),
            model_options=_model_options_from_body(body),
            disabled_tools=tuple(_optional_text_list(body.get("disabledTools"))),
        )
    except SessionNotFoundError as error:
        raise ChatAPIError(HTTPStatus.NOT_FOUND, "session_not_found", str(error)) from error
    except ValueError as error:
        raise ChatAPIError(HTTPStatus.BAD_REQUEST, "invalid_request", str(error)) from error
    marker = _last_compaction_marker_message(result.session.messages)
    return {
        "success": True,
        "sessionId": result.session_id,
        "session": _metadata_payload(result.session.metadata),
        "compressed": result.compressed,
        "context": _context_payload(result.context.to_dict(), result.session.messages),
        "events": list(result.events),
        "warning": result.warning,
        "message": _public_chat_message(marker) if marker else None,
    }


def media_response(artifact_id: str, *, download: bool = False, media_store: MediaStore | None = None) -> FileResponse:
    store = media_store or get_media_store()
    try:
        artifact = store.require_artifact(artifact_id)
        path = store.path_for(artifact.id)
    except MediaStoreError as error:
        raise ChatAPIError(HTTPStatus.NOT_FOUND, "media_not_found", str(error)) from error
    return FileResponse(
        path,
        media_type=artifact.mime_type or "application/octet-stream",
        filename=artifact.file_name if download else None,
        content_disposition_type="attachment" if download else "inline",
    )


async def _chat_sse_events(body: Any) -> AsyncIterator[bytes]:
    request_id = _optional_text(body.get("requestId")) if isinstance(body, dict) else ""
    try:
        body_for_run = _prepare_stream_body(body)
        prepared = _prepare_chat_run(body_for_run, media_store=get_media_store())
        agent_service = prepared.service
        request = prepared.request
        session_id = request.session_id or ""
        session = agent_service.session_store.get_session(session_id) if session_id else None
        events = _start_chat_stream_worker(
            agent_service,
            request,
            attachments=prepared.attachments,
            visible_text=prepared.visible_text,
            body_for_run=body_for_run,
            request_id=request_id,
            session_id=session_id,
        )
        yield _sse_frame("start", {
            "requestId": request_id,
            "sessionId": session_id,
            "session": _metadata_payload(session.metadata) if session is not None else None,
        })
        while True:
            queued = await asyncio.to_thread(events.get)
            if queued is _STREAM_QUEUE_DONE:
                break
            if isinstance(queued, _QueuedSSE):
                yield _sse_frame(queued.event, queued.payload)
    except Exception as error:
        code = error.code if isinstance(error, ChatAPIError) else "chat_failed"
        yield _sse_frame("error", {"requestId": request_id, "code": code, "error": str(error) or "Chat failed."})
        yield _sse_frame("done", {"requestId": request_id})


def _start_chat_stream_worker(
    agent_service: AgentService,
    request: AgentServiceRequest,
    *,
    attachments: list[dict[str, Any]],
    visible_text: str,
    body_for_run: dict[str, Any],
    request_id: str,
    session_id: str,
) -> queue.Queue[Any]:
    events: queue.Queue[Any] = queue.Queue()

    def enqueue(event: str, payload: dict[str, Any]) -> None:
        events.put(_QueuedSSE(event, payload))

    def worker() -> None:
        final_payload: dict[str, Any] | None = None
        try:
            for stream_event in agent_service.stream(request):
                if stream_event.event == "final":
                    result = stream_event.data.get("result")
                    persisted_session = _persist_latest_user_request_metadata(
                        agent_service,
                        result.session_id,
                        attachments=attachments,
                        visible_text=visible_text,
                        body=body_for_run,
                    )
                    result.session = persisted_session
                    result.messages = persisted_session.messages
                    final_payload = chat_result_payload(
                        result,
                        request_id=request_id,
                        session_payload=_metadata_payload(result.session.metadata),
                    )
                    enqueue("final", final_payload)
                    continue
                payload = dict(stream_event.data)
                payload.setdefault("requestId", request_id)
                payload.setdefault("sessionId", session_id)
                enqueue(stream_event.event, payload)
            enqueue("done", {
                "requestId": request_id,
                "sessionId": final_payload.get("sessionId", session_id) if final_payload else session_id,
            })
        except Exception as error:
            code = error.code if isinstance(error, ChatAPIError) else "chat_failed"
            enqueue("error", {"requestId": request_id, "code": code, "error": str(error) or "Chat failed."})
            enqueue("done", {"requestId": request_id, "sessionId": session_id})
        finally:
            events.put(_STREAM_QUEUE_DONE)

    threading.Thread(target=worker, name=f"paper-notes-chat-{request_id or 'run'}", daemon=True).start()
    return events


async def _json_body(request: Request) -> Any:
    try:
        return await request.json()
    except Exception:
        return {}


def _sse_frame(event: str, payload: dict[str, Any]) -> bytes:
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    lines = [f"event: {event}"]
    lines.extend(f"data: {line}" for line in body.splitlines() or ["{}"])
    return ("\n".join(lines) + "\n\n").encode("utf-8")
