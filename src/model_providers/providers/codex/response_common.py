from __future__ import annotations

import json
from typing import Any

from app_infra.artifact_generation import image_generation_provider_options


CODEX_PROVIDER_NAME = "codex-oauth"


def image_generation_options(options: dict[str, Any]) -> dict[str, Any]:
    return image_generation_provider_options(options)


def content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text", item.get("content", ""))
                if isinstance(text, str):
                    parts.append(text)
                else:
                    parts.append(json.dumps(item, ensure_ascii=False))
            else:
                parts.append(str(item))
        return "\n".join(part for part in parts if part)
    return str(content) if content is not None else ""


def combine_instructions(*parts: str | None) -> str:
    return "\n\n".join(part.strip() for part in parts if isinstance(part, str) and part.strip())


def merge_include(current: Any, values: list[str]) -> list[str]:
    items: list[str] = []
    if isinstance(current, str) and current.strip():
        items.append(current.strip())
    elif isinstance(current, list):
        items.extend(str(item) for item in current if str(item or "").strip())
    for value in values:
        if value not in items:
            items.append(value)
    return items


def normalize_phase(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


def get_attr(item: Any, name: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(name, default)
    return getattr(item, name, default)


def set_attr(item: Any, name: str, value: Any) -> None:
    if isinstance(item, dict):
        item[name] = value
        return
    try:
        setattr(item, name, value)
    except Exception:
        pass


def first_int(value: Any, *keys: str) -> int:
    for key in keys:
        raw = get_attr(value, key, None)
        if isinstance(raw, bool):
            continue
        try:
            number = int(raw)
        except (TypeError, ValueError):
            continue
        if number >= 0:
            return number
    return 0


def json_safe(value: Any) -> Any:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, list | tuple | set):
        return [json_safe(item) for item in value]
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        try:
            return json_safe(model_dump(by_alias=True, mode="json"))
        except TypeError:
            return json_safe(model_dump())
    return str(getattr(value, "value", value))


__all__ = [
    "CODEX_PROVIDER_NAME",
    "combine_instructions",
    "content_text",
    "first_int",
    "get_attr",
    "image_generation_options",
    "json_safe",
    "merge_include",
    "normalize_phase",
    "set_attr",
]
