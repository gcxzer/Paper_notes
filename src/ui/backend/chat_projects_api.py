from __future__ import annotations

import json
import threading
from datetime import UTC, datetime
from http import HTTPStatus
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from agent_sessions import SessionNotFoundError
from app_infra.formatting import normalize_text
from app_infra.paths import LOCAL_STATE_DIR
from app_infra.storage import atomic_write_json
from ui.backend.agent_api import get_agent_service, _metadata_payload


DEFAULT_CHAT_PROJECTS_PATH = LOCAL_STATE_DIR / "chat-projects.json"
_PROJECTS_LOCK = threading.Lock()


class ChatProjectAPIError(ValueError):
    def __init__(self, status: HTTPStatus, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code


def register_chat_project_routes(app: FastAPI) -> None:
    @app.get("/api/chat/projects")
    async def api_list_chat_projects() -> JSONResponse:
        return JSONResponse(list_chat_projects())

    @app.post("/api/chat/projects")
    async def api_create_chat_project(request: Request) -> JSONResponse:
        try:
            return JSONResponse(create_chat_project(await _json_body(request)), status_code=HTTPStatus.CREATED)
        except Exception as error:
            return _chat_project_error_response(error)

    @app.post("/api/chat/project/rename")
    async def api_rename_chat_project(request: Request) -> JSONResponse:
        try:
            payload = rename_chat_project(await _json_body(request))
            payload.update(sync_chat_project_session_metadata(payload["project"]["id"], project_name=payload["project"]["name"]))
            return JSONResponse(payload)
        except Exception as error:
            return _chat_project_error_response(error)

    @app.post("/api/chat/project/delete")
    async def api_delete_chat_project(request: Request) -> JSONResponse:
        try:
            payload = delete_chat_project(await _json_body(request))
            payload.update(sync_chat_project_session_metadata(payload["projectId"], clear=True))
            return JSONResponse(payload)
        except Exception as error:
            return _chat_project_error_response(error)

    @app.post("/api/chat/session/project")
    async def api_update_chat_session_project(request: Request) -> JSONResponse:
        try:
            return JSONResponse(update_chat_session_project(await _json_body(request)))
        except Exception as error:
            return _chat_project_error_response(error)


def list_chat_projects(*, path: str | Path | None = None) -> dict[str, Any]:
    return _read_projects(path=path)


def create_chat_project(body: Any, *, path: str | Path | None = None) -> dict[str, Any]:
    if not isinstance(body, dict):
        raise ChatProjectAPIError(HTTPStatus.BAD_REQUEST, "invalid_body", "Request body must be a JSON object.")
    name = normalize_text(body.get("name") or body.get("title"))
    if not name:
        raise ChatProjectAPIError(HTTPStatus.BAD_REQUEST, "project_name_required", "Project name is required.")
    if len(name) > 80:
        raise ChatProjectAPIError(
            HTTPStatus.BAD_REQUEST,
            "project_name_too_long",
            "Project name must be 80 characters or fewer.",
        )

    now = _now_iso()
    with _PROJECTS_LOCK:
        payload = _read_projects(path=path)
        projects = payload["projects"]
        project = {
            "id": f"project-{uuid4().hex[:12]}",
            "name": name,
            "createdAt": now,
            "updatedAt": now,
            "order": len(projects),
        }
        projects.append(project)
        normalized = _normalize_projects({"projects": projects})
        _write_projects(normalized, path=path)
    return {"project": project, "projects": normalized["projects"]}


def rename_chat_project(body: Any, *, path: str | Path | None = None) -> dict[str, Any]:
    if not isinstance(body, dict):
        raise ChatProjectAPIError(HTTPStatus.BAD_REQUEST, "invalid_body", "Request body must be a JSON object.")
    project_id = _project_id_from_body(body)
    name = normalize_text(body.get("name") or body.get("title"))
    if not name:
        raise ChatProjectAPIError(HTTPStatus.BAD_REQUEST, "project_name_required", "Project name is required.")
    if len(name) > 80:
        raise ChatProjectAPIError(
            HTTPStatus.BAD_REQUEST,
            "project_name_too_long",
            "Project name must be 80 characters or fewer.",
        )

    now = _now_iso()
    with _PROJECTS_LOCK:
        payload = _read_projects(path=path)
        projects: list[dict[str, Any]] = []
        updated_project: dict[str, Any] | None = None
        for project in payload["projects"]:
            if project["id"] == project_id:
                updated_project = {**project, "name": name, "updatedAt": now}
                projects.append(updated_project)
            else:
                projects.append(project)
        if updated_project is None:
            raise ChatProjectAPIError(HTTPStatus.NOT_FOUND, "project_not_found", f"Project not found: {project_id}")
        normalized = _normalize_projects({"projects": projects})
        _write_projects(normalized, path=path)
    return {"project": updated_project, "projects": normalized["projects"]}


def delete_chat_project(body: Any, *, path: str | Path | None = None) -> dict[str, Any]:
    if not isinstance(body, dict):
        raise ChatProjectAPIError(HTTPStatus.BAD_REQUEST, "invalid_body", "Request body must be a JSON object.")
    project_id = _project_id_from_body(body)

    with _PROJECTS_LOCK:
        payload = _read_projects(path=path)
        existing = next((project for project in payload["projects"] if project["id"] == project_id), None)
        if existing is None:
            raise ChatProjectAPIError(HTTPStatus.NOT_FOUND, "project_not_found", f"Project not found: {project_id}")
        normalized = _normalize_projects({
            "projects": [project for project in payload["projects"] if project["id"] != project_id],
        })
        _write_projects(normalized, path=path)
    return {"deleted": True, "projectId": project_id, "project": existing, "projects": normalized["projects"]}


def update_chat_session_project(body: Any, *, service: Any = None) -> dict[str, Any]:
    if not isinstance(body, dict):
        raise ChatProjectAPIError(HTTPStatus.BAD_REQUEST, "invalid_body", "Request body must be a JSON object.")
    session_id = normalize_text(body.get("sessionId") or body.get("session_id") or body.get("id"))
    if not session_id:
        raise ChatProjectAPIError(HTTPStatus.BAD_REQUEST, "session_id_required", "Session id is required.")

    project_id = normalize_text(body.get("projectId") or body.get("project_id"))
    project_name = normalize_text(body.get("projectName") or body.get("project_name"))
    agent_service = service or get_agent_service()
    try:
        metadata = agent_service.session_store.update_session_metadata(
            session_id,
            _project_metadata(project_id, project_name),
        )
    except SessionNotFoundError as error:
        raise ChatProjectAPIError(HTTPStatus.NOT_FOUND, "session_not_found", str(error)) from error
    return {"session": _metadata_payload(metadata)}


def sync_chat_project_session_metadata(
    project_id: str,
    *,
    project_name: str = "",
    clear: bool = False,
    service: Any = None,
) -> dict[str, Any]:
    normalized_project_id = normalize_text(project_id)
    if not normalized_project_id:
        raise ChatProjectAPIError(HTTPStatus.BAD_REQUEST, "project_id_required", "Project id is required.")

    agent_service = service or get_agent_service()
    updated = 0
    for metadata in agent_service.session_store.list_sessions(include_archived=True):
        session_project_id = _session_project_id(metadata.metadata)
        if session_project_id != normalized_project_id:
            continue
        next_project_id = "" if clear else normalized_project_id
        next_project_name = "" if clear else normalize_text(project_name)
        agent_service.session_store.update_session_metadata(
            metadata.session_id,
            _project_metadata(next_project_id, next_project_name),
        )
        updated += 1
    return {"updatedSessions": updated}


def _read_projects(*, path: str | Path | None = None) -> dict[str, Any]:
    projects_path = Path(path) if path is not None else DEFAULT_CHAT_PROJECTS_PATH
    try:
        raw = json.loads(projects_path.read_text(encoding="utf-8"))
    except Exception:
        raw = {}
    return _normalize_projects(raw)


def _write_projects(payload: dict[str, Any], *, path: str | Path | None = None) -> None:
    projects_path = Path(path) if path is not None else DEFAULT_CHAT_PROJECTS_PATH
    atomic_write_json(projects_path, payload)


def _normalize_projects(payload: Any) -> dict[str, Any]:
    raw = payload if isinstance(payload, dict) else {}
    raw_projects = raw.get("projects") if isinstance(raw.get("projects"), list) else []
    projects: list[dict[str, Any]] = []
    seen: set[str] = set()

    for index, raw_project in enumerate(raw_projects):
        if not isinstance(raw_project, dict):
            continue
        project_id = normalize_text(raw_project.get("id")) or f"project-{index + 1}"
        if project_id in seen:
            continue
        name = normalize_text(raw_project.get("name") or raw_project.get("title"))
        if not name:
            continue
        seen.add(project_id)
        projects.append({
            "id": project_id,
            "name": name[:80],
            "createdAt": normalize_text(raw_project.get("createdAt") or raw_project.get("created_at")),
            "updatedAt": normalize_text(raw_project.get("updatedAt") or raw_project.get("updated_at")),
            "order": _project_order(raw_project.get("order"), index),
        })

    projects.sort(key=lambda project: (project["order"], project["name"].lower(), project["id"]))
    return {"projects": projects}


def _project_order(value: Any, fallback: int) -> int:
    try:
        order = int(value)
    except (TypeError, ValueError):
        return fallback
    return max(0, min(order, 100000))


def _project_id_from_body(body: dict[str, Any]) -> str:
    project_id = normalize_text(body.get("projectId") or body.get("project_id") or body.get("id"))
    if not project_id:
        raise ChatProjectAPIError(HTTPStatus.BAD_REQUEST, "project_id_required", "Project id is required.")
    return project_id


def _project_metadata(project_id: str, project_name: str) -> dict[str, str]:
    return {
        "projectId": project_id,
        "project_id": project_id,
        "projectName": project_name,
        "project_name": project_name,
    }


def _session_project_id(metadata: Any) -> str:
    payload = metadata if isinstance(metadata, dict) else {}
    return normalize_text(payload.get("projectId") or payload.get("project_id"))


async def _json_body(request: Request) -> dict[str, Any]:
    try:
        payload = await request.json()
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _chat_project_error_response(error: Exception) -> JSONResponse:
    if isinstance(error, ChatProjectAPIError):
        return JSONResponse(
            {"success": False, "code": error.code, "error": str(error)},
            status_code=int(error.status),
        )
    return JSONResponse(
        {"success": False, "code": "chat_project_failed", "error": str(error)},
        status_code=HTTPStatus.BAD_REQUEST,
    )


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
