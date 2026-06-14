from __future__ import annotations

import asyncio
import json
from http import HTTPStatus
from typing import Any, AsyncIterator

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse

from agent_runtime import AgentService, AgentServiceRequest
from agent_runtime.service import ATTACHMENT_ONLY_MESSAGE
from agent_sessions import SessionNotFoundError
from app_infra.formatting import normalize_text
from media import MediaStore, MediaStoreError
from ui.backend.agent_api import get_agent_service, _metadata_payload


_MEDIA_STORE: MediaStore | None = None


class ChatAPIError(ValueError):
    def __init__(self, status: HTTPStatus, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code


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
    if not isinstance(body, dict):
        raise ChatAPIError(HTTPStatus.BAD_REQUEST, "invalid_body", "Request body must be a JSON object.")
    agent_service = service or get_agent_service()
    store = media_store or get_media_store()
    message = _request_message(body)
    attachments = _attachment_artifacts(body.get("attachments"), store)
    if not message and not attachments:
        raise ChatAPIError(HTTPStatus.BAD_REQUEST, "message_required", "Message is required.")

    session_id = _optional_text(body.get("sessionId") or body.get("session_id"))
    if _bool(body.get("editLatestUserMessage") or body.get("edit_latest_user_message")) and session_id:
        _truncate_latest_user_turn(agent_service, session_id)

    request = AgentServiceRequest(
        message=_message_content(message, attachments, store),
        session_id=session_id or None,
        title=_session_title(body, message),
        note_id=_optional_text(body.get("noteId") or body.get("note_id")) or None,
        provider=_optional_text(body.get("provider")),
        model=_optional_text(body.get("model")),
        system_prompt=_system_prompt(body),
        enable_tools=_bool(body.get("enableTools", body.get("enable_tools")), default=True),
        metadata=_request_metadata(body),
        run_config=body.get("runConfig") if isinstance(body.get("runConfig"), dict) else None,
        stream_mode=_optional_text(body.get("streamMode") or body.get("stream_mode")) or "values",
    )
    try:
        result = agent_service.run(request)
    except SessionNotFoundError as error:
        raise ChatAPIError(HTTPStatus.NOT_FOUND, "session_not_found", str(error)) from error
    except ValueError as error:
        raise ChatAPIError(HTTPStatus.BAD_REQUEST, "invalid_request", str(error)) from error

    visible_text = message or ATTACHMENT_ONLY_MESSAGE
    if attachments:
        session = _persist_user_attachment_metadata(
            agent_service,
            result.session_id,
            attachments=attachments,
            visible_text=visible_text,
            body=body,
        )
        result.session = session
        result.messages = session.messages
    return _chat_result_payload(result, request_id=_optional_text(body.get("requestId") or body.get("request_id")))


def upload_chat_attachment(
    body: Any,
    *,
    media_store: MediaStore | None = None,
) -> dict[str, Any]:
    if not isinstance(body, dict):
        raise ChatAPIError(HTTPStatus.BAD_REQUEST, "invalid_body", "Request body must be a JSON object.")
    attachment_data = _optional_text(body.get("data") or body.get("file") or body.get("image") or body.get("base64"))
    if not attachment_data:
        raise ChatAPIError(HTTPStatus.BAD_REQUEST, "attachment_required", "Attachment data is required.")
    file_name = _optional_text(body.get("fileName") or body.get("file_name") or body.get("name"))
    mime_type = _optional_text(body.get("mimeType") or body.get("mime_type") or body.get("type"))
    scope = _optional_text(body.get("sessionId") or body.get("session_id") or body.get("requestId") or body.get("request_id"))
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
    request_id = _optional_text(body.get("requestId") or body.get("request_id")) if isinstance(body, dict) else ""
    try:
        body_for_run = _prepare_stream_body(body)
        session_id = _optional_text(body_for_run.get("sessionId") or body_for_run.get("session_id"))
        session = get_agent_service().session_store.get_session(session_id) if session_id else None
        yield _sse_frame("start", {
            "requestId": request_id,
            "sessionId": session_id,
            "session": _metadata_payload(session.metadata) if session is not None else None,
        })
        payload = await asyncio.to_thread(handle_chat_request, body_for_run)
        payload["requestId"] = request_id or payload.get("requestId", "")
        yield _sse_frame("final", payload)
        yield _sse_frame("done", {"requestId": payload.get("requestId", ""), "sessionId": payload.get("sessionId", "")})
    except Exception as error:
        code = error.code if isinstance(error, ChatAPIError) else "chat_failed"
        yield _sse_frame("error", {"requestId": request_id, "code": code, "error": str(error) or "Chat failed."})
        yield _sse_frame("done", {"requestId": request_id})


def _prepare_stream_body(body: Any) -> dict[str, Any]:
    if not isinstance(body, dict):
        raise ChatAPIError(HTTPStatus.BAD_REQUEST, "invalid_body", "Request body must be a JSON object.")
    prepared = dict(body)
    session_id = _optional_text(prepared.get("sessionId") or prepared.get("session_id"))
    if session_id or _bool(prepared.get("editLatestUserMessage") or prepared.get("edit_latest_user_message")):
        return prepared
    message = _request_message(prepared)
    if not message and not prepared.get("attachments"):
        return prepared
    service = get_agent_service()
    session = service.session_store.create_session(
        title=_session_title(prepared, message),
        note_id=_optional_text(prepared.get("noteId") or prepared.get("note_id")) or None,
        provider=_optional_text(prepared.get("provider")) or None,
        model=_optional_text(prepared.get("model")) or None,
        metadata=_request_metadata(prepared),
    )
    prepared["sessionId"] = session.metadata.session_id
    prepared["session_id"] = session.metadata.session_id
    return prepared


def _chat_result_payload(result: Any, *, request_id: str = "") -> dict[str, Any]:
    response_text = _content_text(result.response)
    messages = [_public_chat_message(message) for message in result.messages]
    messages = [message for message in messages if message is not None]
    assistant_message: dict[str, Any] = {
        "role": "assistant",
        "content": response_text,
        "text": response_text,
        "error": bool(result.error),
    }
    return {
        "success": True,
        "requestId": request_id,
        "sessionId": result.session_id,
        "session": _metadata_payload(result.session.metadata),
        "createdSession": bool(result.created_session),
        "completed": bool(result.completed),
        "cancelled": False,
        "response": response_text,
        "message": assistant_message,
        "messages": messages,
        "events": [],
        "turns": 1,
        "pendingToolCalls": [],
        "artifacts": [],
        "error": result.error,
    }


def _public_chat_message(message: dict[str, Any]) -> dict[str, Any] | None:
    role = _optional_text(message.get("role"))
    if role == "tool":
        return None
    if role == "assistant" and message.get("tool_calls"):
        return None
    if role not in {"user", "assistant", "divider"}:
        return None
    payload = dict(message)
    payload["text"] = _content_text(payload.get("text") or payload.get("content"))
    return payload


def _persist_user_attachment_metadata(
    service: AgentService,
    session_id: str,
    *,
    attachments: list[dict[str, Any]],
    visible_text: str,
    body: dict[str, Any],
) -> Any:
    session = service.session_store.require_session(session_id)
    messages = [dict(message) for message in session.messages]
    for index in range(len(messages) - 1, -1, -1):
        if messages[index].get("role") != "user":
            continue
        metadata = dict(messages[index].get("metadata") or {})
        request_metadata = body.get("metadata") if isinstance(body.get("metadata"), dict) else {}
        metadata.update(request_metadata)
        generation = body.get("imageGeneration") or body.get("image_generation")
        if isinstance(generation, dict):
            metadata["generation"] = generation
        selected_text_context = request_metadata.get("selectedTextContext") if isinstance(request_metadata, dict) else None
        if isinstance(selected_text_context, dict):
            metadata["selectedTextContext"] = selected_text_context
        messages[index]["metadata"] = metadata
        messages[index]["attachments"] = attachments
        messages[index]["text"] = visible_text
        break
    return service.session_store.replace_messages(session_id, messages)


def _message_content(message: str, attachments: list[dict[str, Any]], media_store: MediaStore) -> Any:
    attachment_context = _attachment_context(attachments, media_store)
    text = message or ATTACHMENT_ONLY_MESSAGE
    if attachment_context:
        text = f"{text}\n\n{attachment_context}"
    image_parts = _image_content_parts(attachments, media_store)
    if not image_parts:
        return text
    return [{"type": "text", "text": text}, *image_parts]


def _attachment_context(attachments: list[dict[str, Any]], media_store: MediaStore) -> str:
    sections: list[str] = []
    for artifact in attachments:
        if _is_image_artifact(artifact):
            sections.append(f"- Image: {artifact.get('fileName') or artifact.get('id')} ({artifact.get('mimeType')})")
            continue
        try:
            extracted = media_store.extracted_text_for_artifact(str(artifact.get("id") or ""))
        except Exception:
            extracted = ""
        heading = f"Attachment: {artifact.get('fileName') or artifact.get('id')} ({artifact.get('mimeType')})"
        sections.append(f"{heading}\n{extracted}".rstrip())
    return "\n\n".join(section for section in sections if section).strip()


def _image_content_parts(attachments: list[dict[str, Any]], media_store: MediaStore) -> list[dict[str, Any]]:
    parts: list[dict[str, Any]] = []
    for artifact in attachments:
        if not _is_image_artifact(artifact):
            continue
        try:
            data_url = media_store.data_url_for_artifact(str(artifact.get("id") or ""))
        except Exception:
            continue
        parts.append({"type": "image_url", "image_url": {"url": data_url}})
    return parts


def _attachment_artifacts(raw_attachments: Any, media_store: MediaStore) -> list[dict[str, Any]]:
    if not isinstance(raw_attachments, list):
        return []
    artifacts: list[dict[str, Any]] = []
    for raw in raw_attachments:
        artifact_id = _optional_text(raw.get("id") if isinstance(raw, dict) else raw)
        if not artifact_id:
            continue
        try:
            artifacts.append(media_store.public_artifact(artifact_id))
        except MediaStoreError as error:
            raise ChatAPIError(HTTPStatus.BAD_REQUEST, "invalid_attachment", str(error)) from error
    return artifacts


def _truncate_latest_user_turn(service: AgentService, session_id: str) -> None:
    session = service.session_store.require_session(session_id)
    messages = list(session.messages)
    latest_user = -1
    for index, message in enumerate(messages):
        if message.get("role") == "user":
            latest_user = index
    if latest_user >= 0:
        service.session_store.replace_messages(session_id, messages[:latest_user])


def _request_message(body: dict[str, Any]) -> str:
    return _optional_text(body.get("message") if "message" in body else body.get("text"))


def _request_metadata(body: dict[str, Any]) -> dict[str, Any]:
    metadata = dict(body.get("metadata")) if isinstance(body.get("metadata"), dict) else {}
    note_id = _optional_text(body.get("noteId") or body.get("note_id"))
    note_title = _optional_text(body.get("noteTitle") or body.get("note_title"))
    if note_id:
        metadata.setdefault("originNoteId", note_id)
        metadata.setdefault("currentNoteId", note_id)
    if note_title:
        metadata.setdefault("originNoteTitle", note_title)
        metadata.setdefault("currentNoteTitle", note_title)
    request_id = _optional_text(body.get("requestId") or body.get("request_id"))
    if request_id:
        metadata.setdefault("requestId", request_id)
    return metadata


def _session_title(body: dict[str, Any], message: str) -> str:
    explicit = _optional_text(body.get("title") or body.get("sessionTitle") or body.get("session_title"))
    if explicit:
        return explicit[:80]
    text = normalize_text(message).splitlines()[0] if message else "Attachment chat"
    return (text[:80] or "New chat")


def _system_prompt(body: dict[str, Any]) -> str | None:
    context = body.get("context") if isinstance(body.get("context"), dict) else {}
    parts: list[str] = []
    note_title = _optional_text(body.get("noteTitle") or body.get("note_title"))
    if note_title:
        parts.append(f"Current paper/note: {note_title}")
    current_page = _optional_text(body.get("currentPage") or context.get("currentPage") or context.get("current_page"))
    if current_page:
        parts.append(f"Current page: {current_page}")
    selection = _optional_text(body.get("selectionText") or body.get("selection_text") or context.get("selectionText") or context.get("selection_text"))
    if selection:
        parts.append(f"Selected text:\n{selection}")
    return "\n\n".join(parts) or None


def _is_image_artifact(artifact: dict[str, Any]) -> bool:
    return _optional_text(artifact.get("kind")) == "image" or _optional_text(artifact.get("mimeType")).startswith("image/")


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text") or item.get("content")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(parts)
    return str(content or "")


async def _json_body(request: Request) -> Any:
    try:
        return await request.json()
    except Exception:
        return {}


def _chat_error_response(error: Exception) -> JSONResponse:
    if isinstance(error, ChatAPIError):
        return JSONResponse(
            {"success": False, "code": error.code, "error": str(error)},
            status_code=int(error.status),
        )
    return JSONResponse(
        {"success": False, "code": "chat_failed", "error": str(error) or "Chat failed."},
        status_code=HTTPStatus.BAD_REQUEST,
    )


def _sse_frame(event: str, payload: dict[str, Any]) -> bytes:
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    lines = [f"event: {event}"]
    lines.extend(f"data: {line}" for line in body.splitlines() or ["{}"])
    return ("\n".join(lines) + "\n\n").encode("utf-8")


def _optional_text(value: Any) -> str:
    return str(value or "").strip()


def _bool(value: Any, *, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)
