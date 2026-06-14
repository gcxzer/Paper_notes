from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app_infra.formatting import normalize_text
from app_infra.storage import atomic_write_json, atomic_write_text
from tools.skills import DEFAULT_SKILL_SETTINGS_PATH, SkillStore, default_skill_roots
from tools.skills.settings import normalize_disabled_skills, normalize_external_directories, skill_settings_path


_FRONTMATTER_RE = re.compile(r"\A---[ \t]*\r?\n(?P<frontmatter>[\s\S]*?)\r?\n---[ \t]*(?:\r?\n|$)")
_MAX_SKILL_DESCRIPTION_LENGTH = 2000
_MAX_SKILL_CONTENT_LENGTH = 200_000


def register_skills_routes(app: FastAPI) -> None:
    @app.get("/api/skills")
    async def api_list_skills(category: str = "") -> JSONResponse:
        return JSONResponse(list_skills(category=category))

    @app.get("/api/skills/view")
    async def api_view_skill(name: str = "", filePath: str = "", file_path: str = "") -> JSONResponse:
        try:
            return JSONResponse(view_skill(name=name, file_path=filePath or file_path))
        except Exception as error:
            return _skills_error_response(error)

    @app.post("/api/skills/settings")
    async def api_update_skill_settings(request: Request) -> JSONResponse:
        try:
            return JSONResponse(update_skill_settings(await _json_body(request)))
        except Exception as error:
            return _skills_error_response(error)

    @app.post("/api/skills/update")
    async def api_update_skill(request: Request) -> JSONResponse:
        try:
            return JSONResponse(update_skill(await _json_body(request)))
        except Exception as error:
            return _skills_error_response(error)


def list_skills(category: str = "", *, settings_path: str | Path | None = None) -> dict[str, Any]:
    payload = SkillStore(default_skill_roots(settings_path), settings_path=settings_path).list(
        category=normalize_text(category),
        include_disabled=True,
        include_enabled_state=True,
    )
    payload.update(_skill_settings_payload(settings_path=settings_path))
    return payload


def view_skill(name: str, file_path: str = "", *, settings_path: str | Path | None = None) -> dict[str, Any]:
    normalized_name = normalize_text(name)
    if not normalized_name:
        raise ValueError("Skill name is required.")
    return SkillStore(default_skill_roots(settings_path), settings_path=settings_path).view(
        name=normalized_name,
        file_path=normalize_text(file_path),
        include_disabled=True,
        include_enabled_state=True,
    )


def update_skill(body: Any, *, settings_path: str | Path | None = None) -> dict[str, Any]:
    if not isinstance(body, dict):
        raise ValueError("Request body must be a JSON object.")
    name = normalize_text(body.get("name"))
    if not name:
        raise ValueError("Skill name is required.")
    description = normalize_text(body.get("description"))
    if len(description) > _MAX_SKILL_DESCRIPTION_LENGTH:
        raise ValueError("Skill description is too long.")
    content_value = body.get("content")
    if not isinstance(content_value, str):
        raise ValueError("Skill content is required.")
    if len(content_value) > _MAX_SKILL_CONTENT_LENGTH:
        raise ValueError("Skill content is too long.")

    store = SkillStore(default_skill_roots(settings_path))
    record = store.find_record(name)
    if record is None:
        raise ValueError(f"Skill '{name}' not found.")
    skill_md = Path(record["skill_md"]).expanduser().resolve()
    if skill_md.name != "SKILL.md":
        raise ValueError("Only folder-based SKILL.md skills can be edited.")
    if skill_md.is_symlink():
        raise ValueError("Symlinked skills cannot be edited.")
    original = skill_md.read_text(encoding="utf-8")
    next_markdown = _replace_skill_markdown(
        original,
        name=str(record["name"]),
        description=description,
        content=content_value,
    )
    atomic_write_text(skill_md, next_markdown)
    _reset_agent_service()
    return view_skill(name, settings_path=settings_path)


def update_skill_settings(body: Any, *, settings_path: str | Path | None = None) -> dict[str, Any]:
    if not isinstance(body, dict):
        raise ValueError("Request body must be a JSON object.")
    path = skill_settings_path(settings_path)
    existing = _read_settings_path(path)
    external_directories = normalize_external_directories(
        body.get(
            "externalDirectories",
            body.get(
                "external_directories",
                existing.get("externalDirectories", existing.get("external_directories", [])),
            ),
        )
    )
    disabled_skills = normalize_disabled_skills(
        body.get(
            "disabledSkills",
            body.get("disabled_skills", existing.get("disabledSkills", existing.get("disabled_skills", []))),
        )
    )
    atomic_write_json(path, {"externalDirectories": external_directories, "disabledSkills": disabled_skills})
    _reset_agent_service()
    return _skill_settings_payload(settings_path=settings_path)


def _skill_settings_payload(*, settings_path: str | Path | None = None) -> dict[str, Any]:
    path = skill_settings_path(settings_path)
    settings = _read_settings_path(path)
    external_directories = normalize_external_directories(
        settings.get("externalDirectories", settings.get("external_directories", []))
    )
    disabled_skills = normalize_disabled_skills(settings.get("disabledSkills", settings.get("disabled_skills", [])))
    return {
        "success": True,
        "settingsPath": str(path),
        "disabledSkills": disabled_skills,
        "externalDirectories": [
            {
                "path": directory,
                "exists": Path(directory).expanduser().exists(),
            }
            for directory in external_directories
        ],
        "defaultRoots": [str(path) for path in default_skill_roots(settings_path)[:2]],
        "uiHint": (
            "Add skills by placing SKILL.md folders in .paper-notes/skills or src/skills, "
            "or add another folder under External directories."
        ),
        "hint": "Use skill_view(name) to load full SKILL.md content and linked files.",
    }


def _read_settings_path(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        import json

        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _replace_skill_markdown(original: str, *, name: str, description: str, content: str) -> str:
    body = content.replace("\r\n", "\n").replace("\r", "\n").strip()
    frontmatter = ""
    match = _FRONTMATTER_RE.match(original)
    if match:
        frontmatter = match.group("frontmatter").strip("\n")
    if not frontmatter:
        frontmatter = f"name: {_yaml_scalar(name)}"
    frontmatter = _set_frontmatter_scalar(frontmatter, "name", name)
    frontmatter = _set_frontmatter_scalar(frontmatter, "description", description)
    return f"---\n{frontmatter.rstrip()}\n---\n\n{body}\n"


def _set_frontmatter_scalar(frontmatter: str, key: str, value: str) -> str:
    replacement = f"{key}: {_yaml_scalar(value)}"
    pattern = re.compile(rf"^({re.escape(key)}\s*:\s*).*$", re.MULTILINE)
    if pattern.search(frontmatter):
        return pattern.sub(replacement, frontmatter, count=1)
    lines = frontmatter.splitlines()
    insert_at = 1 if key == "description" and lines and lines[0].startswith("name:") else len(lines)
    lines.insert(insert_at, replacement)
    return "\n".join(lines)


def _yaml_scalar(value: str) -> str:
    text = str(value or "").replace("\r\n", " ").replace("\r", " ").replace("\n", " ").strip()
    if _can_use_plain_yaml_scalar(text):
        return text
    return "'" + text.replace("'", "''") + "'"


def _can_use_plain_yaml_scalar(text: str) -> bool:
    if not text:
        return False
    lowered = text.lower()
    if lowered in {"null", "true", "false", "~"}:
        return False
    if text != text.strip():
        return False
    if text[0] in "-?:,[]{}#&*!|>'\"%@`":
        return False
    if re.search(r":(?:\s|$)|(?:^|\s)#", text):
        return False
    if re.search(r"\s", text):
        return True
    if re.fullmatch(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?", text):
        return False
    return True


def _reset_agent_service() -> None:
    from ui.backend.agent_api import set_agent_service

    set_agent_service(None)


async def _json_body(request: Request) -> dict[str, Any]:
    try:
        payload = await request.json()
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _skills_error_response(error: Exception) -> JSONResponse:
    return JSONResponse(
        {"success": False, "error": str(error) or "Skills request failed."},
        status_code=400,
    )


__all__ = [
    "DEFAULT_SKILL_SETTINGS_PATH",
    "list_skills",
    "register_skills_routes",
    "update_skill",
    "update_skill_settings",
    "view_skill",
]
