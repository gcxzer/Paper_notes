from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app_infra.files import LOCAL_STATE_DIR, atomic_write_json
from app_infra.formatting import normalize_text


DEFAULT_SAVED_PROMPTS_PATH = LOCAL_STATE_DIR / "saved-prompts.json"
FILE_GENERATION_FORMATS = {"markdown", "text", "json", "csv", "html"}


def register_saved_prompt_routes(app: FastAPI) -> None:
    @app.get("/api/saved-prompts")
    async def api_read_saved_prompts() -> JSONResponse:
        return JSONResponse(read_saved_prompts())

    @app.post("/api/saved-prompts")
    async def api_write_saved_prompts(request: Request) -> JSONResponse:
        return JSONResponse(write_saved_prompts(await _read_json_body(request)))


def read_saved_prompts(*, path: str | Path | None = None) -> dict[str, Any]:
    saved_prompts_path = Path(path) if path is not None else DEFAULT_SAVED_PROMPTS_PATH
    try:
        raw = json.loads(saved_prompts_path.read_text(encoding="utf-8"))
    except Exception:
        raw = {}
    return normalize_saved_prompts(raw)


def write_saved_prompts(payload: Any, *, path: str | Path | None = None) -> dict[str, Any]:
    saved_prompts_path = Path(path) if path is not None else DEFAULT_SAVED_PROMPTS_PATH
    normalized = normalize_saved_prompts(payload)
    atomic_write_json(saved_prompts_path, normalized)
    return normalized


def normalize_saved_prompts(payload: Any) -> dict[str, Any]:
    raw_prompts = _raw_prompts(payload)
    prompts: list[dict[str, Any]] = []
    seen: set[str] = set()

    for index, raw_prompt in enumerate(raw_prompts):
        if not isinstance(raw_prompt, dict):
            continue
        prompt_id = normalize_text(raw_prompt.get("id")) or f"prompt-{index + 1}"
        if prompt_id in seen:
            continue
        content = normalize_text(raw_prompt.get("content"))
        if not content:
            continue
        seen.add(prompt_id)
        title = normalize_text(raw_prompt.get("title")) or _title_from_content(content)
        prompts.append({
            "id": prompt_id,
            "title": title,
            "content": content,
            "toolMode": _tool_mode(raw_prompt.get("toolMode") or _nested_tool_value(raw_prompt, "mode")),
            "fileFormat": _file_format(raw_prompt.get("fileFormat") or _nested_tool_value(raw_prompt, "format")),
            "iconType": _icon_type(raw_prompt.get("iconType") or _nested_icon_value(raw_prompt, "type")),
            "iconValue": normalize_text(raw_prompt.get("iconValue") or _nested_icon_value(raw_prompt, "value")) or "bookmark",
            "createdAt": normalize_text(raw_prompt.get("createdAt")),
            "updatedAt": normalize_text(raw_prompt.get("updatedAt") or raw_prompt.get("createdAt")),
        })

    prompts.sort(key=lambda prompt: str(prompt.get("updatedAt") or ""), reverse=True)
    return {"prompts": prompts}


def _raw_prompts(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and isinstance(payload.get("prompts"), list):
        return payload["prompts"]
    return []


def _nested_tool_value(raw_prompt: dict[str, Any], key: str) -> Any:
    tool = raw_prompt.get("tool")
    return tool.get(key) if isinstance(tool, dict) else None


def _nested_icon_value(raw_prompt: dict[str, Any], key: str) -> Any:
    icon = raw_prompt.get("icon")
    return icon.get(key) if isinstance(icon, dict) else None


def _tool_mode(value: Any) -> str:
    mode = normalize_text(value).lower()
    return mode if mode in {"image", "file"} else ""


def _file_format(value: Any) -> str:
    file_format = normalize_text(value).lower()
    return file_format if file_format in FILE_GENERATION_FORMATS else "markdown"


def _icon_type(value: Any) -> str:
    icon_type = normalize_text(value).lower()
    return icon_type if icon_type in {"emoji", "icon"} else "icon"


def _title_from_content(content: str) -> str:
    first_line = next((line.strip() for line in normalize_text(content).splitlines() if line.strip()), "")
    title = first_line or "Untitled prompt"
    return f"{title[:53]}..." if len(title) > 56 else title


async def _read_json_body(request: Request) -> Any:
    try:
        return await request.json()
    except Exception:
        return {}
