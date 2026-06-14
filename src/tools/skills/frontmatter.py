from __future__ import annotations

import re
import sys
from typing import Any

from tools.skills.constants import PLATFORM_MAP


_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*(?:\n|\Z)", re.DOTALL)


def parse_frontmatter(content: str) -> tuple[dict[str, Any], str]:
    match = _FRONTMATTER_RE.match(content)
    if not match:
        return {}, content
    return parse_simple_yaml(match.group(1)), content[match.end():]


def parse_simple_yaml(text: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    stack: list[tuple[int, dict[str, Any]]] = [(-1, result)]
    last_key_by_indent: dict[int, str] = {}
    for raw_line in text.splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        line = raw_line.strip()
        while stack and indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]
        if line.startswith("- "):
            if len(stack) >= 2:
                grandparent = stack[-2][1]
                key = last_key_by_indent.get(stack[-1][0])
                if key and grandparent.get(key) is parent:
                    existing = grandparent[key] = []
                    stack.pop()
                    parent = grandparent
                else:
                    key = last_key_by_indent.get(stack[-1][0])
                    existing = parent.setdefault(key, []) if key else None
            else:
                key = last_key_by_indent.get(stack[-1][0])
                existing = parent.setdefault(key, []) if key else None
            if key and isinstance(existing, list):
                existing.append(clean_scalar(line[2:]))
            continue
        key, separator, value = line.partition(":")
        if not separator:
            continue
        clean_key = key.strip()
        if value.strip():
            parent[clean_key] = parse_scalar(value.strip())
            last_key_by_indent[indent] = clean_key
            continue
        child: dict[str, Any] = {}
        parent[clean_key] = child
        last_key_by_indent[indent] = clean_key
        stack.append((indent, child))
    return result


def parse_scalar(value: str) -> Any:
    if not value:
        return ""
    lowered = value.casefold()
    if lowered in {"true", "false"}:
        return lowered == "true"
    if value.startswith("[") and value.endswith("]"):
        return [clean_scalar(item) for item in value[1:-1].split(",") if item.strip()]
    return clean_scalar(value)


def clean_scalar(value: str) -> str:
    return value.strip().strip("\"'")


def frontmatter_get(frontmatter: dict[str, Any], key: str) -> Any:
    value = frontmatter.get(key)
    return value if value is not None else ""


def matches_platform(frontmatter: dict[str, Any]) -> bool:
    platforms = as_string_list(frontmatter.get("platforms"))
    if not platforms:
        return True
    current = sys.platform
    for item in platforms:
        prefix = PLATFORM_MAP.get(item.casefold(), item.casefold())
        if current.startswith(prefix):
            return True
    return False


def as_string_list(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [item.strip() for item in str(value).strip("[]").split(",") if item.strip()]


def metadata_string_list(frontmatter: dict[str, Any], key: str) -> list[str]:
    return as_string_list(frontmatter.get(key))
