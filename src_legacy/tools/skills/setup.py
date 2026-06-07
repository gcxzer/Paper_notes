from __future__ import annotations

import re
from typing import Any

from tools.skills.frontmatter import as_string_list


def required_environment_variables(frontmatter: dict[str, Any]) -> list[dict[str, Any]]:
    required_raw = frontmatter.get("required_environment_variables")
    setup = frontmatter.get("setup") if isinstance(frontmatter.get("setup"), dict) else {}
    collect_secrets = setup.get("collect_secrets") if isinstance(setup, dict) else []
    prereqs = frontmatter.get("prerequisites") if isinstance(frontmatter.get("prerequisites"), dict) else {}
    entries: list[Any] = []
    if isinstance(required_raw, list):
        entries.extend(required_raw)
    elif required_raw:
        entries.append(required_raw)
    if isinstance(collect_secrets, dict):
        entries.append(collect_secrets)
    elif isinstance(collect_secrets, list):
        entries.extend(collect_secrets)
    env_vars = prereqs.get("env_vars") if isinstance(prereqs, dict) else []
    entries.extend(as_string_list(env_vars))

    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in entries:
        normalized = normalize_required_environment_entry(entry, setup if isinstance(setup, dict) else {})
        if not normalized or normalized["name"] in seen:
            continue
        seen.add(normalized["name"])
        result.append(normalized)
    return result


def normalize_required_environment_entry(entry: Any, setup: dict[str, Any]) -> dict[str, Any] | None:
    if isinstance(entry, str):
        name = entry.strip()
        source: dict[str, Any] = {}
    elif isinstance(entry, dict):
        name = str(entry.get("name") or entry.get("env_var") or "").strip()
        source = entry
    else:
        return None
    if not name or not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", name):
        return None
    normalized: dict[str, Any] = {
        "name": name,
        "prompt": str(source.get("prompt") or f"Enter value for {name}").strip(),
    }
    help_text = source.get("help") or source.get("provider_url") or source.get("url") or setup.get("help")
    if isinstance(help_text, str) and help_text.strip():
        normalized["help"] = help_text.strip()
    required_for = source.get("required_for")
    if isinstance(required_for, str) and required_for.strip():
        normalized["required_for"] = required_for.strip()
    if source.get("optional"):
        normalized["optional"] = True
    return normalized


def required_commands(frontmatter: dict[str, Any]) -> list[str]:
    prereqs = frontmatter.get("prerequisites") if isinstance(frontmatter.get("prerequisites"), dict) else {}
    return as_string_list(prereqs.get("commands") if isinstance(prereqs, dict) else [])


def setup_help(frontmatter: dict[str, Any], required_env: list[dict[str, Any]]) -> str:
    setup = frontmatter.get("setup") if isinstance(frontmatter.get("setup"), dict) else {}
    help_text = setup.get("help") if isinstance(setup, dict) else ""
    if isinstance(help_text, str) and help_text.strip():
        return help_text.strip()
    for entry in required_env:
        value = entry.get("help")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""
