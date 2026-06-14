from __future__ import annotations

from typing import Any


def get_field(value: Any, name: str) -> Any:
    if value is None:
        return None
    if isinstance(value, dict):
        return value.get(name)
    return getattr(value, name, None)


def first_field(value: Any, *names: str) -> Any:
    for name in names:
        found = get_field(value, name)
        if found is not None:
            return found
    return None


def json_safe_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, list):
        return [json_safe_value(item) for item in value]
    if isinstance(value, tuple):
        return [json_safe_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): json_safe_value(item) for key, item in value.items()}
    return str(value)


def format_exception(error: BaseException) -> str:
    text = str(error).strip()
    if text:
        return text
    return repr(error)


__all__ = [
    "first_field",
    "format_exception",
    "get_field",
    "json_safe_value",
]
