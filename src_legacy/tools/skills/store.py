from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from tools.skills.constants import (
    INJECTION_PATTERNS,
    MAX_DESCRIPTION_LENGTH,
    MAX_NAME_LENGTH,
    PAPER_NOTES_SKILLS_DIR,
    REPO_SKILLS_DIR,
)
from tools.skills.files import linked_files, read_supporting_file, read_text
from tools.skills.frontmatter import frontmatter_get, matches_platform, metadata_string_list, parse_frontmatter
from tools.skills.settings import default_skill_roots, disabled_skill_names, normalize_disabled_skills
from tools.skills.setup import required_commands, required_environment_variables, setup_help


class SkillStore:
    def __init__(
        self,
        roots: list[str | Path] | tuple[str | Path, ...] | None = None,
        *,
        disabled_skills: list[str] | tuple[str, ...] | set[str] | None = None,
        settings_path: str | Path | None = None,
    ) -> None:
        if roots is None:
            roots = default_skill_roots(settings_path)
            if disabled_skills is None:
                disabled_skills = disabled_skill_names(settings_path)
        elif disabled_skills is None and settings_path is not None:
            disabled_skills = disabled_skill_names(settings_path)
        self.roots = tuple(_normalize_root(root) for root in roots)
        self.disabled_skills = frozenset(normalize_disabled_skills(list(disabled_skills or [])))

    def ensure_user_dir(self) -> None:
        if PAPER_NOTES_SKILLS_DIR.resolve() in self.roots:
            PAPER_NOTES_SKILLS_DIR.mkdir(parents=True, exist_ok=True)

    def list(
        self,
        *,
        category: str = "",
        include_disabled: bool = False,
        include_enabled_state: bool = False,
    ) -> dict[str, Any]:
        self.ensure_user_dir()
        skills = _sort_skills(list(self._iter_skill_records()))
        if not include_disabled:
            skills = [skill for skill in skills if self._skill_enabled(skill["name"])]
        if category:
            skills = [skill for skill in skills if skill.get("category") == category]
        categories = sorted({str(skill.get("category")) for skill in skills if skill.get("category")})
        payload = {
            "success": True,
            "skills": [
                self._skill_list_item(skill, include_enabled_state=include_enabled_state)
                for skill in skills
            ],
            "categories": categories,
            "count": len(skills),
            "hint": "Use skill_view(name) to load full SKILL.md content and linked files.",
        }
        if not skills:
            payload["message"] = (
                "No skills found in skills/ directory."
                if any(root.exists() for root in self.roots)
                else f"No skills found. Skills directory created at {PAPER_NOTES_SKILLS_DIR}/"
            )
        return payload

    def view(
        self,
        *,
        name: str,
        file_path: str = "",
        include_disabled: bool = False,
        include_enabled_state: bool = False,
    ) -> dict[str, Any]:
        self.ensure_user_dir()
        normalized_name = str(name or "").strip()
        if not normalized_name:
            return {"success": False, "error": "Skill name is required."}

        record = self._find_skill(normalized_name)
        if record is None:
            available_records = _sort_skills(list(self._iter_skill_records()))
            if not include_disabled:
                available_records = [skill for skill in available_records if self._skill_enabled(skill["name"])]
            available = [skill["name"] for skill in available_records[:20]]
            return {
                "success": False,
                "error": f"Skill '{normalized_name}' not found.",
                "available_skills": available,
                "hint": "Use skills_list to see all available skills.",
            }
        enabled = self._skill_enabled(record["name"])
        if not enabled and not include_disabled:
            return {
                "success": False,
                "code": "skill_disabled",
                "error": f"Skill '{record['name']}' is disabled.",
                "hint": "Enable this skill in Settings > Skills before using it.",
            }

        skill_dir = record["skill_dir"]
        if file_path:
            payload = read_supporting_file(record, file_path)
            if include_enabled_state:
                payload["enabled"] = enabled
            return payload

        skill_md = record["skill_md"]
        content = read_text(skill_md)
        frontmatter, _ = parse_frontmatter(content)
        if not matches_platform(frontmatter):
            payload = {
                "success": False,
                "error": f"Skill '{normalized_name}' is not supported on this platform.",
                "readiness_status": "unsupported",
            }
            if include_enabled_state:
                payload["enabled"] = enabled
            return payload
        linked = linked_files(skill_dir)
        required_env = required_environment_variables(frontmatter)
        missing_env = [entry["name"] for entry in required_env if not entry.get("optional") and not os.getenv(entry["name"])]
        result: dict[str, Any] = {
            "success": True,
            "name": record["name"],
            "description": record["description"],
            "tags": metadata_string_list(frontmatter, "tags"),
            "related_skills": metadata_string_list(frontmatter, "related_skills"),
            "content": content,
            "path": record["path"],
            "skill_dir": str(skill_dir) if skill_dir else None,
            "source": record["source"],
            "linked_files": linked or None,
            "usage_hint": (
                "To view linked files, call skill_view(name, file_path) where file_path is e.g. "
                "'references/api.md' or 'assets/config.yaml'"
            )
            if linked
            else None,
            "required_environment_variables": required_env,
            "required_commands": required_commands(frontmatter),
            "missing_required_environment_variables": missing_env,
            "missing_required_commands": [],
            "setup_needed": bool(missing_env),
            "setup_skipped": False,
            "readiness_status": "setup_needed" if missing_env else "available",
        }
        if include_enabled_state:
            result["enabled"] = enabled
        help_text = setup_help(frontmatter, required_env)
        if help_text:
            result["setup_help"] = help_text
        if missing_env:
            result["setup_note"] = f"Setup needed before using this skill: missing {', '.join(missing_env)}."
        compatibility = frontmatter_get(frontmatter, "compatibility")
        if compatibility:
            result["compatibility"] = compatibility
        metadata = frontmatter.get("metadata")
        if isinstance(metadata, dict):
            result["metadata"] = metadata
        if any(pattern in content.casefold() for pattern in INJECTION_PATTERNS):
            result["security_warning"] = "Skill content contains patterns that may indicate prompt injection."
        return result

    def find_record(self, name: str) -> dict[str, Any] | None:
        normalized_name = str(name or "").strip()
        if not normalized_name:
            return None
        return self._find_skill(normalized_name)

    def _iter_skill_records(self):
        seen: set[str] = set()
        for root in self.roots:
            if not root.exists():
                continue
            for skill_md in sorted(root.rglob("SKILL.md")):
                if any(part in {".git", ".github", ".archive", "__pycache__"} for part in skill_md.parts):
                    continue
                record = _skill_record(root, skill_md)
                if record is None:
                    continue
                if record["name"] in seen:
                    continue
                seen.add(record["name"])
                yield record

    def _find_skill(self, name: str) -> dict[str, Any] | None:
        normalized = name.replace(":", "/").strip("/")
        for root in self.roots:
            if not root.exists():
                continue
            direct = root / normalized
            if direct.is_dir() and (direct / "SKILL.md").exists():
                record = _skill_record(root, direct / "SKILL.md", filter_platform=False)
                if record is not None:
                    return record
            legacy = direct.with_suffix(".md")
            if legacy.exists() and legacy.name != "SKILL.md":
                record = _skill_record(root, legacy, filter_platform=False)
                if record is not None:
                    return record
        for record in self._iter_skill_records():
            skill_dir_name = record["skill_dir"].name if record["skill_dir"] is not None else ""
            if record["name"] == name or skill_dir_name == name or _record_path_stem(record["path"]) == normalized:
                return record
        for root in self.roots:
            if not root.exists():
                continue
            for skill_md in sorted(root.rglob("SKILL.md")):
                record = _skill_record(root, skill_md, filter_platform=False)
                if record is None:
                    continue
                skill_dir_name = record["skill_dir"].name if record["skill_dir"] is not None else ""
                if skill_dir_name == name:
                    return record
            for legacy in sorted(root.rglob(f"{name}.md")):
                if legacy.name == "SKILL.md":
                    continue
                record = _skill_record(root, legacy, filter_platform=False)
                if record is not None:
                    return record
        return None

    def _skill_enabled(self, name: str) -> bool:
        return str(name or "").strip() not in self.disabled_skills

    def _skill_list_item(self, skill: dict[str, Any], *, include_enabled_state: bool) -> dict[str, Any]:
        item = {
            "name": skill["name"],
            "description": skill["description"],
            "category": skill.get("category"),
            "path": skill["path"],
            "source": skill["source"],
        }
        if include_enabled_state:
            item["enabled"] = self._skill_enabled(skill["name"])
        return item


def _normalize_root(root: str | Path) -> Path:
    return Path(root).expanduser().resolve()


def _skill_record(root: Path, skill_md: Path, *, filter_platform: bool = True) -> dict[str, Any] | None:
    try:
        content = read_text(skill_md, max_chars=8000)
    except OSError:
        return None
    frontmatter, body = parse_frontmatter(content)
    if filter_platform and not matches_platform(frontmatter):
        return None
    skill_dir = skill_md.parent if skill_md.name == "SKILL.md" else None
    name = str(frontmatter_get(frontmatter, "name") or (skill_dir.name if skill_dir else skill_md.stem)).strip()[:MAX_NAME_LENGTH]
    if not name:
        return None
    description = str(frontmatter_get(frontmatter, "description") or _first_body_line(body)).strip()
    if len(description) > MAX_DESCRIPTION_LENGTH:
        description = f"{description[:MAX_DESCRIPTION_LENGTH - 3]}..."
    return {
        "name": name,
        "description": description,
        "category": _category_from_path(skill_md, root),
        "path": _relative_path(skill_md, root),
        "source": _source_for_root(root),
        "skill_dir": skill_dir,
        "skill_md": skill_md,
    }


def _first_body_line(body: str) -> str:
    for line in body.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            return stripped
    return ""


def _sort_skills(skills: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(skills, key=lambda skill: (str(skill.get("category") or ""), str(skill.get("name") or "")))


def _source_for_root(root: Path) -> str:
    if root == PAPER_NOTES_SKILLS_DIR.resolve():
        return "user"
    if root == REPO_SKILLS_DIR.resolve():
        return "bundled"
    return "external"


def _category_from_path(skill_md: Path, root: Path) -> str | None:
    try:
        relative = skill_md.relative_to(root)
    except ValueError:
        return None
    return relative.parts[0] if len(relative.parts) >= 3 else None


def _relative_path(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _record_path_stem(path: str) -> str:
    if path.endswith("/SKILL.md"):
        return path.removesuffix("/SKILL.md")
    if path.endswith(".md"):
        return path.removesuffix(".md")
    return path
