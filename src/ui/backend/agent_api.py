from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from agent_runtime import AgentService
from agent_sessions import SessionNotFoundError


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
    return {
        **metadata,
        "metadata": metadata,
        "messages": _jsonable(session.messages),
    }


def _metadata_payload(metadata: Any) -> dict[str, Any]:
    payload = metadata.to_dict() if hasattr(metadata, "to_dict") else _jsonable(metadata)
    if not isinstance(payload, dict):
        return {}
    extra = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    session_id = payload.get("session_id", "")
    origin_note_id = _text(
        extra.get("originNoteId")
        or extra.get("origin_note_id")
        or extra.get("note_id")
        or payload.get("note_id")
    )
    origin_note_title = _text(
        extra.get("originNoteTitle")
        or extra.get("origin_note_title")
        or extra.get("noteTitle")
        or extra.get("note_title")
    )
    current_note_id = _text(extra.get("currentNoteId") or extra.get("current_note_id") or origin_note_id)
    current_note_title = _text(extra.get("currentNoteTitle") or extra.get("current_note_title") or origin_note_title)
    project_id = _text(payload.get("projectId") or payload.get("project_id") or extra.get("projectId") or extra.get("project_id"))
    project_name = _text(
        payload.get("projectName") or payload.get("project_name") or extra.get("projectName") or extra.get("project_name")
    )
    state = _text(payload.get("state")) or ("archived" if payload.get("archived") else "active")
    return {
        **payload,
        "id": session_id,
        "sessionId": session_id,
        "createdAt": payload.get("created_at", ""),
        "updatedAt": payload.get("updated_at", ""),
        "dateBucket": payload.get("date_bucket", ""),
        "noteId": origin_note_id or payload.get("note_id"),
        "originNoteId": origin_note_id,
        "originNoteTitle": origin_note_title,
        "currentNoteId": current_note_id,
        "currentNoteTitle": current_note_title,
        "messageCount": payload.get("message_count", 0),
        "projectId": project_id,
        "projectName": project_name,
        "archivedAt": _text(extra.get("archivedAt") or extra.get("archived_at")),
        "trashedAt": _text(extra.get("trashedAt") or extra.get("trashed_at")),
        "deepseekThinkMode": _text(extra.get("deepseekThinkMode") or extra.get("deepseek_think_mode")),
        "gptThinkMode": _text(extra.get("gptThinkMode") or extra.get("gpt_think_mode")),
        "geminiThinkMode": _text(extra.get("geminiThinkMode") or extra.get("gemini_think_mode")),
        "anthropicThinkMode": _text(extra.get("anthropicThinkMode") or extra.get("anthropic_think_mode")),
        "state": state,
        "archived": state == "archived",
        "trashed": state == "trashed",
    }


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
