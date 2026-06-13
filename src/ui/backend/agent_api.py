from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from agent_runtime import AgentService, AgentServiceRequest
from agent_sessions import SessionNotFoundError


_AGENT_SERVICE: AgentService | None = None


def get_agent_service() -> AgentService:
    global _AGENT_SERVICE
    if _AGENT_SERVICE is None:
        _AGENT_SERVICE = AgentService()
    return _AGENT_SERVICE


def register_agent_routes(app: FastAPI) -> None:
    @app.post("/api/agent/run")
    async def api_agent_run(request: Request) -> JSONResponse:
        body = await _json_body(request)
        try:
            result = get_agent_service().run(_agent_request_from_body(body))
        except SessionNotFoundError as error:
            return _agent_error_response(error, code="session_not_found", status_code=404)
        except Exception as error:
            return _agent_error_response(error, code="agent_run_failed", status_code=400)
        return JSONResponse({"success": True, **_agent_result_payload(result)})

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

    @app.get("/api/agent/sessions/{session_id}/context")
    async def api_agent_session_context(
        session_id: str,
        provider: str = "",
        model: str = "",
        enableTools: bool = True,
    ) -> JSONResponse:
        try:
            status = get_agent_service().context_status(
                session_id=session_id,
                provider=_text(provider),
                model=_text(model),
                enable_tools=enableTools,
            )
        except SessionNotFoundError as error:
            return _agent_error_response(error, code="session_not_found", status_code=404)
        except Exception as error:
            return _agent_error_response(error, code="context_status_failed", status_code=400)
        return JSONResponse({"success": True, "context": status.to_dict()})

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


def _agent_request_from_body(body: dict[str, Any]) -> AgentServiceRequest:
    metadata = _first(body, "metadata")
    return AgentServiceRequest(
        message=_first(body, "message", "content"),
        session_id=_optional_text(_first(body, "sessionId", "session_id")),
        title=_text(_first(body, "title")) or "New chat",
        note_id=_optional_text(_first(body, "noteId", "note_id")),
        provider=_text(_first(body, "provider")),
        model=_text(_first(body, "model")),
        system_prompt=_optional_text(_first(body, "systemPrompt", "system_prompt")),
        enable_tools=_bool(_first(body, "enableTools", "enable_tools"), default=True),
        metadata=metadata if isinstance(metadata, dict) else {},
        run_config=_first(body, "runConfig", "run_config") if isinstance(_first(body, "runConfig", "run_config"), dict) else None,
        stream_mode=_text(_first(body, "streamMode", "stream_mode")) or "values",
        debug=_bool(_first(body, "debug")),
    )


def _agent_result_payload(result: Any) -> dict[str, Any]:
    return {
        "sessionId": result.session_id,
        "completed": bool(result.completed),
        "response": result.response,
        "messages": _jsonable(result.messages),
        "createdSession": bool(result.created_session),
        "error": result.error,
        "session": _session_payload(result.session),
    }


def _session_payload(session: Any) -> dict[str, Any]:
    return {
        "metadata": _metadata_payload(session.metadata),
        "messages": _jsonable(session.messages),
    }


def _metadata_payload(metadata: Any) -> dict[str, Any]:
    payload = metadata.to_dict() if hasattr(metadata, "to_dict") else _jsonable(metadata)
    if not isinstance(payload, dict):
        return {}
    return {
        **payload,
        "sessionId": payload.get("session_id", ""),
        "createdAt": payload.get("created_at", ""),
        "updatedAt": payload.get("updated_at", ""),
        "dateBucket": payload.get("date_bucket", ""),
        "noteId": payload.get("note_id"),
        "messageCount": payload.get("message_count", 0),
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
