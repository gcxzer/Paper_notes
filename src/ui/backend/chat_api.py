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

from agent_prompts import AgentPromptContext, build_agent_instructions
from agent_runtime import AgentService, AgentServiceRequest
from agent_runtime.service import ATTACHMENT_ONLY_MESSAGE
from agent_sessions import SessionNotFoundError
from app_infra.formatting import normalize_text
from media import MediaStore, MediaStoreError
from ui.backend.agent_api import get_agent_service, _metadata_payload


_MEDIA_STORE: MediaStore | None = None
_STREAM_QUEUE_DONE = object()


@dataclass(slots=True)
class _QueuedSSE:
    event: str
    payload: dict[str, Any]


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
    agent_service, request, attachments, visible_text = _prepare_chat_run(
        body,
        service=service,
        media_store=media_store,
    )
    try:
        result = agent_service.run(request)
    except SessionNotFoundError as error:
        raise ChatAPIError(HTTPStatus.NOT_FOUND, "session_not_found", str(error)) from error
    except ValueError as error:
        raise ChatAPIError(HTTPStatus.BAD_REQUEST, "invalid_request", str(error)) from error

    session = _persist_latest_user_request_metadata(
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


def chat_context_status(
    query: Any,
    *,
    service: AgentService | None = None,
) -> dict[str, Any]:
    agent_service = service or get_agent_service()
    session_id = _optional_text(_query_value(query, "sessionId", "session_id"))
    if not session_id:
        return {"success": True, "context": _empty_context_payload(query)}
    try:
        status = agent_service.context_status(
            session_id=session_id,
            provider=_optional_text(_query_value(query, "provider")),
            model=_optional_text(_query_value(query, "model")),
            enable_tools=_bool(_query_value(query, "enableTools", "enable_tools"), default=True),
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
    session_id = _optional_text(body.get("sessionId") or body.get("session_id"))
    if not session_id:
        raise ChatAPIError(HTTPStatus.BAD_REQUEST, "session_required", "sessionId is required.")
    agent_service = service or get_agent_service()
    try:
        result = agent_service.compact_session(
            session_id=session_id,
            focus=_optional_text(body.get("focus")),
            provider=_optional_text(body.get("provider")),
            model=_optional_text(body.get("model")),
            enable_tools=_bool(body.get("enableTools", body.get("enable_tools")), default=True),
            model_options=_request_model_options(body),
            disabled_tools=tuple(_optional_text_list(body.get("disabledTools") or body.get("disabled_tools"))),
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
    request_id = _optional_text(body.get("requestId") or body.get("request_id")) if isinstance(body, dict) else ""
    try:
        body_for_run = _prepare_stream_body(body)
        agent_service, request, attachments, visible_text = _prepare_chat_run(body_for_run)
        session_id = request.session_id or ""
        session = agent_service.session_store.get_session(session_id) if session_id else None
        events = _start_chat_stream_worker(
            agent_service,
            request,
            attachments=attachments,
            visible_text=visible_text,
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
                    final_payload = _chat_result_payload(result, request_id=request_id)
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


def _prepare_chat_run(
    body: Any,
    *,
    service: AgentService | None = None,
    media_store: MediaStore | None = None,
) -> tuple[AgentService, AgentServiceRequest, list[dict[str, Any]], str]:
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

    enable_tools = _bool(body.get("enableTools", body.get("enable_tools")), default=True)
    model_options = _request_model_options(body)
    model_options["_write_note_media_store"] = store
    model_options["_paper_notes_attachments"] = attachments
    if session_id:
        model_options["_paper_notes_session_id"] = session_id
    image_generation = _image_generation_options(body)
    if image_generation:
        model_options["_paper_notes_image_generation"] = image_generation
    file_generation = _file_generation_options(body)
    if file_generation:
        model_options["_paper_notes_file_generation"] = file_generation
    request = AgentServiceRequest(
        message=_message_content(message, attachments, store),
        session_id=session_id or None,
        title=_session_title(body, message),
        note_id=_optional_text(body.get("noteId") or body.get("note_id")) or None,
        provider=_optional_text(body.get("provider")),
        model=_optional_text(body.get("model")),
        system_prompt=None,
        enable_tools=enable_tools,
        metadata=_request_metadata(body),
        model_options=model_options,
        disabled_tools=tuple(_optional_text_list(body.get("disabledTools") or body.get("disabled_tools"))),
        run_config=body.get("runConfig") if isinstance(body.get("runConfig"), dict) else None,
        stream_mode=_optional_text(body.get("streamMode") or body.get("stream_mode")) or "values",
    )
    prompt_session = agent_service.session_store.get_session(session_id) if session_id else None
    prompt_model_config = agent_service._model_config_for_request(request, session=prompt_session)
    request.system_prompt = _system_prompt(
        body,
        tools=agent_service._tools_for_request(request, model_config=prompt_model_config, session=prompt_session),
        model=request.model,
    )
    return agent_service, request, attachments, message or ATTACHMENT_ONLY_MESSAGE


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
    artifacts = _latest_assistant_artifacts(messages)
    assistant_message: dict[str, Any] = {
        "role": "assistant",
        "content": response_text,
        "text": response_text,
        "error": bool(result.error),
    }
    if artifacts:
        assistant_message["artifacts"] = artifacts
    if getattr(result, "run_trace", None):
        assistant_message["runTrace"] = result.run_trace
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
        "events": list(getattr(result, "events", []) or []),
        "runTrace": getattr(result, "run_trace", None),
        "turns": 1,
        "pendingToolCalls": [],
        "artifacts": artifacts,
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
    artifacts = _message_artifacts(payload)
    if artifacts:
        payload["artifacts"] = artifacts
    if role == "divider":
        metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
        payload["markerType"] = _optional_text(metadata.get("type"))
        payload["focus"] = _optional_text(metadata.get("focus"))
        payload["warning"] = _optional_text(metadata.get("warning"))
    return payload


def _query_value(query: Any, *keys: str) -> Any:
    for key in keys:
        if hasattr(query, "get"):
            value = query.get(key)
            if value is not None:
                return value
    return None


def _empty_context_payload(query: Any) -> dict[str, Any]:
    provider = _optional_text(_query_value(query, "provider"))
    model = _optional_text(_query_value(query, "model"))
    return {
        "sessionId": "",
        "provider": provider,
        "model": model,
        "contextLength": 0,
        "tokensUsed": 0,
        "estimatedRequestTokens": 0,
        "messageTokens": 0,
        "toolSchemaTokens": 0,
        "actualInputTokens": 0,
        "actualOutputTokens": 0,
        "actualTotalTokens": 0,
        "actualUsageAvailable": False,
        "usageUpdatedAt": "",
        "usageRequestId": "",
        "remainingTokens": 0,
        "thresholdTokens": 0,
        "percentFull": 0,
        "thresholdPercent": 0,
        "messageCount": 0,
        "compactionEnabled": False,
        "compactionReady": False,
        "summaryAvailable": False,
        "compressionCount": 0,
        "lastCompressedAt": "",
        "lastCompressionError": "",
        "fallbackUsed": False,
    }


def _context_payload(status: dict[str, Any], messages: list[dict[str, Any]]) -> dict[str, Any]:
    context_window = int(status.get("contextWindow") or status.get("contextLength") or 0)
    estimated_tokens = int(status.get("estimatedTokens") or status.get("tokensUsed") or 0)
    actual_input_tokens = int(status.get("actualInputTokens") or 0)
    actual_usage_available = bool(status.get("actualUsageAvailable") or actual_input_tokens > 0)
    display_tokens = actual_input_tokens if actual_usage_available and actual_input_tokens > 0 else estimated_tokens
    threshold_tokens = int(status.get("compactionTriggerTokens") or status.get("thresholdTokens") or 0)
    compression_count = _compaction_marker_count(messages)
    summary_available = _has_summary_message(messages)
    threshold_percent = round((threshold_tokens / context_window) * 100) if context_window > 0 and threshold_tokens > 0 else 0
    percent_full = round((display_tokens / context_window) * 100) if context_window > 0 and display_tokens > 0 else 0
    return {
        **status,
        "contextLength": context_window,
        "tokensUsed": display_tokens,
        "requestTokens": display_tokens,
        "estimatedRequestTokens": estimated_tokens,
        "actualInputTokens": actual_input_tokens,
        "actualOutputTokens": int(status.get("actualOutputTokens") or 0),
        "actualTotalTokens": int(status.get("actualTotalTokens") or 0),
        "actualUsageAvailable": actual_usage_available,
        "usageUpdatedAt": _optional_text(status.get("usageUpdatedAt")),
        "usageRequestId": _optional_text(status.get("usageRequestId")),
        "messageTokens": int(status.get("messageTokens") or 0),
        "instructionTokens": int(status.get("instructionTokens") or 0),
        "toolSchemaTokens": int(status.get("toolTokens") or status.get("toolSchemaTokens") or 0),
        "thresholdTokens": threshold_tokens,
        "percentFull": min(100, max(0, int(percent_full))),
        "thresholdPercent": threshold_percent,
        "messageCount": int(status.get("messageCount") or len(messages)),
        "compactionEnabled": bool(status.get("compactionEnabled", True)),
        "summaryAvailable": summary_available,
        "compressionCount": compression_count,
        "lastCompressedAt": _last_compaction_marker_time(messages),
        "lastCompressionError": "",
        "fallbackUsed": False,
    }


def _has_summary_message(messages: list[dict[str, Any]]) -> bool:
    return any(
        message.get("role") == "user"
        and isinstance(message.get("content"), str)
        and message["content"].strip().startswith("[summary]")
        for message in messages
    )


def _compaction_marker_count(messages: list[dict[str, Any]]) -> int:
    return sum(1 for message in messages if _is_compaction_marker(message))


def _last_compaction_marker_time(messages: list[dict[str, Any]]) -> str:
    for message in reversed(messages):
        if _is_compaction_marker(message):
            return _optional_text(message.get("created_at") or message.get("createdAt"))
    return ""


def _last_compaction_marker_message(messages: list[dict[str, Any]]) -> dict[str, Any] | None:
    for message in reversed(messages):
        if _is_compaction_marker(message):
            return message
    return None


def _is_compaction_marker(message: dict[str, Any]) -> bool:
    metadata = message.get("metadata")
    return message.get("role") == "divider" and isinstance(metadata, dict) and metadata.get("type") == "context_compaction_marker"


def _persist_latest_user_request_metadata(
    service: AgentService,
    session_id: str,
    *,
    attachments: list[dict[str, Any]],
    visible_text: str,
    body: dict[str, Any],
) -> Any:
    session = service.session_store.require_session(session_id)
    request_metadata = _user_message_request_metadata(body)
    if not attachments and not request_metadata:
        return session
    messages = [dict(message) for message in session.messages]
    for index in range(len(messages) - 1, -1, -1):
        if messages[index].get("role") != "user":
            continue
        metadata = dict(messages[index].get("metadata") or {})
        metadata.update(request_metadata)
        if metadata:
            messages[index]["metadata"] = metadata
        if attachments:
            messages[index]["attachments"] = attachments
            messages[index]["text"] = visible_text
        break
    return service.session_store.replace_messages(session_id, messages)


def _user_message_request_metadata(body: dict[str, Any]) -> dict[str, Any]:
    metadata = dict(body.get("metadata")) if isinstance(body.get("metadata"), dict) else {}
    generation = _request_generation_metadata(body)
    if generation:
        existing_generation = metadata.get("generation") if isinstance(metadata.get("generation"), dict) else {}
        metadata["generation"] = {**existing_generation, **generation}

    selected_text_context = body.get("selectedTextContext") or body.get("selected_text_context")
    if isinstance(selected_text_context, dict):
        metadata.setdefault("selectedTextContext", selected_text_context)
    if not isinstance(metadata.get("selectedTextContext"), dict):
        selection_text = _optional_text(body.get("selectionText") or body.get("selection_text"))
        if selection_text:
            context: dict[str, Any] = {"type": "selected_text", "text": selection_text}
            current_page = _optional_text(body.get("currentPage") or body.get("current_page"))
            if current_page:
                context["page"] = current_page
            metadata["selectedTextContext"] = context
    return metadata


def _request_generation_metadata(body: dict[str, Any]) -> dict[str, Any]:
    generation: dict[str, Any] = {}
    image_generation = _image_generation_options(body)
    if image_generation:
        generation["imageGeneration"] = image_generation
    file_generation = _file_generation_options(body)
    if file_generation:
        generation["fileGeneration"] = file_generation
    return generation


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


def _request_model_options(body: dict[str, Any]) -> dict[str, Any]:
    options: dict[str, Any] = {}
    for key in ("requestOptions", "request_options", "modelOptions", "model_options"):
        value = body.get(key)
        if isinstance(value, dict):
            options.update(value)
    return options


def _image_generation_options(body: dict[str, Any]) -> dict[str, Any]:
    value = body.get("imageGeneration") or body.get("image_generation")
    if not isinstance(value, dict) or value.get("enabled") is not True:
        return {}
    config = dict(value)
    config.setdefault("format", "png")
    return config


def _file_generation_options(body: dict[str, Any]) -> dict[str, Any]:
    value = body.get("fileGeneration") or body.get("file_generation")
    if not isinstance(value, dict) or value.get("enabled") is not True:
        return {}
    file_format = _optional_text(value.get("format")).lower() or "markdown"
    if file_format not in {"markdown", "text", "json", "csv", "html"}:
        file_format = "markdown"
    return {
        **dict(value),
        "enabled": True,
        "format": file_format,
        "mime_type": _mime_type_for_file_generation_format(file_format),
    }


def _mime_type_for_file_generation_format(file_format: str) -> str:
    return {
        "markdown": "text/markdown",
        "text": "text/plain",
        "json": "application/json",
        "csv": "text/csv",
        "html": "text/html",
    }.get(str(file_format or "").strip().lower(), "text/markdown")


def _latest_assistant_artifacts(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for message in reversed(messages):
        if message.get("role") != "assistant":
            continue
        artifacts = _message_artifacts(message)
        if artifacts:
            return artifacts
    return []


def _message_artifacts(message: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[Any] = []
    if isinstance(message.get("artifacts"), list):
        candidates.append(message.get("artifacts"))
    metadata = message.get("metadata") if isinstance(message.get("metadata"), dict) else {}
    response_metadata = metadata.get("response_metadata") if isinstance(metadata.get("response_metadata"), dict) else {}
    if isinstance(response_metadata.get("artifacts"), list):
        candidates.append(response_metadata.get("artifacts"))
    artifacts: list[dict[str, Any]] = []
    seen: set[str] = set()
    for candidate in candidates:
        if not isinstance(candidate, list):
            continue
        for artifact in candidate:
            if not isinstance(artifact, dict):
                continue
            artifact_id = str(artifact.get("id") or artifact.get("artifactId") or "")
            if artifact_id and artifact_id in seen:
                continue
            if artifact_id:
                seen.add(artifact_id)
            artifacts.append(dict(artifact))
    return artifacts


def _optional_text_list(value: Any) -> list[str]:
    if isinstance(value, str):
        candidates: list[Any] = value.split(",")
    elif isinstance(value, list):
        candidates = value
    else:
        return []
    return [text for item in candidates if (text := _optional_text(item))]


def _session_title(body: dict[str, Any], message: str) -> str:
    explicit = _optional_text(body.get("title") or body.get("sessionTitle") or body.get("session_title"))
    if explicit:
        return explicit[:80]
    text = normalize_text(message).splitlines()[0] if message else "Attachment chat"
    return (text[:80] or "New chat")


def _system_prompt(body: dict[str, Any], *, tools: list[Any] | None = None, model: str = "") -> str:
    resolved_tools = tools or []
    return build_agent_instructions(
        tools=resolved_tools,
        context=_agent_prompt_context(body),
        extra_instructions=_generation_mode_instructions(body, tools=resolved_tools),
        model=model,
    )


def _generation_mode_instructions(body: dict[str, Any], *, tools: list[Any] | None = None) -> str:
    instructions: list[str] = []
    tool_names = _tool_names(tools or [])
    if _image_generation_options(body):
        if "create_image_artifact" in tool_names:
            instructions.append(
                "The frontend image generation mode is selected for this turn. Treat it as a strong preference "
                "to create a downloadable image if the user request is compatible. Call `create_image_artifact` "
                "with `prompt`, `mode`, and optional `input_artifact_ids`; do not only describe the image. After "
                "the tool succeeds, briefly describe the result and mention the artifact id if useful, but do not "
                "write raw download URLs or sandbox links; the UI will attach the generated artifact card."
            )
        else:
            instructions.append(
                "The frontend image generation mode is selected for this turn, but `create_image_artifact` is not "
                "available for the current provider/model. Do not call unsupported image tools, do not fabricate "
                "image files, artifact ids, download URLs, Markdown image tags, data URLs, SVG/HTML stand-ins, or "
                "local temp paths. Respond directly to the user in natural language: explain that this current "
                "model cannot generate downloadable images in Paper Notes, and offer a useful text prompt, plan, "
                "or a suggestion to switch to an image-capable OpenAI or Codex model."
            )
    file_generation = _file_generation_options(body)
    if file_generation:
        mime_type = str(file_generation.get("mime_type") or "text/markdown")
        if "create_file_artifact" in tool_names:
            instructions.append(
                "The frontend file generation mode is selected for this turn. Treat it as a strong preference "
                "to create a downloadable file if the user request is compatible. Call `create_file_artifact` "
                "with `file_name`, `mime_type`, and `content`; prefer "
                f"`{mime_type}` unless the user asks for a different allowed text format. Do not only paste the "
                "file contents in chat. If the file content depends on the current paper, page, note, or selected "
                "text and you need more source material, first call the relevant local Paper Notes reading/search "
                "tool, then call `create_file_artifact` in the same turn. After the tool succeeds, briefly describe "
                "the file and mention the artifact id if useful, but do not write raw download URLs or sandbox links; "
                "the UI will attach the file card."
            )
        else:
            instructions.append(
                "The frontend file generation mode is selected for this turn, but `create_file_artifact` is not "
                "available. Do not fabricate artifact ids, download URLs, sandbox links, or local paths. Respond "
                "directly in chat, explain that a downloadable file cannot be created in this run, and provide the "
                f"requested `{mime_type}` content inline if that is still useful."
            )
    return "\n".join(instructions)


def _tool_names(tools: list[Any]) -> set[str]:
    names: set[str] = set()
    for tool in tools:
        if isinstance(tool, dict):
            function = tool.get("function") if isinstance(tool.get("function"), dict) else {}
            name = function.get("name") or tool.get("name") or tool.get("type")
        else:
            name = getattr(tool, "name", "")
        text = str(name or "").strip()
        if text:
            names.add("web_search" if text.startswith("web_search_") else text)
    return names


def _agent_prompt_context(body: dict[str, Any]) -> AgentPromptContext | None:
    context = body.get("context") if isinstance(body.get("context"), dict) else {}
    note_id = _optional_text(
        body.get("noteId")
        or body.get("note_id")
        or context.get("selectedNoteId")
        or context.get("selected_note_id")
        or context.get("noteId")
        or context.get("note_id")
    )
    note_title = _optional_text(
        body.get("noteTitle")
        or body.get("note_title")
        or context.get("selectedNoteTitle")
        or context.get("selected_note_title")
        or context.get("noteTitle")
        or context.get("note_title")
    )
    collection_path = _optional_text(
        context.get("selectedCategoryName")
        or context.get("selected_category_name")
        or context.get("collectionPath")
        or context.get("collection_path")
    )
    current_page = _optional_int(body.get("currentPage") or context.get("currentPage") or context.get("current_page"))
    selection = _optional_text(
        body.get("selectionText")
        or body.get("selection_text")
        or context.get("selectionText")
        or context.get("selection_text")
    )
    visible_annotations = _visible_annotations(
        body.get("visibleAnnotations")
        or body.get("visible_annotations")
        or context.get("visibleAnnotations")
        or context.get("visible_annotations")
    )
    if not any([note_id, note_title, collection_path, current_page is not None, selection, visible_annotations]):
        return None
    note = {"id": note_id, "title": note_title}
    if collection_path:
        note["collectionPath"] = collection_path
    return AgentPromptContext.from_note(
        note,
        current_page=current_page,
        selection_text=selection,
        visible_annotations=visible_annotations,
        session_title=_optional_text(body.get("sessionTitle") or body.get("session_title") or body.get("title")),
    )


def _optional_int(value: Any) -> int | None:
    text = _optional_text(value)
    if not text:
        return None
    try:
        return int(text)
    except (TypeError, ValueError):
        return None


def _visible_annotations(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


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
