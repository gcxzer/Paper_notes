from __future__ import annotations

import json
import threading
from datetime import UTC, datetime
from http import HTTPStatus
from pathlib import Path
from typing import Any
from uuid import uuid4

from app_config.secrets import LOCAL_STATE_DIR
from app_infra.formatting import normalize_text
from app_infra.storage import atomic_write_json

from .agent_api import AgentAPIError


DEFAULT_CHAT_PROJECTS_PATH = LOCAL_STATE_DIR / "chat-projects.json"
_PROJECTS_LOCK = threading.Lock()


def list_chat_projects(*, path: str | Path | None = None) -> dict[str, Any]:
    return _read_projects(path=path)


def create_chat_project(body: Any, *, path: str | Path | None = None) -> dict[str, Any]:
    if not isinstance(body, dict):
        raise AgentAPIError(HTTPStatus.BAD_REQUEST, "invalid_body", "Request body must be a JSON object.")
    name = normalize_text(body.get("name") or body.get("title"))
    if not name:
        raise AgentAPIError(HTTPStatus.BAD_REQUEST, "project_name_required", "Project name is required.")
    if len(name) > 80:
        raise AgentAPIError(HTTPStatus.BAD_REQUEST, "project_name_too_long", "Project name must be 80 characters or fewer.")

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
        raise AgentAPIError(HTTPStatus.BAD_REQUEST, "invalid_body", "Request body must be a JSON object.")
    project_id = _project_id_from_body(body)
    name = normalize_text(body.get("name") or body.get("title"))
    if not name:
        raise AgentAPIError(HTTPStatus.BAD_REQUEST, "project_name_required", "Project name is required.")
    if len(name) > 80:
        raise AgentAPIError(HTTPStatus.BAD_REQUEST, "project_name_too_long", "Project name must be 80 characters or fewer.")

    now = _now_iso()
    with _PROJECTS_LOCK:
        payload = _read_projects(path=path)
        projects = []
        updated_project: dict[str, Any] | None = None
        for project in payload["projects"]:
            if project["id"] == project_id:
                updated_project = {**project, "name": name, "updatedAt": now}
                projects.append(updated_project)
            else:
                projects.append(project)
        if updated_project is None:
            raise AgentAPIError(HTTPStatus.NOT_FOUND, "project_not_found", f"Project not found: {project_id}")
        normalized = _normalize_projects({"projects": projects})
        _write_projects(normalized, path=path)
    return {"project": updated_project, "projects": normalized["projects"]}


def delete_chat_project(body: Any, *, path: str | Path | None = None) -> dict[str, Any]:
    if not isinstance(body, dict):
        raise AgentAPIError(HTTPStatus.BAD_REQUEST, "invalid_body", "Request body must be a JSON object.")
    project_id = _project_id_from_body(body)

    with _PROJECTS_LOCK:
        payload = _read_projects(path=path)
        existing = next((project for project in payload["projects"] if project["id"] == project_id), None)
        if existing is None:
            raise AgentAPIError(HTTPStatus.NOT_FOUND, "project_not_found", f"Project not found: {project_id}")
        normalized = _normalize_projects({
            "projects": [project for project in payload["projects"] if project["id"] != project_id],
        })
        _write_projects(normalized, path=path)
    return {"deleted": True, "projectId": project_id, "project": existing, "projects": normalized["projects"]}


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
        raise AgentAPIError(HTTPStatus.BAD_REQUEST, "project_id_required", "Project id is required.")
    return project_id


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
