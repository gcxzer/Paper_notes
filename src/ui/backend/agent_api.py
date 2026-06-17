from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from agent_runtime import AgentService
from agent_sessions import SessionNotFoundError
from ui.backend.chat_payloads import message_artifacts


_AGENT_SERVICE: AgentService | None = None


def get_agent_service() -> AgentService:
    global _AGENT_SERVICE
    if _AGENT_SERVICE is None:
        _AGENT_SERVICE = AgentService()
    return _AGENT_SERVICE


def existing_agent_service() -> AgentService | None:
    return _AGENT_SERVICE


def set_agent_service(service: AgentService | None) -> None:
    global _AGENT_SERVICE
    existing = _AGENT_SERVICE
    if existing is not None and existing is not service:
        close = getattr(existing, "close", None)
        if callable(close):
            close()
    _AGENT_SERVICE = service


def reset_agent_service() -> None:
    set_agent_service(None)


def register_agent_routes(app: FastAPI) -> None:
    @app.get("/api/agent/sessions")
    async def api_agent_sessions(
        includeArchived: bool = False,
        state: str = "",
    ) -> JSONResponse:
        sessions = get_agent_service().session_store.list_sessions(
            include_archived=includeArchived,
            state=_text(state) or None,
        )
        return JSONResponse({"success": True, "sessions": [_metadata_payload(session) for session in sessions]})

    @app.get("/api/agent/sessions/{session_id}")
    async def api_agent_session(session_id: str) -> JSONResponse:
        session = get_agent_service().session_store.get_session(session_id)
        if session is None:
            return _agent_error_response(
                SessionNotFoundError(session_id),
                code="session_not_found",
                status_code=404,
            )
        return JSONResponse({"success": True, "session": _session_payload(session)})

    @app.post("/api/agent/sessions/{session_id}/rename")
    async def api_agent_session_rename(session_id: str, request: Request) -> JSONResponse:
        body = await _json_body(request)
        try:
            metadata = get_agent_service().session_store.rename_session(session_id, _text(_first(body, "title")) or "New chat")
        except SessionNotFoundError as error:
            return _agent_error_response(error, code="session_not_found", status_code=404)
        return JSONResponse({"success": True, "session": _metadata_payload(metadata)})

    @app.post("/api/agent/sessions/{session_id}/archive")
    async def api_agent_session_archive(session_id: str, request: Request) -> JSONResponse:
        body = await _json_body(request)
        try:
            metadata = get_agent_service().session_store.archive_session(
                session_id,
                archived=_bool(_first(body, "archived"), default=True),
            )
        except SessionNotFoundError as error:
            return _agent_error_response(error, code="session_not_found", status_code=404)
        return JSONResponse({"success": True, "session": _metadata_payload(metadata)})

    @app.post("/api/agent/sessions/{session_id}/state")
    async def api_agent_session_state(session_id: str, request: Request) -> JSONResponse:
        body = await _json_body(request)
        try:
            metadata = get_agent_service().session_store.update_session_state(
                session_id,
                state=_text(_first(body, "state")) or "active",
            )
        except SessionNotFoundError as error:
            return _agent_error_response(error, code="session_not_found", status_code=404)
        return JSONResponse({"success": True, "session": _metadata_payload(metadata)})

    @app.post("/api/agent/sessions/{session_id}/model")
    async def api_agent_session_model(session_id: str, request: Request) -> JSONResponse:
        body = await _json_body(request)
        provider = _optional_text(_first(body, "provider")) if "provider" in body else None
        model = _optional_text(_first(body, "model")) if "model" in body else None
        metadata_updates = _metadata_updates_from_body(body)
        if provider is None and model is None and not metadata_updates:
            return _agent_error_response(
                ValueError("Provider, model, or metadata is required."),
                code="model_update_required",
                status_code=400,
            )
        agent_service = get_agent_service()
        try:
            session = agent_service.session_store.update_session_model(
                session_id,
                provider=provider,
                model=model,
            )
            if metadata_updates:
                agent_service.session_store.update_session_metadata(session_id, metadata_updates)
                session = agent_service.session_store.require_session(session_id)
        except SessionNotFoundError as error:
            return _agent_error_response(error, code="session_not_found", status_code=404)
        return JSONResponse({"success": True, "session": _session_payload(session)})

    @app.delete("/api/agent/sessions/{session_id}")
    async def api_agent_session_delete(session_id: str) -> JSONResponse:
        try:
            metadata = get_agent_service().session_store.delete_session(session_id)
        except SessionNotFoundError as error:
            return _agent_error_response(error, code="session_not_found", status_code=404)
        return JSONResponse({"success": True, "deletedSession": _metadata_payload(metadata)})


async def _json_body(request: Request) -> dict[str, Any]:
    try:
        payload = await request.json()
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _session_payload(session: Any) -> dict[str, Any]:
    metadata = _metadata_payload(session.metadata)
    raw_metadata = metadata.get("metadata") if isinstance(metadata.get("metadata"), dict) else {}
    return {
        **metadata,
        "metadata": raw_metadata,
        "messages": _session_messages_payload(session.messages),
    }


def _session_messages_payload(messages: Any) -> list[Any]:
    raw_messages = _jsonable(messages)
    if not isinstance(raw_messages, list):
        return []
    return [_session_message_payload(message) for message in raw_messages]


def _session_message_payload(message: Any) -> Any:
    if not isinstance(message, dict):
        return message
    payload = dict(message)
    artifacts = message_artifacts(payload)
    if artifacts:
        payload["artifacts"] = artifacts
    return payload


def _metadata_payload(metadata: Any) -> dict[str, Any]:
    payload = metadata.to_dict() if hasattr(metadata, "to_dict") else _jsonable(metadata)
    if not isinstance(payload, dict):
        return {}
    extra = dict(payload.get("metadata")) if isinstance(payload.get("metadata"), dict) else {}
    session_id = _text(payload.get("session_id"))
    note_id = _text(payload.get("note_id"))
    origin_note_id = _metadata_text(extra, "originNoteId") or note_id
    origin_note_title = _metadata_text(extra, "originNoteTitle")
    current_note_id = _metadata_text(extra, "currentNoteId") or origin_note_id
    current_note_title = _metadata_text(extra, "currentNoteTitle") or origin_note_title
    project_id = _metadata_text(extra, "projectId")
    project_name = _metadata_text(extra, "projectName")
    state = _session_state(payload)
    active_run = _metadata_dict(extra, "activeRun")
    return {
        "id": session_id,
        "sessionId": session_id,
        "title": _text(payload.get("title")) or "New chat",
        "createdAt": _text(payload.get("created_at")),
        "updatedAt": _text(payload.get("updated_at")),
        "dateBucket": _text(payload.get("date_bucket")),
        "noteId": origin_note_id or note_id,
        "originNoteId": origin_note_id,
        "originNoteTitle": origin_note_title,
        "currentNoteId": current_note_id,
        "currentNoteTitle": current_note_title,
        "provider": payload.get("provider"),
        "model": payload.get("model"),
        "messageCount": _metadata_int(payload.get("message_count")),
        "projectId": project_id,
        "projectName": project_name,
        "archivedAt": _metadata_text(extra, "archivedAt"),
        "trashedAt": _metadata_text(extra, "trashedAt"),
        "deepseekThinkMode": _metadata_text(extra, "deepseekThinkMode"),
        "gptThinkMode": _metadata_text(extra, "gptThinkMode"),
        "activeRun": active_run,
        "metadata": extra,
        "state": state,
        "archived": state == "archived",
        "trashed": state == "trashed",
    }


def _metadata_text(metadata: dict[str, Any], key: str) -> str:
    return _text(metadata.get(key)) if key in metadata else ""


def _metadata_dict(metadata: dict[str, Any], key: str) -> dict[str, Any] | None:
    value = metadata.get(key)
    return value if isinstance(value, dict) else None


def _metadata_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _session_state(payload: dict[str, Any]) -> str:
    state = _text(payload.get("state")).lower()
    if state in {"active", "archived", "trashed"}:
        return state
    return "archived" if _bool(payload.get("archived")) else "active"


def _agent_error_response(error: Exception, *, code: str, status_code: int) -> JSONResponse:
    return JSONResponse(
        {"success": False, "error": str(error), "code": code},
        status_code=status_code,
    )


def _text(value: Any) -> str:
    return str(value or "").strip()


def _optional_text(value: Any) -> str | None:
    text = _text(value)
    return text or None


def _first(payload: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in payload:
            return payload[key]
    return None


def _metadata_updates_from_body(body: dict[str, Any]) -> dict[str, Any]:
    metadata = _first(body, "metadata")
    return metadata if isinstance(metadata, dict) else {}


def _bool(value: Any, *, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _jsonable(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return _jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    return value
