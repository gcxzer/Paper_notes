from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from tools.skills.constants import PAPER_NOTES_SKILLS_DIR, REPO_SKILLS_DIR


DEFAULT_SKILL_SETTINGS_PATH = PAPER_NOTES_SKILLS_DIR.parent / "skill-settings.json"


def skill_settings_path(settings_path: str | Path | None = None) -> Path:
    return Path(settings_path).expanduser() if settings_path is not None else DEFAULT_SKILL_SETTINGS_PATH


def read_skill_settings(settings_path: str | Path | None = None) -> dict[str, Any]:
    path = skill_settings_path(settings_path)
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def external_skill_roots(settings_path: str | Path | None = None) -> tuple[Path, ...]:
    settings = read_skill_settings(settings_path)
    roots = _paths_from_value(settings.get("externalDirectories", settings.get("external_directories")))
    return tuple(_dedupe_paths(roots))


def environment_skill_roots() -> tuple[Path, ...]:
    override = os.environ.get("PAPER_NOTES_SKILLS_PATHS", "").strip()
    if not override:
        return ()
    return tuple(_dedupe_paths(Path(part).expanduser() for part in override.split(os.pathsep) if part.strip()))


def default_skill_roots(settings_path: str | Path | None = None) -> tuple[Path, ...]:
    return tuple(_dedupe_paths([
        PAPER_NOTES_SKILLS_DIR,
        REPO_SKILLS_DIR,
        *external_skill_roots(settings_path),
        *environment_skill_roots(),
    ]))


def normalize_external_directories(value: Any) -> list[str]:
    roots = _paths_from_value(value)
    return [str(path) for path in _dedupe_paths(roots)]


def _paths_from_value(value: Any) -> list[Path]:
    if not isinstance(value, list):
        return []
    paths: list[Path] = []
    for item in value:
        text = str(item or "").strip() if isinstance(item, str) else ""
        if not text or "\x00" in text:
            continue
        paths.append(Path(text).expanduser())
    return paths


def _dedupe_paths(paths: Any) -> list[Path]:
    deduped: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        try:
            normalized = Path(path).expanduser().resolve()
        except OSError:
            normalized = Path(path).expanduser().absolute()
        key = str(normalized)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(normalized)
    return deduped
