"""说明：提供 skills 文件读写和路径安全工具。

作用：确保查看、创建和更新 skill 文件时只能访问允许的目录。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tools.skills.constants import OTHER_SUPPORT_SUFFIXES, SCRIPT_SUFFIXES, TEXT_FILE_SUFFIXES, TRUSTED_SUPPORT_DIRS


def linked_files(skill_dir: Path | None) -> dict[str, list[str]]:
    if skill_dir is None:
        return {}
    linked: dict[str, list[str]] = {}
    for dirname in TRUSTED_SUPPORT_DIRS:
        directory = skill_dir / dirname
        if not directory.exists():
            continue
        files: list[str] = []
        for path in sorted(directory.rglob("*")):
            if not path.is_file() or path.is_symlink():
                continue
            if dirname == "references" and path.suffix.lower() != ".md":
                continue
            if dirname == "templates" and path.suffix.lower() not in OTHER_SUPPORT_SUFFIXES:
                continue
            if dirname == "scripts" and path.suffix.lower() not in SCRIPT_SUFFIXES:
                continue
            files.append(str(path.relative_to(skill_dir)))
        if files:
            linked[dirname] = files
    return linked


def read_supporting_file(record: dict[str, Any], file_path: str) -> dict[str, Any]:
    skill_dir = record["skill_dir"]
    if skill_dir is None:
        return {
            "success": False,
            "error": f"Skill '{record['name']}' does not have a skill directory with linked files.",
            "hint": "Use file_path only with directory-based skills.",
        }
    if has_traversal(file_path):
        return {
            "success": False,
            "error": "Path traversal ('..') is not allowed.",
            "hint": "Use a relative path within the skill directory.",
        }
    target = (skill_dir / file_path).resolve()
    try:
        target.relative_to(skill_dir.resolve())
    except ValueError:
        return {
            "success": False,
            "error": "Requested file must stay within the skill directory.",
            "hint": "Use a relative path within the skill directory.",
        }
    if not target.exists() or not target.is_file():
        return {
            "success": False,
            "error": f"File '{file_path}' not found in skill '{record['name']}'.",
            "available_files": available_files(skill_dir),
            "hint": "Use one of the available file paths listed above",
        }
    if target.suffix.lower() not in TEXT_FILE_SUFFIXES:
        return {
            "success": True,
            "name": record["name"],
            "file": file_path,
            "content": f"[Binary or unsupported file: {target.name}, size: {target.stat().st_size} bytes]",
            "is_binary": True,
        }
    return {
        "success": True,
        "name": record["name"],
        "file": file_path,
        "content": read_text(target),
        "file_type": target.suffix,
    }


def has_traversal(file_path: str) -> bool:
    return any(part == ".." for part in Path(file_path).parts)


def read_text(path: Path, *, max_chars: int | None = None) -> str:
    text = path.read_text(encoding="utf-8-sig")
    return text[:max_chars] if max_chars is not None else text


def available_files(skill_dir: Path) -> dict[str, list[str]]:
    available: dict[str, list[str]] = {
        "references": [],
        "templates": [],
        "assets": [],
        "scripts": [],
        "other": [],
    }
    for path in sorted(skill_dir.rglob("*")):
        if not path.is_file() or path.name == "SKILL.md" or path.is_symlink():
            continue
        rel = str(path.relative_to(skill_dir))
        if rel.startswith("references/"):
            available["references"].append(rel)
        elif rel.startswith("templates/"):
            available["templates"].append(rel)
        elif rel.startswith("assets/"):
            available["assets"].append(rel)
        elif rel.startswith("scripts/"):
            available["scripts"].append(rel)
        elif path.suffix.lower() in OTHER_SUPPORT_SUFFIXES:
            available["other"].append(rel)
    return {key: value for key, value in available.items() if value}
