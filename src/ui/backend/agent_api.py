from __future__ import annotations

import json
import queue
import re
import threading
import time
from uuid import uuid4
from http import HTTPStatus
from typing import Any, Callable

from agent_runtime import AgentEvent
from agent_runtime.service import AgentCompactResult, AgentContextStatus, AgentService, AgentServiceRequest, AgentServiceResult
from agent_sessions import AgentSession, AgentSessionMetadata, SessionNotFoundError
from tool_safety import ToolApprovalNotFoundError, ToolSnapshotConflictError, ToolSnapshotError
from media import MediaStoreError
from model_providers import ModelProviderAPIError, ModelProviderConfigError, ToolCall, normalize_model_provider_name
from model_providers.profiles import capabilities_for_provider_model
from telemetry.agent_background_runs import BackgroundChatRunStore
from telemetry.agent_progress import AgentProgressStore, unknown_progress_snapshot
from telemetry.agent_runs import AgentRunCoordinator, AgentRunHandle
from app_infra.formatting import normalize_text
from telemetry.debug_logs import DebugRunStore, sanitize_debug_payload


class AgentAPIError(Exception):
    def __init__(self, status: HTTPStatus, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


_SERVICE: AgentService | None = None
_SERVICE_LOCK = threading.Lock()
_PROGRESS_STORE = AgentProgressStore()
_RUN_COORDINATOR = AgentRunCoordinator()
_DEBUG_RUN_STORE = DebugRunStore()
_BACKGROUND_RUN_STORE = BackgroundChatRunStore()
_SANDBOX_MEDIA_LINK_RE = re.compile(r"sandbox:(/api/media/[A-Za-z0-9._~/%+-]+)", re.IGNORECASE)


def get_agent_service() -> AgentService:
    global _SERVICE
    with _SERVICE_LOCK:
        if _SERVICE is None:
            _SERVICE = AgentService()
        return _SERVICE


def set_agent_service(service: AgentService | None) -> None:
    global _SERVICE
    old_service: AgentService | None = None
    with _SERVICE_LOCK:
        old_service = _SERVICE
        _SERVICE = service
    if old_service is not None and old_service is not service:
        close = getattr(old_service, "close", None)
        if callable(close):
            close()


def get_agent_progress_store() -> AgentProgressStore:
    return _PROGRESS_STORE


def get_agent_run_coordinator() -> AgentRunCoordinator:
    return _RUN_COORDINATOR


def get_debug_run_store() -> DebugRunStore:
    return _DEBUG_RUN_STORE


def get_background_run_store() -> BackgroundChatRunStore:
    return _BACKGROUND_RUN_STORE


def _debug_store_for_service(service: AgentService) -> DebugRunStore:
    return DebugRunStore(service.session_store.sessions_root.parent / "logs" / "runs")


def handle_chat_request(
    body: Any,
    *,
    service: AgentService | None = None,
    progress_store: AgentProgressStore | None = None,
    run_coordinator: AgentRunCoordinator | None = None,
    debug_store: DebugRunStore | None = None,
) -> dict[str, Any]:
    if not isinstance(body, dict):
        debug = debug_store or get_debug_run_store()
        _debug_finish_error(debug, _new_debug_request_id(), "json", "invalid_body", "Request body must be a JSON object.")
        raise AgentAPIError(HTTPStatus.BAD_REQUEST, "invalid_body", "Request body must be a JSON object.")

    agent_service = service or get_agent_service()
    debug = debug_store or _debug_store_for_service(agent_service)
    request_id = _request_id(body)
    debug_request_id = request_id or _new_debug_request_id()
    session_id = _optional_text(body.get("sessionId") or body.get("session_id"))
    debug.start_run(
        request_id=debug_request_id,
        session_id=session_id,
        note_id=_note_id(body),
        provider=_optional_text(body.get("provider")),
        model=_optional_text(body.get("model")),
        transport="json",
        metadata=_debug_request_metadata(body),
    )
    message = body.get("message", body.get("text", ""))
    attachments = _chat_attachments(body.get("attachments"))
    if isinstance(message, str) and not normalize_text(message) and not attachments:
        _debug_finish_error(debug, debug_request_id, "json", "message_required", "Message is required.", body=body)
        raise AgentAPIError(HTTPStatus.BAD_REQUEST, "message_required", "Message is required.")
    if message is None and not attachments:
        _debug_finish_error(debug, debug_request_id, "json", "message_required", "Message is required.", body=body)
        raise AgentAPIError(HTTPStatus.BAD_REQUEST, "message_required", "Message is required.")

    progress = progress_store or get_agent_progress_store()
    if request_id:
        progress.start(request_id)

    runs = run_coordinator or get_agent_run_coordinator()
    run_handle = _acquire_run_slot(
        runs,
        session_id=session_id,
        request_id=request_id,
        progress=progress,
    )
    if session_id and run_handle is None:
        if request_id:
            progress.cancelled(request_id)
        payload = _cancelled_chat_result(agent_service, session_id, request_id)
        debug.finish_run(
            debug_request_id,
            status="cancelled",
            session_id=session_id,
            note_id=_note_id(body),
            provider=_optional_text(body.get("provider")),
            model=_optional_text(body.get("model")),
            final_message_preview=payload.get("response") or "",
        )
        return payload

    external_event_sink = body.get("_paper_notes_event_sink")
    if not callable(external_event_sink):
        external_event_sink = None

    def request_event_sink(event: AgentEvent) -> None:
        if request_id:
            progress.append(request_id, event)
        if external_event_sink is not None:
            external_event_sink(event)

    request = AgentServiceRequest(
        message=message,
        session_id=session_id,
        request_id=request_id,
        title=_session_title(body, message),
        note_id=_note_id(body),
        provider=_optional_text(body.get("provider")),
        model=_optional_text(body.get("model")),
        context=_prompt_context(body),
        extra_instructions=_optional_text(body.get("extraInstructions") or body.get("extra_instructions")),
        enable_tools=_bool_value(body.get("enableTools", body.get("enable_tools", True)), default=True),
        toolset=_optional_text(body.get("toolset")),
        enabled_toolsets=_optional_text_list(body.get("enabledToolsets") or body.get("enabled_toolsets")),
        disabled_toolsets=_optional_text_list(body.get("disabledToolsets") or body.get("disabled_toolsets")),
        disabled_tools=_optional_text_list(body.get("disabledTools") or body.get("disabled_tools")) or [],
        tool_write_modes=_tool_write_modes(body.get("toolWriteModes") or body.get("tool_write_modes")),
        write_tool_mode=_write_tool_mode(body),
        max_turns=_int_value(body.get("maxTurns", body.get("max_turns")), default=90, minimum=1, maximum=200),
        max_output_tokens=_optional_int(body.get("maxOutputTokens", body.get("max_output_tokens")), minimum=1),
        request_options=_request_options(body),
        attachments=attachments,
        image_generation=_image_generation_config(body.get("imageGeneration") or body.get("image_generation")),
        file_generation=_file_generation_config(body.get("fileGeneration") or body.get("file_generation")),
        metadata=_request_metadata(body),
        edit_latest_user_message=_bool_value(
            body.get("editLatestUserMessage", body.get("edit_latest_user_message", False)),
            default=False,
        ),
        summarize_on_max_turns=_bool_value(
            body.get("summarizeOnMaxTurns", body.get("summarize_on_max_turns", True)),
            default=True,
        ),
        budget_warnings_enabled=_bool_value(
            body.get("budgetWarningsEnabled", body.get("budget_warnings_enabled", True)),
            default=True,
        ),
        stream_events_enabled=_bool_value(
            body.get("streamEventsEnabled", body.get("stream_events_enabled", False)),
            default=False,
        ),
        event_sink=request_event_sink if (request_id or external_event_sink is not None) else None,
        control=run_handle.control if run_handle is not None else None,
    )

    try:
        result = agent_service.run(request)
    except SessionNotFoundError as error:
        _fail_progress(progress, request_id, str(error))
        _debug_finish_error(debug, debug_request_id, "json", "session_not_found", str(error), body=body)
        raise AgentAPIError(HTTPStatus.NOT_FOUND, "session_not_found", str(error)) from error
    except ModelProviderConfigError as error:
        _fail_progress(progress, request_id, str(error))
        _debug_finish_error(debug, debug_request_id, "json", "model_provider_config", str(error), body=body)
        raise AgentAPIError(HTTPStatus.SERVICE_UNAVAILABLE, "model_provider_config", str(error)) from error
    except ModelProviderAPIError as error:
        public_message = _model_provider_api_public_message(error, body)
        _fail_progress(progress, request_id, public_message)
        _debug_finish_error(debug, debug_request_id, "json", "model_provider_api", public_message, body=body)
        raise AgentAPIError(
            HTTPStatus.BAD_GATEWAY,
            "model_provider_api",
            public_message,
        ) from error
    except ValueError as error:
        _fail_progress(progress, request_id, str(error))
        _debug_finish_error(debug, debug_request_id, "json", "invalid_request", str(error), body=body)
        raise AgentAPIError(HTTPStatus.BAD_REQUEST, "invalid_request", str(error)) from error
    finally:
        runs.release(run_handle)

    if request_id:
        if result.cancelled:
            progress.cancelled(request_id)
        elif result.completed:
            progress.complete(request_id)
        elif result.error:
            progress.fail(request_id, result.error)
    _debug_finish_result(debug, debug_request_id, result, agent_service=agent_service, body=body, transport="json")
    payload = serialize_chat_result(result, debug_store=debug)
    payload["requestId"] = debug_request_id
    return payload


SSESender = Callable[[str, dict[str, Any]], bool | None]


def handle_chat_stream_request(
    body: Any,
    *,
    send_event: SSESender,
    service: AgentService | None = None,
    progress_store: AgentProgressStore | None = None,
    run_coordinator: AgentRunCoordinator | None = None,
    debug_store: DebugRunStore | None = None,
) -> None:
    if not isinstance(body, dict):
        debug = debug_store or get_debug_run_store()
        _debug_finish_error(debug, _new_debug_request_id(), "sse", "invalid_body", "Request body must be a JSON object.")
        send_event("error", {"code": "invalid_body", "error": "Request body must be a JSON object."})
        send_event("done", {})
        return

    agent_service = service or get_agent_service()
    debug = debug_store or _debug_store_for_service(agent_service)
    request_id = _request_id(body) or _new_debug_request_id()
    body = dict(body)
    body["requestId"] = request_id
    message = body.get("message", body.get("text", ""))
    attachments = _chat_attachments(body.get("attachments"))
    if isinstance(message, str) and not normalize_text(message) and not attachments:
        _debug_finish_error(debug, request_id, "sse", "message_required", "Message is required.", body=body)
        send_event("error", {"code": "message_required", "error": "Message is required."})
        send_event("done", {})
        return
    if message is None and not attachments:
        _debug_finish_error(debug, request_id, "sse", "message_required", "Message is required.", body=body)
        send_event("error", {"code": "message_required", "error": "Message is required."})
        send_event("done", {})
        return
    session_id = _ensure_stream_session_id(body, agent_service)

    progress = progress_store or get_agent_progress_store()
    progress.start(request_id)
    send_event("start", {
        "requestId": request_id,
        "sessionId": session_id,
        "session": serialize_session_metadata(agent_service.session_store.require_session(session_id).metadata) if session_id else None,
    })

    runs = run_coordinator or get_agent_run_coordinator()
    background_runs = get_background_run_store()
    run_body = dict(body)
    run_body["streamEventsEnabled"] = True
    run_body["sessionId"] = session_id
    run_body["session_id"] = session_id
    event_queue: queue.Queue[AgentEvent] = queue.Queue()
    run_body["_paper_notes_event_sink"] = event_queue.put

    background_runs.start(
        request_id=request_id,
        session_id=session_id,
        target=lambda: handle_chat_request(
            run_body,
            service=agent_service,
            progress_store=progress,
            run_coordinator=runs,
            debug_store=debug,
        ),
    )

    last_progress_at = ""
    while True:
        while True:
            try:
                event = event_queue.get_nowait()
            except queue.Empty:
                break
            snapshot = progress.get(request_id)
            if send_event(_stream_event_name(event), {
                "requestId": request_id,
                "sessionId": session_id,
                "event": serialize_event(event),
                "progress": snapshot,
                **_stream_event_payload(event),
            }) is False:
                return
        record = background_runs.get(request_id)
        snapshot = progress.get(request_id)
        if snapshot and snapshot.get("updatedAt") != last_progress_at:
            last_progress_at = str(snapshot.get("updatedAt") or "")
            if send_event("progress", {"requestId": request_id, "sessionId": session_id, "progress": snapshot}) is False:
                return
        if record is not None and record.done:
            if record.payload:
                payload = dict(record.payload)
                payload["requestId"] = request_id
                if send_event("final", payload) is False:
                    return
            else:
                if send_event("error", {
                    "code": record.code or "agent_run_failed",
                    "error": record.error or "Agent run failed.",
                    "requestId": request_id,
                    "sessionId": session_id,
                }) is False:
                    return
            send_event("done", {"requestId": request_id, "sessionId": session_id})
            return
        time.sleep(0.8)


def _ensure_stream_session_id(body: dict[str, Any], service: AgentService) -> str:
    session_id = _optional_text(body.get("sessionId") or body.get("session_id"))
    if session_id:
        return session_id
    if _bool_value(body.get("editLatestUserMessage", body.get("edit_latest_user_message", False)), default=False):
        return ""
    session = service.session_store.create_session(
        title=_session_title(body, body.get("message", body.get("text", ""))),
        note_id=_note_id(body),
        provider=_optional_text(body.get("provider")) or None,
        model=_optional_text(body.get("model")) or None,
        metadata=_request_metadata(body),
    )
    session_id = session.metadata.session_id
    body["sessionId"] = session_id
    body["session_id"] = session_id
    return session_id


def upload_chat_attachment(body: Any, *, service: AgentService | None = None) -> dict[str, Any]:
    if not isinstance(body, dict):
        raise AgentAPIError(HTTPStatus.BAD_REQUEST, "invalid_body", "Request body must be a JSON object.")
    attachment_data = _optional_text(body.get("data") or body.get("file") or body.get("image") or body.get("base64"))
    if not attachment_data:
        raise AgentAPIError(HTTPStatus.BAD_REQUEST, "attachment_required", "Attachment data is required.")
    file_name = _optional_text(body.get("fileName") or body.get("file_name") or body.get("name"))
    mime_type = _optional_text(body.get("mimeType") or body.get("mime_type") or body.get("type"))
    scope = _optional_text(body.get("sessionId") or body.get("session_id") or body.get("requestId") or body.get("request_id"))
    metadata = dict(body.get("metadata")) if isinstance(body.get("metadata"), dict) else {}
    media_store = (service or get_agent_service()).media_store if service is not None else get_agent_service().media_store
    try:
        artifact = media_store.create_upload(
            attachment_data,
            file_name=file_name,
            scope=scope,
            mime_type=mime_type,
            metadata=metadata,
        )
    except MediaStoreError as error:
        raise AgentAPIError(HTTPStatus.BAD_REQUEST, "invalid_attachment", str(error)) from error
    except ValueError as error:
        raise AgentAPIError(HTTPStatus.BAD_REQUEST, "invalid_attachment", str(error)) from error
    return {"artifact": artifact.to_dict()}


def cancel_chat_request(
    body: Any,
    *,
    progress_store: AgentProgressStore | None = None,
    run_coordinator: AgentRunCoordinator | None = None,
) -> dict[str, Any]:
    if not isinstance(body, dict):
        raise AgentAPIError(HTTPStatus.BAD_REQUEST, "invalid_body", "Request body must be a JSON object.")

    request_id = _request_id(body)
    session_id = _body_optional_session_id(body)
    if not request_id and not session_id:
        raise AgentAPIError(
            HTTPStatus.BAD_REQUEST,
            "run_id_required",
            "Request id or session id is required.",
        )

    reason = _optional_text(body.get("reason")) or "cancelled"
    progress = progress_store or get_agent_progress_store()
    runs = run_coordinator or get_agent_run_coordinator()
    result = runs.cancel(request_id=request_id, session_id=session_id, reason=reason)
    if result.cancelled and result.request_id:
        if result.status == "cancelling":
            progress.cancelling(result.request_id)
        else:
            progress.cancelled(result.request_id)
    return {
        "cancelled": result.cancelled,
        "status": result.status,
        "requestId": result.request_id or request_id,
        "sessionId": result.session_id or session_id,
    }


def list_debug_runs(
    query: dict[str, list[str]] | None = None,
    *,
    debug_store: DebugRunStore | None = None,
) -> dict[str, Any]:
    params = query or {}
    store = debug_store or get_debug_run_store()
    limit = _query_int(params, "limit") or 50
    session_id = _query_text(params, "sessionId") or _query_text(params, "session_id")
    status = _query_text(params, "status")
    return {"runs": store.list_runs(limit=limit, session_id=session_id, status=status)}


def get_debug_run(
    request_id: str,
    *,
    debug_store: DebugRunStore | None = None,
) -> dict[str, Any]:
    if not request_id:
        raise AgentAPIError(HTTPStatus.BAD_REQUEST, "request_id_required", "Request id is required.")
    store = debug_store or get_debug_run_store()
    record = store.get_run(request_id)
    if record is None:
        raise AgentAPIError(HTTPStatus.NOT_FOUND, "debug_run_not_found", "Debug run was not found.")
    return {"run": record}


def cleanup_debug_runs(
    body: Any,
    *,
    debug_store: DebugRunStore | None = None,
) -> dict[str, Any]:
    payload = body if isinstance(body, dict) else {}
    store = debug_store or get_debug_run_store()
    keep = _int_value(payload.get("keep"), default=200, minimum=0, maximum=5000)
    max_age_days = _int_value(payload.get("maxAgeDays", payload.get("max_age_days")), default=30, minimum=1, maximum=3650)
    return store.cleanup(keep=keep, max_age_days=max_age_days)


def get_chat_progress(
    query: dict[str, list[str]] | None = None,
    *,
    progress_store: AgentProgressStore | None = None,
) -> dict[str, Any]:
    request_id = _query_text(query or {}, "id") or _query_text(query or {}, "requestId")
    if not request_id:
        raise AgentAPIError(HTTPStatus.BAD_REQUEST, "request_id_required", "Request id is required.")
    progress = progress_store or get_agent_progress_store()
    return progress.get(request_id) or unknown_progress_snapshot(request_id)


def list_chat_sessions(query: dict[str, list[str]] | None = None, *, service: AgentService | None = None) -> dict[str, Any]:
    include_archived = _query_bool(query or {}, "includeArchived") or _query_bool(query or {}, "include_archived")
    state = _query_text(query or {}, "state")
    agent_service = service or get_agent_service()
    return {
        "sessions": [
            serialize_session_metadata(session)
            for session in agent_service.session_store.list_sessions(include_archived=include_archived, state=state)
        ],
    }


def get_chat_session(query: dict[str, list[str]] | None = None, *, service: AgentService | None = None) -> dict[str, Any]:
    session_id = _query_text(query or {}, "id") or _query_text(query or {}, "sessionId")
    if not session_id:
        raise AgentAPIError(HTTPStatus.BAD_REQUEST, "session_id_required", "Session id is required.")

    agent_service = service or get_agent_service()
    session = agent_service.session_store.get_session(session_id)
    if session is None:
        raise AgentAPIError(HTTPStatus.NOT_FOUND, "session_not_found", f"Agent session not found: {session_id}")
    return {"session": serialize_session(session, debug_store=_debug_store_for_service(agent_service))}


def get_chat_context_status(query: dict[str, list[str]] | None = None, *, service: AgentService | None = None) -> dict[str, Any]:
    params = query or {}
    session_id = _query_text(params, "id") or _query_text(params, "sessionId")
    agent_service = service or get_agent_service()
    try:
        status = agent_service.context_status_fuc(
            session_id=session_id or None,
            provider=_query_text(params, "provider"),
            model=_query_text(params, "model"),
            context=_query_prompt_context(params),
            toolset=_query_text(params, "toolset"),
            enabled_toolsets=_query_text_list(params, "enabledToolsets") or _query_text_list(params, "enabled_toolsets"),
            disabled_toolsets=_query_text_list(params, "disabledToolsets") or _query_text_list(params, "disabled_toolsets"),
            note_id=_query_text(params, "noteId") or _query_text(params, "note_id"),
        )
    except SessionNotFoundError as error:
        raise AgentAPIError(HTTPStatus.NOT_FOUND, "session_not_found", str(error)) from error
    return {"context": serialize_context_status(status)}


def compact_chat_session(body: Any, *, service: AgentService | None = None) -> dict[str, Any]:
    if not isinstance(body, dict):
        raise AgentAPIError(HTTPStatus.BAD_REQUEST, "invalid_body", "Request body must be a JSON object.")
    session_id = _body_session_id(body)
    agent_service = service or get_agent_service()
    try:
        result = agent_service.compact_session(
            session_id=session_id,
            focus=_optional_text(body.get("focus")),
            provider=_optional_text(body.get("provider")),
            model=_optional_text(body.get("model")),
            context=_prompt_context(body),
            extra_instructions=_optional_text(body.get("extraInstructions") or body.get("extra_instructions")),
            enable_tools=_bool_value(body.get("enableTools", body.get("enable_tools", True)), default=True),
            toolset=_optional_text(body.get("toolset")),
            enabled_toolsets=_optional_text_list(body.get("enabledToolsets") or body.get("enabled_toolsets")),
            disabled_toolsets=_optional_text_list(body.get("disabledToolsets") or body.get("disabled_toolsets")),
            note_id=_note_id(body),
        )
    except SessionNotFoundError as error:
        raise AgentAPIError(HTTPStatus.NOT_FOUND, "session_not_found", str(error)) from error
    except ModelProviderConfigError as error:
        raise AgentAPIError(HTTPStatus.SERVICE_UNAVAILABLE, "model_provider_config", str(error)) from error
    except ModelProviderAPIError as error:
        raise AgentAPIError(
            HTTPStatus.BAD_GATEWAY,
            "model_provider_api",
            _model_provider_api_public_message(error, body),
        ) from error
    except ValueError as error:
        raise AgentAPIError(HTTPStatus.BAD_REQUEST, "invalid_request", str(error)) from error
    return serialize_compact_result(result)


def create_chat_session(body: Any, *, service: AgentService | None = None) -> dict[str, Any]:
    if not isinstance(body, dict):
        raise AgentAPIError(HTTPStatus.BAD_REQUEST, "invalid_body", "Request body must be a JSON object.")
    agent_service = service or get_agent_service()
    session = agent_service.session_store.create_session(
        title=_optional_text(body.get("title") or body.get("sessionTitle") or body.get("session_title")) or "New chat",
        note_id=_note_id(body) or None,
        provider=_provider_or_none(body.get("provider")),
        model=_optional_text(body.get("model")) or None,
        metadata=_request_metadata(body),
    )
    return {"session": serialize_session(session, debug_store=_debug_store_for_service(agent_service))}


def update_chat_session_model(body: Any, *, service: AgentService | None = None) -> dict[str, Any]:
    if not isinstance(body, dict):
        raise AgentAPIError(HTTPStatus.BAD_REQUEST, "invalid_body", "Request body must be a JSON object.")
    session_id = _body_session_id(body)
    provider = _provider_or_none(body.get("provider"))
    model = _optional_text(body.get("model"))
    if provider is None and not model:
        raise AgentAPIError(
            HTTPStatus.BAD_REQUEST,
            "model_update_required",
            "Provider or model is required.",
        )

    agent_service = service or get_agent_service()
    try:
        session = agent_service.session_store.update_session_model(
            session_id,
            provider=provider,
            model=model if "model" in body else None,
        )
        metadata_updates = _session_metadata_updates(body)
        if metadata_updates:
            agent_service.session_store.update_session_metadata(session_id, metadata_updates)
            session = agent_service.session_store.require_session(session_id)
    except SessionNotFoundError as error:
        raise AgentAPIError(HTTPStatus.NOT_FOUND, "session_not_found", str(error)) from error
    return {"session": serialize_session(session, debug_store=_debug_store_for_service(agent_service))}


def rename_chat_session(body: Any, *, service: AgentService | None = None) -> dict[str, Any]:
    if not isinstance(body, dict):
        raise AgentAPIError(HTTPStatus.BAD_REQUEST, "invalid_body", "Request body must be a JSON object.")
    session_id = _body_session_id(body)
    title = _optional_text(body.get("title"))
    if not title:
        raise AgentAPIError(HTTPStatus.BAD_REQUEST, "title_required", "Session title is required.")

    agent_service = service or get_agent_service()
    try:
        metadata = agent_service.session_store.rename_session(session_id, title)
    except SessionNotFoundError as error:
        raise AgentAPIError(HTTPStatus.NOT_FOUND, "session_not_found", str(error)) from error
    return {"session": serialize_session_metadata(metadata)}


def archive_chat_session(body: Any, *, service: AgentService | None = None) -> dict[str, Any]:
    if not isinstance(body, dict):
        raise AgentAPIError(HTTPStatus.BAD_REQUEST, "invalid_body", "Request body must be a JSON object.")
    session_id = _body_session_id(body)
    requested_state = _optional_text(body.get("state"))
    if requested_state:
        state = requested_state
    elif _bool_value(body.get("trashed", False), default=False):
        state = "trashed"
    else:
        archived = _bool_value(body.get("archived", True), default=True)
        state = "archived" if archived else "active"

    agent_service = service or get_agent_service()
    try:
        metadata = agent_service.session_store.update_session_state(session_id, state=state)
    except SessionNotFoundError as error:
        raise AgentAPIError(HTTPStatus.NOT_FOUND, "session_not_found", str(error)) from error
    return {"session": serialize_session_metadata(metadata)}


def delete_chat_session(body: Any, *, service: AgentService | None = None) -> dict[str, Any]:
    if not isinstance(body, dict):
        raise AgentAPIError(HTTPStatus.BAD_REQUEST, "invalid_body", "Request body must be a JSON object.")
    session_id = _body_session_id(body)

    agent_service = service or get_agent_service()
    try:
        metadata = agent_service.session_store.delete_session(session_id)
    except SessionNotFoundError as error:
        raise AgentAPIError(HTTPStatus.NOT_FOUND, "session_not_found", str(error)) from error
    return {
        "deleted": True,
        "session": serialize_session_metadata(metadata),
    }


def branch_chat_session(body: Any, *, service: AgentService | None = None) -> dict[str, Any]:
    if not isinstance(body, dict):
        raise AgentAPIError(HTTPStatus.BAD_REQUEST, "invalid_body", "Request body must be a JSON object.")
    session_id = _body_session_id(body)
    title = _optional_text(body.get("title"))

    agent_service = service or get_agent_service()
    try:
        session = agent_service.session_store.branch_session(session_id, title=title or None)
    except SessionNotFoundError as error:
        raise AgentAPIError(HTTPStatus.NOT_FOUND, "session_not_found", str(error)) from error
    return {
        "sourceSessionId": session_id,
        "session": serialize_session(session, debug_store=_debug_store_for_service(agent_service)),
    }


def undo_chat_session(body: Any, *, service: AgentService | None = None) -> dict[str, Any]:
    if not isinstance(body, dict):
        raise AgentAPIError(HTTPStatus.BAD_REQUEST, "invalid_body", "Request body must be a JSON object.")
    session_id = _body_session_id(body)

    agent_service = service or get_agent_service()
    try:
        session, removed_count = agent_service.session_store.undo_last_turn(session_id)
    except SessionNotFoundError as error:
        raise AgentAPIError(HTTPStatus.NOT_FOUND, "session_not_found", str(error)) from error
    return {
        "removedCount": removed_count,
        "session": serialize_session(session, debug_store=_debug_store_for_service(agent_service)),
    }


def undo_chat_tool_snapshot(body: Any, *, service: AgentService | None = None) -> dict[str, Any]:
    if not isinstance(body, dict):
        raise AgentAPIError(HTTPStatus.BAD_REQUEST, "invalid_body", "Request body must be a JSON object.")
    session_id = _body_session_id(body)
    snapshot_id = _optional_text(body.get("snapshotId") or body.get("snapshot_id"))
    if not snapshot_id:
        raise AgentAPIError(HTTPStatus.BAD_REQUEST, "snapshot_id_required", "Snapshot id is required.")
    force = _bool_value(body.get("force", False), default=False)

    agent_service = service or get_agent_service()
    try:
        return agent_service.restore_tool_snapshot(session_id=session_id, snapshot_id=snapshot_id, force=force)
    except SessionNotFoundError as error:
        raise AgentAPIError(HTTPStatus.NOT_FOUND, "session_not_found", str(error)) from error
    except ToolSnapshotConflictError as error:
        raise AgentAPIError(HTTPStatus.CONFLICT, "snapshot_conflict", str(error)) from error
    except ToolSnapshotError as error:
        raise AgentAPIError(HTTPStatus.NOT_FOUND, "snapshot_not_found", str(error)) from error


def redo_chat_tool_snapshot(body: Any, *, service: AgentService | None = None) -> dict[str, Any]:
    if not isinstance(body, dict):
        raise AgentAPIError(HTTPStatus.BAD_REQUEST, "invalid_body", "Request body must be a JSON object.")
    session_id = _body_session_id(body)
    snapshot_id = _optional_text(body.get("snapshotId") or body.get("snapshot_id"))
    if not snapshot_id:
        raise AgentAPIError(HTTPStatus.BAD_REQUEST, "snapshot_id_required", "Snapshot id is required.")
    force = _bool_value(body.get("force", False), default=False)

    agent_service = service or get_agent_service()
    try:
        return agent_service.redo_tool_snapshot(session_id=session_id, snapshot_id=snapshot_id, force=force)
    except SessionNotFoundError as error:
        raise AgentAPIError(HTTPStatus.NOT_FOUND, "session_not_found", str(error)) from error
    except ToolSnapshotConflictError as error:
        raise AgentAPIError(HTTPStatus.CONFLICT, "snapshot_conflict", str(error)) from error
    except ToolSnapshotError as error:
        raise AgentAPIError(HTTPStatus.NOT_FOUND, "snapshot_not_found", str(error)) from error


def preview_chat_tool_snapshot(
    query: dict[str, list[str]] | None = None,
    *,
    service: AgentService | None = None,
) -> dict[str, Any]:
    params = query or {}
    session_id = _query_text(params, "sessionId") or _query_text(params, "session_id") or _query_text(params, "id")
    if not session_id:
        raise AgentAPIError(HTTPStatus.BAD_REQUEST, "session_id_required", "Session id is required.")
    snapshot_id = _query_text(params, "snapshotId") or _query_text(params, "snapshot_id")
    if not snapshot_id:
        raise AgentAPIError(HTTPStatus.BAD_REQUEST, "snapshot_id_required", "Snapshot id is required.")
    max_chars = _int_value(_query_text(params, "maxChars") or _query_text(params, "max_chars"), default=16_000, minimum=1_000, maximum=80_000)
    agent_service = service or get_agent_service()
    try:
        return agent_service.preview_tool_snapshot(
            session_id=session_id,
            snapshot_id=snapshot_id,
            max_chars=max_chars,
        )
    except SessionNotFoundError as error:
        raise AgentAPIError(HTTPStatus.NOT_FOUND, "session_not_found", str(error)) from error
    except ToolSnapshotError as error:
        raise AgentAPIError(HTTPStatus.NOT_FOUND, "snapshot_not_found", str(error)) from error


def list_chat_tool_snapshots(
    query: dict[str, list[str]] | None = None,
    *,
    service: AgentService | None = None,
) -> dict[str, Any]:
    params = query or {}
    session_id = _query_text(params, "sessionId") or _query_text(params, "session_id") or _query_text(params, "id")
    if not session_id:
        raise AgentAPIError(HTTPStatus.BAD_REQUEST, "session_id_required", "Session id is required.")
    limit = _int_value(_query_text(params, "limit"), default=50, minimum=1, maximum=200)
    agent_service = service or get_agent_service()
    try:
        snapshots = agent_service.list_tool_snapshots(session_id=session_id, limit=limit)
    except SessionNotFoundError as error:
        raise AgentAPIError(HTTPStatus.NOT_FOUND, "session_not_found", str(error)) from error
    return {"sessionId": session_id, "snapshots": snapshots}


def cleanup_chat_tool_snapshots(body: Any, *, service: AgentService | None = None) -> dict[str, Any]:
    if not isinstance(body, dict):
        raise AgentAPIError(HTTPStatus.BAD_REQUEST, "invalid_body", "Request body must be a JSON object.")
    session_id = _optional_text(body.get("sessionId") or body.get("session_id"))
    keep = _int_value(body.get("keepPerSession", body.get("keep_per_session")), default=50, minimum=0, maximum=500)
    max_age = _optional_int(body.get("maxAgeDays", body.get("max_age_days")), minimum=0)
    agent_service = service or get_agent_service()
    try:
        return agent_service.cleanup_tool_snapshots(
            session_id=session_id or None,
            keep_per_session=keep,
            max_age_days=max_age,
        )
    except SessionNotFoundError as error:
        raise AgentAPIError(HTTPStatus.NOT_FOUND, "session_not_found", str(error)) from error


def list_chat_tool_approvals(
    query: dict[str, list[str]] | None = None,
    *,
    service: AgentService | None = None,
) -> dict[str, Any]:
    params = query or {}
    session_id = _query_text(params, "sessionId") or _query_text(params, "session_id") or _query_text(params, "id")
    agent_service = service or get_agent_service()
    try:
        approvals = agent_service.list_tool_approvals(session_id=session_id or None)
    except SessionNotFoundError as error:
        raise AgentAPIError(HTTPStatus.NOT_FOUND, "session_not_found", str(error)) from error
    return {"sessionId": session_id, "approvals": approvals}


def respond_chat_tool_approval(body: Any, *, service: AgentService | None = None) -> dict[str, Any]:
    if not isinstance(body, dict):
        raise AgentAPIError(HTTPStatus.BAD_REQUEST, "invalid_body", "Request body must be a JSON object.")
    approval_id = _optional_text(body.get("approvalId") or body.get("approval_id") or body.get("id"))
    if not approval_id:
        raise AgentAPIError(HTTPStatus.BAD_REQUEST, "approval_id_required", "Approval id is required.")
    action = _optional_text(body.get("action") or body.get("decision"))
    if not action:
        raise AgentAPIError(HTTPStatus.BAD_REQUEST, "approval_action_required", "Approval action is required.")
    message = _optional_text(body.get("message"))
    agent_service = service or get_agent_service()
    try:
        approval = agent_service.respond_tool_approval(
            approval_id=approval_id,
            action=action,
            message=message,
        )
    except ToolApprovalNotFoundError as error:
        raise AgentAPIError(HTTPStatus.NOT_FOUND, "approval_not_found", str(error)) from error
    except ValueError as error:
        raise AgentAPIError(HTTPStatus.BAD_REQUEST, "invalid_approval_action", str(error)) from error
    return {"approval": approval}


def serialize_chat_result(result: AgentServiceResult, *, debug_store: DebugRunStore | None = None) -> dict[str, Any]:
    tool_activity = _tool_activity_from_events(result.events, session_id=result.session_id)
    response_text = _normalize_public_message_links(result.response or "")
    assistant_message = {
        "role": "assistant",
        "content": response_text,
        "text": response_text,
        "error": bool((result.error or result.cancelled) and not result.completed),
    }
    if tool_activity:
        assistant_message["toolActivity"] = tool_activity
    if result.artifacts:
        assistant_message["artifacts"] = result.artifacts
    messages = _messages_with_debug_run_traces(
        _public_chat_messages([serialize_message(message) for message in result.messages]),
        session_id=result.session_id,
        debug_store=debug_store,
    )
    run_trace = _last_assistant_run_trace(messages)
    if run_trace:
        assistant_message["runTrace"] = run_trace
    work_trace = _work_trace_with_reasoning(
        _last_assistant_work_trace(messages),
        _last_assistant_reasoning_content(result.messages),
    )
    if work_trace:
        assistant_message["workTrace"] = work_trace
    if tool_activity:
        for message in reversed(messages):
            if message.get("role") == "assistant":
                message["toolActivity"] = tool_activity
                break
    return {
        "requestId": (run_trace or {}).get("requestId") or "",
        "sessionId": result.session_id,
        "session": serialize_session_metadata(result.session.metadata),
        "createdSession": result.created_session,
        "completed": result.completed,
        "cancelled": result.cancelled,
        "response": response_text,
        "message": assistant_message,
        "messages": messages,
        "events": [serialize_event(event) for event in result.events],
        "turns": result.turns,
        "pendingToolCalls": [serialize_tool_call(tool_call) for tool_call in result.pending_tool_calls],
        "artifacts": result.artifacts,
        "error": result.error,
    }


def _tool_activity_from_events(events: list[AgentEvent], *, session_id: str) -> list[dict[str, Any]]:
    activities: list[dict[str, Any]] = []
    for event in events:
        if event.type != "tool_result":
            continue
        data = event.data or {}
        raw_snapshots = data.get("snapshots") if isinstance(data.get("snapshots"), list) else []
        snapshots: list[dict[str, Any]] = []
        seen_snapshot_ids: set[str] = set()
        for raw_snapshot in raw_snapshots:
            if not isinstance(raw_snapshot, dict):
                continue
            snapshot_id = str(raw_snapshot.get("snapshotId") or "").strip()
            if snapshot_id and snapshot_id in seen_snapshot_ids:
                continue
            if snapshot_id:
                seen_snapshot_ids.add(snapshot_id)
            snapshots.append(raw_snapshot)
        single_snapshot = data.get("snapshot") if isinstance(data.get("snapshot"), dict) else {}
        single_snapshot_id = str(single_snapshot.get("snapshotId") or "").strip()
        if single_snapshot and (not single_snapshot_id or single_snapshot_id not in seen_snapshot_ids):
            snapshots.append(single_snapshot)
        for snapshot in snapshots:
            changed_files = snapshot.get("changedFiles") if isinstance(snapshot.get("changedFiles"), list) else []
            if not changed_files:
                continue
            snapshot_arguments = snapshot.get("arguments") if isinstance(snapshot.get("arguments"), dict) else {}
            note_id = data.get("note_id") or snapshot_arguments.get("note_id") or snapshot_arguments.get("id")
            activities.append({
                "type": "tool_result",
                "name": snapshot.get("toolName") or data.get("name") or "tool",
                "sessionId": session_id,
                "noteId": note_id or "",
                "snapshotId": snapshot.get("snapshotId") or "",
                "changedFiles": changed_files,
                "undoable": bool(snapshot.get("undoable")),
                "writeMode": data.get("write_mode") or data.get("writeMode") or "",
                "changed": bool(data.get("changed") or snapshot.get("changed")),
                "summary": data.get("summary") or "",
                "toolMessage": data.get("message") or "",
                "message": data.get("message") or event.message or "Tool completed.",
            })
    return activities


def _last_assistant_run_trace(messages: list[dict[str, Any]]) -> dict[str, Any] | None:
    for message in reversed(messages):
        if message.get("role") != "assistant":
            continue
        trace = message.get("runTrace")
        return trace if isinstance(trace, dict) else None
    return None


def _last_assistant_work_trace(messages: list[dict[str, Any]]) -> dict[str, Any] | None:
    for message in reversed(messages):
        if message.get("role") != "assistant":
            continue
        trace = message.get("workTrace")
        return trace if isinstance(trace, dict) else None
    return None


def _last_assistant_reasoning_content(messages: list[dict[str, Any]]) -> str:
    for message in reversed(messages):
        if message.get("role") != "assistant":
            continue
        value = message.get("reasoning_content")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _work_trace_with_reasoning(work_trace: dict[str, Any] | None, reasoning_content: str) -> dict[str, Any] | None:
    if not reasoning_content:
        return work_trace
    trace = dict(work_trace or {})
    raw_items = trace.get("items")
    items = list(raw_items) if isinstance(raw_items, list) else []
    if not any(isinstance(item, dict) and item.get("type") == "reasoning" and item.get("text") == reasoning_content for item in items):
        items.append({"type": "reasoning", "text": reasoning_content, "source": "deepseek"})
    trace["items"] = items
    return trace


def serialize_compact_result(result: AgentCompactResult) -> dict[str, Any]:
    marker = _last_compaction_marker_message(result.session.messages)
    return {
        "sessionId": result.session_id,
        "session": serialize_session_metadata(result.session.metadata),
        "compressed": result.compressed,
        "context": serialize_context_status(result.context),
        "events": [serialize_event(event) for event in result.events],
        "warning": result.warning or "",
        "message": serialize_message(marker) if marker is not None else None,
    }


def _last_compaction_marker_message(messages: list[dict[str, Any]]) -> dict[str, Any] | None:
    for message in reversed(messages):
        if message.get("role") != "divider":
            continue
        metadata = message.get("metadata")
        if isinstance(metadata, dict) and metadata.get("type") == "context_compaction_marker":
            return message
    return None


def serialize_session(session: AgentSession, *, debug_store: DebugRunStore | None = None) -> dict[str, Any]:
    return {
        **serialize_session_metadata(session.metadata),
        "messages": _messages_with_debug_run_traces(
            _public_chat_messages([serialize_message(message) for message in session.messages]),
            session_id=session.metadata.session_id,
            debug_store=debug_store,
        ),
    }


def serialize_context_status(status: AgentContextStatus) -> dict[str, Any]:
    return {
        "provider": status.provider,
        "model": status.model,
        "contextLength": status.context_length,
        "tokensUsed": status.display_tokens,
        "requestTokens": status.request_tokens,
        "estimatedRequestTokens": status.estimated_request_tokens,
        "messageTokens": status.message_tokens,
        "instructionTokens": status.instruction_tokens,
        "toolSchemaTokens": status.tool_schema_tokens,
        "thresholdTokens": status.threshold_tokens,
        "percentFull": status.percent_full,
        "thresholdPercent": status.threshold_percent,
        "messageCount": status.message_count,
        "compactionEnabled": status.compaction_enabled,
        "actualUsageAvailable": status.actual_usage_available,
        "usageUpdatedAt": status.usage_updated_at,
        "usageRequestId": status.usage_request_id,
        "actualInputTokens": status.actual_input_tokens,
        "compressionCount": status.compression_count,
        "lastCompressedAt": status.last_compressed_at,
        "summaryAvailable": status.summary_available,
        "lastCompressionError": status.last_compression_error,
        "fallbackUsed": status.fallback_used,
    }


def serialize_session_metadata(metadata: AgentSessionMetadata) -> dict[str, Any]:
    state = getattr(metadata, "state", "archived" if metadata.archived else "active")
    metadata_payload = metadata.metadata or {}
    origin_note_id = str(
        metadata_payload.get("originNoteId")
        or metadata_payload.get("origin_note_id")
        or metadata_payload.get("note_id")
        or metadata.note_id
        or ""
    )
    origin_note_title = str(
        metadata_payload.get("originNoteTitle")
        or metadata_payload.get("origin_note_title")
        or metadata_payload.get("note_title")
        or ""
    )
    current_note_id = str(
        metadata_payload.get("currentNoteId")
        or metadata_payload.get("current_note_id")
        or origin_note_id
        or ""
    )
    current_note_title = str(
        metadata_payload.get("currentNoteTitle")
        or metadata_payload.get("current_note_title")
        or origin_note_title
        or ""
    )
    return {
        "id": metadata.session_id,
        "sessionId": metadata.session_id,
        "title": metadata.title,
        "noteId": origin_note_id,
        "originNoteId": origin_note_id,
        "originNoteTitle": origin_note_title,
        "currentNoteId": current_note_id,
        "currentNoteTitle": current_note_title,
        "provider": metadata.provider or "",
        "model": metadata.model or "",
        "createdAt": metadata.created_at,
        "updatedAt": metadata.updated_at,
        "dateBucket": metadata.date_bucket,
        "messageCount": metadata.message_count,
        "state": state,
        "archived": state == "archived",
        "trashed": state == "trashed",
        "archivedAt": str(metadata_payload.get("archivedAt") or ""),
        "trashedAt": str(metadata_payload.get("trashedAt") or ""),
        "metadata": metadata.metadata,
    }


def serialize_message(message: dict[str, Any]) -> dict[str, Any]:
    content = message.get("content", "")
    text = _normalize_public_message_links(_message_text(content))
    serialized = dict(message)
    reasoning_content = serialized.pop("reasoning_content", None)
    if isinstance(reasoning_content, str) and reasoning_content.strip():
        serialized["workTrace"] = _work_trace_with_reasoning(
            serialized.get("workTrace") if isinstance(serialized.get("workTrace"), dict) else None,
            reasoning_content.strip(),
        )
    for internal_key in ("codex_reasoning_items", "codex_message_items", "provider_data"):
        serialized.pop(internal_key, None)
    tool_calls = serialized.get("tool_calls")
    run_trace = serialized.get("runTrace") if isinstance(serialized.get("runTrace"), dict) else {}
    work_trace = serialized.get("workTrace") if isinstance(serialized.get("workTrace"), dict) else {}
    trace_status = str(run_trace.get("status") or work_trace.get("status") or "").strip().lower()
    if message.get("role") == "assistant" and isinstance(tool_calls, list) and trace_status == "cancelled" and not text:
        serialized.pop("tool_calls", None)
        serialized.pop("toolCalls", None)
    elif isinstance(tool_calls, list):
        serialized["tool_calls"] = [_public_tool_call_message(tool_call) for tool_call in tool_calls]
    serialized["text"] = text
    return serialized


def _public_chat_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [message for message in messages if _is_public_chat_message(message)]


def _is_public_chat_message(message: dict[str, Any]) -> bool:
    role = message.get("role")
    if role == "tool":
        return False
    if role == "assistant" and message.get("tool_calls"):
        return False
    return role in {"user", "assistant", "divider"}


def _messages_with_debug_run_traces(
    messages: list[dict[str, Any]],
    *,
    session_id: str,
    debug_store: DebugRunStore | None = None,
) -> list[dict[str, Any]]:
    if not session_id:
        return messages
    missing_indexes = [
        index for index, message in enumerate(messages)
        if _message_can_receive_debug_trace(message)
    ]
    if not missing_indexes:
        return messages

    traces = _debug_run_traces_for_session(session_id, debug_store=debug_store)
    if not traces:
        return messages

    used_trace_indexes: set[int] = set()
    for message_index in missing_indexes:
        text = _normalized_trace_match_text(messages[message_index].get("text") or messages[message_index].get("content"))
        if not text:
            continue
        for trace_index, trace in enumerate(traces):
            if trace_index in used_trace_indexes:
                continue
            if _debug_trace_matches_message(trace, text):
                messages[message_index]["runTrace"] = trace["runTrace"]
                if "workTrace" not in messages[message_index] and isinstance(trace.get("workTrace"), dict):
                    messages[message_index]["workTrace"] = trace["workTrace"]
                used_trace_indexes.add(trace_index)
                break

    remaining_message_indexes = [
        index for index in missing_indexes
        if not isinstance(messages[index].get("runTrace"), dict)
    ]
    remaining_trace_indexes = [
        index for index in range(len(traces))
        if index not in used_trace_indexes
    ]
    if remaining_message_indexes and len(remaining_message_indexes) == len(remaining_trace_indexes):
        for message_index, trace_index in zip(remaining_message_indexes, remaining_trace_indexes, strict=False):
            messages[message_index]["runTrace"] = traces[trace_index]["runTrace"]
            if "workTrace" not in messages[message_index] and isinstance(traces[trace_index].get("workTrace"), dict):
                messages[message_index]["workTrace"] = traces[trace_index]["workTrace"]

    return messages


def _message_can_receive_debug_trace(message: dict[str, Any]) -> bool:
    if message.get("role") != "assistant":
        return False
    if isinstance(message.get("runTrace"), dict):
        return False
    if message.get("tool_calls"):
        return False
    return bool(_message_text(message.get("content", message.get("text", ""))))


def _debug_run_traces_for_session(
    session_id: str,
    *,
    debug_store: DebugRunStore | None = None,
) -> list[dict[str, Any]]:
    store = debug_store or get_debug_run_store()
    try:
        run_items = store.list_runs(limit=500, session_id=session_id)
    except Exception:
        return []

    traces: list[dict[str, Any]] = []
    for item in reversed(run_items):
        request_id = str(item.get("requestId") or "")
        if not request_id:
            continue
        try:
            detail = store.get_run(request_id)
        except Exception:
            detail = None
        if not isinstance(detail, dict):
            continue
        run_trace = _run_trace_from_debug_run(detail)
        if run_trace is None:
            continue
        traces.append({
            "preview": _normalized_trace_match_text(detail.get("finalMessagePreview")),
            "status": str(detail.get("status") or ""),
            "error": detail.get("error") if isinstance(detail.get("error"), dict) else {},
            "runTrace": run_trace,
            "workTrace": _work_trace_from_run_trace(run_trace),
        })
    return traces


def _run_trace_from_debug_run(run: dict[str, Any]) -> dict[str, Any] | None:
    events = run.get("events") if isinstance(run.get("events"), list) else []
    duration = _safe_int(run.get("durationMs"))
    if not events and duration <= 0:
        return None
    error = run.get("error") if isinstance(run.get("error"), dict) else {}
    return {
        "requestId": str(run.get("requestId") or ""),
        "startedAt": str(run.get("startedAt") or ""),
        "finishedAt": str(run.get("finishedAt") or ""),
        "durationMs": duration,
        "status": str(run.get("status") or ""),
        "error": str(error.get("message") or error.get("error") or error.get("code") or ""),
        "events": [event for event in events if isinstance(event, dict)],
    }


def _work_trace_from_run_trace(run_trace: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(run_trace, dict):
        return None
    events = run_trace.get("events") if isinstance(run_trace.get("events"), list) else []
    items: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for event in events:
        if not isinstance(event, dict):
            continue
        event_type = str(event.get("type") or "")
        data = event.get("data") if isinstance(event.get("data"), dict) else {}
        if event_type in {"work_trace_delta", "work_trace_item"}:
            text = str(data.get("text") or event.get("message") or "").strip()
            item_type = str(data.get("trace_type") or "summary").strip() or "summary"
            item_source = str(data.get("source") or "provider").strip() or "provider"
        elif event_type == "tool_call":
            name = str(data.get("name") or "tool")
            text = _work_trace_tool_start_detail(name, data)
            item_type = "skill" if _is_skill_tool(name) else "tool"
            item_source = "runtime"
        elif event_type == "tool_result":
            name = str(data.get("name") or "tool")
            text = _work_trace_tool_result_detail(name, data)
            item_type = "skill" if _is_skill_tool(name) else "tool"
            item_source = "runtime"
        elif event_type == "tool_error":
            text = _work_trace_tool_error_detail(str(data.get("name") or "tool"), data)
            item_type = "status"
            item_source = "runtime"
        elif event_type in {"cancelled", "halted", "tool_halted", "tool_approval_requested"}:
            text = str(event.get("message") or "").strip()
            item_type = "status"
            item_source = "runtime"
        else:
            continue
        if not text:
            continue
        key = (item_type, text)
        if key in seen:
            continue
        seen.add(key)
        _merge_run_work_trace_item(items, {"type": item_type, "text": text, "source": item_source})
    if not items:
        return None
    return {
        "status": str(run_trace.get("status") or "completed"),
        "items": items,
    }


def _merge_run_work_trace_item(items: list[dict[str, Any]], item: dict[str, Any]) -> None:
    item_type = str(item.get("type") or "summary").strip() or "summary"
    item_source = str(item.get("source") or "").strip()
    item_text = str(item.get("text") or "").strip()
    if not item_text:
        return
    for index in range(len(items) - 1, -1, -1):
        existing = items[index]
        if str(existing.get("type") or "summary") != item_type:
            continue
        if str(existing.get("source") or "").strip() != item_source:
            continue
        existing_text = str(existing.get("text") or "").strip()
        if existing_text == item_text or item_text.startswith(existing_text) or existing_text.startswith(item_text):
            items[index] = {
                "type": item_type,
                "text": item_text if len(item_text) >= len(existing_text) else existing_text,
                "source": item_source,
            }
            return
    items.append({"type": item_type, "text": item_text, "source": item_source})


def _work_trace_tool_start_detail(name: str, data: dict[str, Any]) -> str:
    args = _work_trace_tool_args(data.get("arguments"))
    if name == "skills_list":
        category = _work_trace_clean_text(args.get("category"))
        return f"Checking available skills{f' in category {category}' if category else ''}..."
    if name == "skill_view":
        skill_name = _work_trace_clean_text(args.get("name"))
        file_path = _work_trace_clean_text(args.get("file_path") or args.get("filePath"))
        return f"Loading skill: {skill_name or 'instructions'}{f' -> {file_path}' if file_path else ''}..."
    if name == "search_notes":
        query = _work_trace_clean_text(args.get("query"))
        return f"Searching paper notes{f': {query}' if query else ''}..."
    if name == "get_note_context":
        return "Reading note context..."
    if name == "create_image_artifact":
        return "Generating image..."
    if name == "read_paper":
        return "Reading paper source..."
    if name == "review_note":
        return "Reviewing note..."
    if name in {"write_note", "manage_annotations", "write_note_media", "write_note_section", "append_note_section", "replace_note_section", "update_note_metadata"}:
        return "Updating note..."
    if name == "read_note_html":
        return "Reading note HTML..."
    if name == "list_note_sections":
        return "Reading note outline..."
    if name == "persistent_memory":
        return "Checking saved memory..."
    if name == "session_search":
        return "Searching past sessions..."
    if name == "todo":
        return "Updating task list..."
    if name == "web_search":
        return "Searching the web..."
    if name == "web_fetch":
        return "Reading web page..."
    return f"Using {name}{_work_trace_argument_suffix(args)}..."


def _work_trace_tool_result_detail(name: str, data: dict[str, Any]) -> str:
    snapshot = data.get("snapshot") if isinstance(data.get("snapshot"), dict) else {}
    changed_files = snapshot.get("changedFiles") if isinstance(snapshot.get("changedFiles"), list) else []
    if changed_files:
        suffix = "s" if len(changed_files) != 1 else ""
        return f"Saved {len(changed_files)} file{suffix}."
    return ""


def _work_trace_tool_error_detail(name: str, data: dict[str, Any]) -> str:
    error = _work_trace_clean_text(data.get("error") or data.get("message"))
    code = _work_trace_clean_text(data.get("code"))
    detail = error or code
    return f"Tool failed: {name}{f' - {detail}' if detail else ''}"


def _work_trace_tool_args(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _work_trace_clean_text(value: Any) -> str:
    return normalize_text(value)


def _is_skill_tool(name: str) -> bool:
    return name in {"skills_list", "skill_view"}


def _work_trace_argument_suffix(args: dict[str, Any]) -> str:
    formatted = _work_trace_format_arguments(args)
    return f" ({formatted})" if formatted else ""


def _work_trace_format_arguments(args: dict[str, Any], *, max_items: int = 4, max_chars: int = 140) -> str:
    if not isinstance(args, dict) or not args:
        return ""
    parts: list[str] = []
    for key in sorted(args):
        value = args.get(key)
        if value in (None, "", [], {}):
            continue
        parts.append(f"{key}: {_work_trace_short_value(value)}")
        if len(parts) >= max_items:
            break
    text = ", ".join(parts)
    return f"{text[:max_chars - 1]}…" if len(text) > max_chars else text


def _work_trace_short_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        return f"[{', '.join(_work_trace_short_value(item) for item in value[:3])}{', …' if len(value) > 3 else ''}]"
    if isinstance(value, dict):
        return "{…}"
    text = _work_trace_clean_text(value).replace("\n", " ")
    if len(text) > 46:
        text = f"{text[:45]}…"
    return json.dumps(text, ensure_ascii=False)


def _debug_trace_matches_message(trace: dict[str, Any], message_text: str) -> bool:
    preview = str(trace.get("preview") or "")
    if preview:
        prefix_length = min(len(preview), len(message_text), 120)
        if prefix_length >= 20 and preview[:prefix_length] == message_text[:prefix_length]:
            return True
        if message_text.startswith(preview[:80]) or preview.startswith(message_text[:80]):
            return True
    if trace.get("status") == "failed" and "assistant request failed" in message_text.lower():
        return True
    return False


def _normalized_trace_match_text(value: Any) -> str:
    return " ".join(_normalize_public_message_links(_message_text(value)).split())


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _public_tool_call_message(tool_call: Any) -> Any:
    if not isinstance(tool_call, dict):
        return tool_call
    public = dict(tool_call)
    public.pop("response_item_id", None)
    public.pop("call_id", None)
    public.pop("thoughtSignature", None)
    public.pop("thought_signature", None)
    return public


def serialize_event(event: AgentEvent) -> dict[str, Any]:
    return {
        "type": event.type,
        "message": event.message,
        "data": event.data,
    }


def _stream_event_name(event: AgentEvent) -> str:
    if event.type == "model_delta":
        return "model_delta"
    if event.type in {"work_trace_delta", "work_trace_item"}:
        return event.type
    if event.type == "tool_call":
        return "tool_call"
    if event.type in {"tool_result", "tool_error"}:
        return "tool_result"
    if event.type == "tool_approval_requested":
        return "approval_required"
    return "progress"


def _stream_event_payload(event: AgentEvent) -> dict[str, Any]:
    if event.type == "model_delta":
        return {
            "delta": str(event.data.get("delta") or ""),
            "text": str(event.data.get("text") or ""),
            "turn": event.data.get("turn"),
        }
    if event.type in {"work_trace_delta", "work_trace_item"}:
        return {
            "delta": str(event.data.get("delta") or ""),
            "text": str(event.data.get("text") or event.message or ""),
            "traceType": str(event.data.get("trace_type") or ""),
            "turn": event.data.get("turn"),
        }
    return {}


def serialize_tool_call(tool_call: ToolCall) -> dict[str, Any]:
    return {
        "id": tool_call.call_id or tool_call.id or "",
        "name": tool_call.name,
        "arguments": tool_call.arguments,
    }


def error_response(error: AgentAPIError) -> dict[str, str]:
    return {
        "error": error.message,
        "code": error.code,
    }


def _prompt_context(body: dict[str, Any]) -> dict[str, Any]:
    raw_context = body.get("context")
    context = dict(raw_context) if isinstance(raw_context, dict) else {}
    note_id = _note_id(body)
    note_title = _optional_text(
        body.get("noteTitle")
        or body.get("note_title")
        or context.get("selectedNoteTitle")
        or context.get("noteTitle")
    )

    if "current_note" not in context and "note" not in context and (note_id or note_title):
        context["current_note"] = {
            "id": note_id,
            "title": note_title,
        }
    current_note = context.get("current_note") if isinstance(context.get("current_note"), dict) else None
    if current_note is not None:
        collection_name = _optional_text(
            context.get("selectedCategoryName")
            or context.get("collectionName")
            or context.get("collection")
        )
        if collection_name and "collectionName" not in current_note:
            current_note["collectionName"] = collection_name
        if collection_name and "collectionPath" not in current_note:
            current_note["collectionPath"] = collection_name
    if "current_page" not in context and "page" not in context:
        page = _optional_int(body.get("currentPage", body.get("page")), minimum=1)
        if page is not None:
            context["current_page"] = page
    if "selection_text" not in context and "selection" not in context:
        selection = _optional_text(body.get("selectionText") or body.get("selection"))
        if selection:
            context["selection_text"] = selection
    if "visible_annotations" not in context and "annotations" not in context:
        annotations = body.get("visibleAnnotations")
        if isinstance(annotations, list):
            context["visible_annotations"] = annotations
    return context


def _query_prompt_context(query: dict[str, list[str]]) -> dict[str, Any]:
    context: dict[str, Any] = {}
    note_id = _query_text(query, "noteId") or _query_text(query, "note_id")
    note_title = _query_text(query, "noteTitle") or _query_text(query, "note_title")
    if note_id or note_title:
        context["current_note"] = {
            "id": note_id,
            "title": note_title,
        }
    page = _query_int(query, "currentPage") or _query_int(query, "page")
    if page is not None:
        context["current_page"] = page
    return context


def _request_metadata(body: dict[str, Any]) -> dict[str, Any]:
    metadata = dict(body.get("metadata")) if isinstance(body.get("metadata"), dict) else {}
    note_id = _note_id(body)
    note_title = _note_title(body)
    if note_id:
        metadata.setdefault("note_id", note_id)
        metadata.setdefault("currentNoteId", note_id)
        metadata.setdefault("current_note_id", note_id)
        metadata.setdefault("originNoteId", note_id)
        metadata.setdefault("origin_note_id", note_id)
    if note_title:
        metadata.setdefault("note_title", note_title)
        metadata.setdefault("currentNoteTitle", note_title)
        metadata.setdefault("current_note_title", note_title)
        metadata.setdefault("originNoteTitle", note_title)
        metadata.setdefault("origin_note_title", note_title)
    return metadata


def _request_options(body: dict[str, Any]) -> dict[str, Any]:
    options = dict(body.get("requestOptions")) if isinstance(body.get("requestOptions"), dict) else {}
    provider = (_provider_or_none(body.get("provider")) or "").lower()
    metadata = body.get("metadata") if isinstance(body.get("metadata"), dict) else {}

    if provider in {"openai", "codex-oauth"}:
        model = _optional_text(body.get("model")).lower()
        think_mode = _optional_text(metadata.get("gptThinkMode") or metadata.get("gpt_think_mode"))
        if not think_mode:
            return options
        normalized = think_mode.strip().lower()
        if normalized == "off":
            if capabilities_for_provider_model(provider, model).supports_reasoning_off:
                options["reasoning"] = {"effort": "none"}
            else:
                reasoning = dict(options.get("reasoning")) if isinstance(options.get("reasoning"), dict) else {}
                options["reasoning"] = {**reasoning, "effort": "low", "summary": reasoning.get("summary") or "auto"}
        elif normalized in {"low", "medium", "high", "xhigh"}:
            reasoning = dict(options.get("reasoning")) if isinstance(options.get("reasoning"), dict) else {}
            options["reasoning"] = {**reasoning, "effort": normalized, "summary": reasoning.get("summary") or "auto"}
        return options

    if provider == "gemini":
        model = _optional_text(body.get("model")).lower()
        think_mode = _optional_text(metadata.get("geminiThinkMode") or metadata.get("gemini_think_mode"))
        if not think_mode:
            return options
        normalized = _normalize_gemini_think_mode(think_mode, model)
        thinking_config: dict[str, Any]
        if model == "gemini-3-pro-preview":
            thinking_config = {"thinkingLevel": normalized}
        elif normalized == "off":
            thinking_config = {"thinkingLevel": "minimal"}
        else:
            thinking_config = {"thinkingLevel": normalized}
        if normalized != "off":
            thinking_config["includeThoughts"] = True
        options["thinkingConfig"] = thinking_config
        options.pop("thinking_config", None)
        return options

    if provider == "anthropic":
        model = _optional_text(body.get("model")).lower()
        think_mode = _optional_text(metadata.get("anthropicThinkMode") or metadata.get("anthropic_think_mode"))
        normalized = _normalize_anthropic_think_mode(think_mode, model)
        if not _anthropic_model_supports_think_mode(model):
            options.pop("thinking", None)
            options.pop("output_config", None)
            options.pop("outputConfig", None)
            return options
        if not think_mode or normalized == "off":
            options["thinking"] = {"type": "disabled"}
            options.pop("output_config", None)
            options.pop("outputConfig", None)
            return options
        output_config = dict(options.get("output_config")) if isinstance(options.get("output_config"), dict) else {}
        options["thinking"] = {"type": "adaptive", "display": "summarized"}
        options["output_config"] = {**output_config, "effort": normalized}
        options.pop("outputConfig", None)
        return options

    if provider != "deepseek":
        return options

    options.pop("_paper_notes_native_web_search", None)
    options.pop("_paper_notes_provider_native_web_search", None)
    think_mode = _optional_text(metadata.get("deepseekThinkMode") or metadata.get("deepseek_think_mode"))
    if not think_mode:
        return options

    normalized = think_mode.strip().lower()
    if normalized == "off":
        options["thinking"] = {"type": "disabled"}
        options.pop("reasoning_effort", None)
        options.pop("reasoningEffort", None)
    elif normalized in {"high", "max"}:
        options["thinking"] = {"type": "enabled"}
        options["reasoning_effort"] = normalized
        options.pop("reasoningEffort", None)
    return options


def _session_metadata_updates(body: dict[str, Any]) -> dict[str, Any]:
    metadata = body.get("metadata")
    if not isinstance(metadata, dict):
        return {}
    updates: dict[str, Any] = {}
    think_mode = _optional_text(metadata.get("deepseekThinkMode") or metadata.get("deepseek_think_mode"))
    if think_mode:
        normalized = think_mode.strip().lower()
        updates["deepseekThinkMode"] = normalized if normalized in {"off", "high", "max"} else "off"
    gpt_think_mode = _optional_text(metadata.get("gptThinkMode") or metadata.get("gpt_think_mode"))
    if gpt_think_mode:
        normalized = gpt_think_mode.strip().lower()
        updates["gptThinkMode"] = normalized if normalized in {"off", "low", "medium", "high", "xhigh"} else "off"
    gemini_think_mode = _optional_text(metadata.get("geminiThinkMode") or metadata.get("gemini_think_mode"))
    if gemini_think_mode:
        model = _optional_text(body.get("model")).lower()
        updates["geminiThinkMode"] = _normalize_gemini_think_mode(gemini_think_mode, model)
    anthropic_think_mode = _optional_text(metadata.get("anthropicThinkMode") or metadata.get("anthropic_think_mode"))
    if anthropic_think_mode:
        model = _optional_text(body.get("model")).lower()
        updates["anthropicThinkMode"] = _normalize_anthropic_think_mode(anthropic_think_mode, model)
    return updates


def _normalize_gemini_think_mode(value: str, model: str = "") -> str:
    normalized = value.strip().lower()
    if model == "gemini-3-pro-preview":
        return normalized if normalized in {"low", "high"} else "high"
    if normalized in {"off", "low", "medium", "high"}:
        return normalized
    return "off"


def _anthropic_model_supports_think_mode(model: str) -> bool:
    return model in {"claude-opus-4-7", "claude-sonnet-4-6"}


def _normalize_anthropic_think_mode(value: str, model: str = "") -> str:
    normalized = value.strip().lower()
    if model == "claude-opus-4-7":
        if normalized in {"off", "low", "medium", "high", "xhigh", "max"}:
            return normalized
        return "medium"
    if model == "claude-sonnet-4-6":
        if normalized in {"off", "low", "medium", "high", "max"}:
            return normalized
        return "medium"
    return "off"


def _chat_attachments(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    attachments: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, str):
            attachment_id = _optional_text(item)
            if attachment_id:
                attachments.append({"id": attachment_id})
            continue
        if not isinstance(item, dict):
            continue
        attachment_id = _optional_text(item.get("id") or item.get("artifactId"))
        if attachment_id:
            attachments.append({"id": attachment_id})
    return attachments


def _image_generation_config(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {
        "enabled": _bool_value(value.get("enabled"), default=False),
        "action": _optional_text(value.get("action")),
        "size": _optional_text(value.get("size")),
        "quality": _optional_text(value.get("quality")),
        "format": _optional_text(value.get("format")),
    }


def _file_generation_config(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {
        "enabled": _bool_value(value.get("enabled"), default=False),
        "format": _optional_text(value.get("format")),
    }


def _model_provider_error_message(body: dict[str, Any]) -> str:
    has_attachments = bool(_chat_attachments(body.get("attachments")))
    image_generation = _image_generation_config(body.get("imageGeneration") or body.get("image_generation"))
    if has_attachments or image_generation.get("enabled"):
        return (
            "Model provider image request failed. Check that the selected provider and model support "
            "image vision or image generation."
        )
    return "Model provider request failed."


def _model_provider_api_public_message(error: ModelProviderAPIError, body: dict[str, Any]) -> str:
    code = str(error.provider_data.get("code") or "")
    if code in {"image_generation_unavailable", "image_input_unavailable", "native_web_search_unavailable"}:
        return str(error) or _model_provider_error_message(body)
    classified = _classified_model_provider_api_message(error, body)
    if classified:
        return classified
    return _model_provider_error_message(body)


def _classified_model_provider_api_message(error: ModelProviderAPIError, body: dict[str, Any]) -> str:
    provider = str(error.provider_data.get("provider") or body.get("provider") or "").strip().lower()
    if provider and provider not in {"openai", "codex-oauth"}:
        return ""
    details = _model_provider_api_error_details(error)
    code = details.get("code", "").lower()
    error_type = details.get("type", "").lower()
    message = details.get("message", "").lower()
    status_code = error.status_code or 0
    if code == "insufficient_quota" or "insufficient_quota" in error_type or "current quota" in message:
        return (
            "OpenAI API quota or credits are exhausted. Check billing or usage limits, "
            "or switch to another provider."
        )
    if code == "invalid_api_key" or status_code == 401:
        return "OpenAI credential was rejected. Check or replace it in Settings."
    if code in {"model_not_found", "model_not_available"} or status_code == 403:
        model = _optional_text(body.get("model"))
        suffix = f" ({model})" if model else ""
        return f"OpenAI API cannot access the selected model{suffix}. Check the model, project, or key permissions."
    if code == "rate_limit_exceeded" or ("rate limit" in message and "quota" not in message):
        return "OpenAI API rate limit was reached. Try again shortly or reduce request rate."
    if status_code == 429:
        return "OpenAI API limit was reached. Check usage limits or try again shortly."
    safe_detail = _safe_openai_invalid_request_detail(details.get("message", ""))
    if status_code == 400 and safe_detail:
        return f"OpenAI API rejected the request: {safe_detail}"
    return ""


def _model_provider_api_error_details(error: ModelProviderAPIError) -> dict[str, str]:
    details = {
        "code": str(error.provider_data.get("api_error_code") or ""),
        "type": str(error.provider_data.get("api_error_type") or ""),
        "param": str(error.provider_data.get("api_error_param") or ""),
        "message": str(error),
    }
    body = _model_provider_api_error_body(error.body)
    if isinstance(body, dict):
        raw_error = body.get("error")
        error_body = raw_error if isinstance(raw_error, dict) else body
        for source_key, target_key in (("code", "code"), ("type", "type"), ("param", "param"), ("message", "message")):
            value = error_body.get(source_key)
            if value not in (None, "", [], {}) and not details.get(target_key):
                details[target_key] = str(value)
    return details


def _model_provider_api_error_body(body: object) -> object:
    if isinstance(body, bytes):
        try:
            body = body.decode("utf-8", errors="replace")
        except Exception:
            return None
    if isinstance(body, str):
        text = body.strip()
        if not text:
            return None
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"message": text}
    return body


def _safe_openai_invalid_request_detail(value: str) -> str:
    text = _optional_text(value)
    if not text:
        return ""
    if re.search(r"(api[_ -]?key|authorization|bearer|secret|token|credential|password)", text, re.IGNORECASE):
        return ""
    text = re.sub(r"\s+", " ", text).strip()
    return text[:240]


def _message_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and item.get("type") in {"text", "input_text"}:
                parts.append(_optional_text(item.get("text") or item.get("content")))
        return "\n".join(part for part in parts if part)
    return str(content or "")


def _normalize_public_message_links(text: str) -> str:
    return _SANDBOX_MEDIA_LINK_RE.sub(r"\1", str(text or ""))


def _session_title(body: dict[str, Any], message: Any) -> str:
    explicit = _optional_text(body.get("title") or body.get("sessionTitle") or body.get("session_title"))
    if explicit:
        return explicit

    if isinstance(message, str):
        message_title = normalize_text(message).splitlines()[0][:80]
        if message_title:
            return message_title

    context = body.get("context") if isinstance(body.get("context"), dict) else {}
    note_title = _optional_text(body.get("noteTitle") or context.get("selectedNoteTitle"))
    if note_title:
        return note_title

    return "New chat"


def _new_debug_request_id() -> str:
    return f"debug-{uuid4()}"


def _debug_finish_result(
    debug_store: DebugRunStore,
    request_id: str,
    result: AgentServiceResult,
    *,
    agent_service: AgentService,
    body: dict[str, Any],
    transport: str,
    events: list[dict[str, Any]] | None = None,
) -> None:
    metadata = result.session.metadata
    debug_store.finish_run(
        request_id,
        status=_debug_status_from_result(result),
        session_id=result.session_id,
        note_id=metadata.note_id or _note_id(body),
        provider=metadata.provider or _optional_text(body.get("provider")),
        model=metadata.model or _optional_text(body.get("model")),
        error={"code": result.error or "", "message": result.error or ""} if result.error else None,
        events=events or [serialize_event(event) for event in result.events if event.type != "model_delta"],
        transcript_path=_debug_transcript_path(agent_service, result.session_id),
        final_message_preview=result.response or "",
        metadata={"transport": transport},
    )


def _debug_finish_error(
    debug_store: DebugRunStore,
    request_id: str,
    transport: str,
    code: str,
    message: str,
    *,
    body: dict[str, Any] | None = None,
    events: list[dict[str, Any]] | None = None,
) -> None:
    payload = body or {}
    if debug_store.get_run(request_id) is None:
        debug_store.start_run(
            request_id=request_id,
            session_id=_optional_text(payload.get("sessionId") or payload.get("session_id")),
            note_id=_note_id(payload),
            provider=_optional_text(payload.get("provider")),
            model=_optional_text(payload.get("model")),
            transport=transport,
            metadata=_debug_request_metadata(payload),
        )
    debug_store.finish_run(
        request_id,
        status="failed",
        session_id=_optional_text(payload.get("sessionId") or payload.get("session_id")),
        note_id=_note_id(payload),
        provider=_optional_text(payload.get("provider")),
        model=_optional_text(payload.get("model")),
        error={"code": code, "message": message},
        events=events or [],
        metadata={"transport": transport},
    )


def _debug_status_from_result(result: AgentServiceResult) -> str:
    if result.cancelled:
        return "cancelled"
    if result.completed:
        return "completed"
    if result.error:
        return "failed"
    if result.pending_tool_calls:
        return "pending"
    return "stopped"


def _debug_request_metadata(body: dict[str, Any]) -> dict[str, Any]:
    attachments = body.get("attachments")
    safe_attachments = []
    request_metadata = body.get("metadata") if isinstance(body.get("metadata"), dict) else {}
    deepseek_think_mode = _optional_text(
        request_metadata.get("deepseekThinkMode") or request_metadata.get("deepseek_think_mode")
    )
    gemini_think_mode = _optional_text(
        request_metadata.get("geminiThinkMode") or request_metadata.get("gemini_think_mode")
    )
    gpt_think_mode = _optional_text(
        request_metadata.get("gptThinkMode") or request_metadata.get("gpt_think_mode")
    )
    anthropic_think_mode = _optional_text(
        request_metadata.get("anthropicThinkMode") or request_metadata.get("anthropic_think_mode")
    )
    if isinstance(attachments, list):
        for attachment in attachments:
            if isinstance(attachment, dict):
                safe_attachments.append({
                    "id": attachment.get("id") or "",
                    "kind": attachment.get("kind") or "",
                    "fileName": attachment.get("fileName") or attachment.get("file_name") or "",
                    "mimeType": attachment.get("mimeType") or attachment.get("mime_type") or "",
                    "source": attachment.get("source") or "",
                })
    return sanitize_debug_payload({
        "enabledToolsets": body.get("enabledToolsets") or body.get("enabled_toolsets"),
        "disabledToolsets": body.get("disabledToolsets") or body.get("disabled_toolsets"),
        "disabledTools": body.get("disabledTools") or body.get("disabled_tools"),
        "writeToolMode": body.get("writeToolMode") or body.get("write_tool_mode"),
        "toolWriteModes": body.get("toolWriteModes") or body.get("tool_write_modes"),
        "maxTurns": body.get("maxTurns") or body.get("max_turns"),
        "requestOptions": _request_options(body),
        "deepseekThinkMode": deepseek_think_mode or None,
        "gptThinkMode": gpt_think_mode or None,
        "geminiThinkMode": gemini_think_mode or None,
        "anthropicThinkMode": anthropic_think_mode or None,
        "attachments": safe_attachments,
        "imageGeneration": body.get("imageGeneration") or body.get("image_generation"),
        "editLatestUserMessage": body.get("editLatestUserMessage") or body.get("edit_latest_user_message"),
    })


def _debug_transcript_path(agent_service: AgentService, session_id: str) -> str:
    if not session_id:
        return ""
    try:
        return str(agent_service.session_store.transcript_path(session_id))
    except Exception:
        return ""


def _note_id(body: dict[str, Any]) -> str:
    context = body.get("context") if isinstance(body.get("context"), dict) else {}
    return _optional_text(
        body.get("noteId")
        or body.get("note_id")
        or body.get("selectedNoteId")
        or context.get("selectedNoteId")
        or context.get("noteId")
    )


def _note_title(body: dict[str, Any]) -> str:
    context = body.get("context") if isinstance(body.get("context"), dict) else {}
    return _optional_text(
        body.get("noteTitle")
        or body.get("note_title")
        or body.get("selectedNoteTitle")
        or context.get("selectedNoteTitle")
        or context.get("noteTitle")
    )


def _request_id(body: dict[str, Any]) -> str:
    return _optional_text(body.get("requestId") or body.get("request_id"))


def _write_tool_mode(body: dict[str, Any]) -> str:
    mode = _optional_text(body.get("writeToolMode") or body.get("write_tool_mode") or body.get("toolWriteMode"))
    normalized = mode.lower()
    return normalized if normalized in {"auto", "warn", "ask", "readonly", "block", "halt"} else "auto"


def _tool_write_modes(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    modes: dict[str, str] = {}
    for raw_name, raw_mode in value.items():
        name = _optional_text(raw_name)
        mode = _optional_text(raw_mode).lower()
        if name and mode in {"auto", "warn", "ask", "readonly", "block", "halt"}:
            modes[name] = mode
    return modes


def _acquire_run_slot(
    runs: AgentRunCoordinator,
    *,
    session_id: str,
    request_id: str,
    progress: AgentProgressStore,
) -> AgentRunHandle | None:
    if not session_id:
        if request_id:
            progress.running(request_id)
        return None

    return runs.acquire(
        session_id,
        request_id=request_id,
        on_queued=lambda handle: progress.queued(handle.request_id) if handle.request_id else None,
        on_running=lambda handle: progress.running(handle.request_id) if handle.request_id else None,
    )


def _cancelled_chat_result(
    service: AgentService,
    session_id: str,
    request_id: str,
) -> dict[str, Any]:
    session = service.session_store.get_session(session_id)
    messages = [serialize_message(message) for message in session.messages] if session else []
    session_payload = serialize_session_metadata(session.metadata) if session else {
        "id": session_id,
        "sessionId": session_id,
    }
    return {
        "sessionId": session_id,
        "session": session_payload,
        "createdSession": False,
        "completed": False,
        "cancelled": True,
        "response": "",
        "message": {
            "role": "assistant",
            "content": "",
            "text": "",
            "error": True,
        },
        "messages": messages,
        "events": [serialize_event(AgentEvent("cancelled", "Agent run cancelled.", {"reason": "cancelled"}))],
        "turns": 0,
        "pendingToolCalls": [],
        "error": "cancelled",
    }


def _fail_progress(progress_store: AgentProgressStore, request_id: str, detail: str) -> None:
    if request_id:
        progress_store.fail(request_id, detail)


def _body_session_id(body: dict[str, Any]) -> str:
    session_id = _optional_text(body.get("sessionId") or body.get("session_id") or body.get("id"))
    if not session_id:
        raise AgentAPIError(HTTPStatus.BAD_REQUEST, "session_id_required", "Session id is required.")
    return session_id


def _body_optional_session_id(body: dict[str, Any]) -> str:
    return _optional_text(body.get("sessionId") or body.get("session_id") or body.get("id"))


def _optional_text(value: Any) -> str:
    return normalize_text(value)


def _optional_text_list(value: Any) -> list[str] | None:
    if value in (None, ""):
        return None
    raw_items: list[Any] = []
    if isinstance(value, list):
        for item in value:
            raw_items.extend(str(item).replace(",", " ").split())
    else:
        raw_items = str(value).replace(",", " ").split()
    items: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        text = _optional_text(item)
        if not text or text in seen:
            continue
        items.append(text)
        seen.add(text)
    return items


def _provider_or_none(value: Any) -> str | None:
    text = _optional_text(value)
    if not text:
        return None
    try:
        return normalize_model_provider_name(text)
    except ValueError as error:
        raise AgentAPIError(HTTPStatus.BAD_REQUEST, "unsupported_provider", str(error)) from error


def _optional_int(value: Any, *, minimum: int | None = None) -> int | None:
    if value in (None, ""):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    if minimum is not None and parsed < minimum:
        return None
    return parsed


def _int_value(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    parsed = _optional_int(value, minimum=minimum)
    if parsed is None:
        return default
    return min(parsed, maximum)


def _bool_value(value: Any, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return default


def _query_text(query: dict[str, list[str]], name: str) -> str:
    return _optional_text((query.get(name) or [""])[0])


def _query_text_list(query: dict[str, list[str]], name: str) -> list[str] | None:
    values = query.get(name)
    if not values:
        return None
    return _optional_text_list(values)


def _query_bool(query: dict[str, list[str]], name: str) -> bool:
    return _bool_value((query.get(name) or ["false"])[0], default=False)


def _query_int(query: dict[str, list[str]], name: str) -> int | None:
    return _optional_int((query.get(name) or [""])[0], minimum=1)
