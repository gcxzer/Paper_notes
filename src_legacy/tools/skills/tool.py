"""Local agent skills tool definitions.

Inspired by Hermes Agent `tools/skills_tool.py` (MIT License). The scanning,
frontmatter parsing, setup metadata, and linked-file handling live in focused
helpers so this module stays as the registry-facing entrypoint.
"""

from __future__ import annotations

from typing import Any

from tools.registry import ToolDefinition, ToolRegistry
from tools.skills.constants import PAPER_NOTES_SKILLS_DIR, REPO_SKILLS_DIR, SKILLS_TOOLSET
from tools.skills.manifest import TOOL_GROUP
from tools.skills.store import SkillStore


def register_skills_tools(registry: ToolRegistry, *, store: SkillStore | None = None) -> None:
    registry.register_group(TOOL_GROUP)
    skill_store = store or SkillStore()
    if registry.get("skills_list") is None:
        registry.register(create_skills_list_tool_definition(skill_store))
    if registry.get("skill_view") is None:
        registry.register(create_skill_view_tool_definition(skill_store))


def create_skills_list_tool_definition(store: SkillStore) -> ToolDefinition:
    return ToolDefinition(
        name="skills_list",
        description=(
            "List local agent skills with compact metadata. Use this first when the user asks for a specialized "
            "workflow or mentions skills; call skill_view only for the skill you need."
        ),
        parameters={
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "description": "Optional category filter, for skills stored as category/name/SKILL.md.",
                },
            },
            "required": [],
            "additionalProperties": False,
        },
        handler=lambda args: skills_list(args, store=store),
        toolset=SKILLS_TOOLSET,
        read_only=True,
        risk="read",
        kind="read",
        result_max_chars=12_000,
        metadata={"mode": "progressive_disclosure", "tier": "metadata"},
    )


def create_skill_view_tool_definition(store: SkillStore) -> ToolDefinition:
    return ToolDefinition(
        name="skill_view",
        description=(
            "Load a skill's full SKILL.md instructions or a linked supporting file. The first call returns "
            "linked_files for references, templates, scripts, and assets; call again with file_path to load one."
        ),
        parameters={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Skill name from skills_list, or category/name.",
                },
                "file_path": {
                    "type": "string",
                    "description": "Optional relative path inside the skill, such as references/api.md or scripts/check.py.",
                },
            },
            "required": ["name"],
            "additionalProperties": False,
        },
        handler=lambda args: skill_view(args, store=store),
        toolset=SKILLS_TOOLSET,
        read_only=True,
        risk="read",
        kind="read",
        result_max_chars=24_000,
        metadata={"mode": "progressive_disclosure", "tier": "instructions"},
    )


def skills_list(args: dict[str, Any], *, store: SkillStore | None = None) -> dict[str, Any]:
    return (store or SkillStore()).list(category=str(args.get("category") or "").strip())


def skill_view(args: dict[str, Any], *, store: SkillStore | None = None) -> dict[str, Any]:
    return (store or SkillStore()).view(
        name=str(args.get("name") or "").strip(),
        file_path=str(args.get("file_path") or "").strip(),
    )


__all__ = [
    "PAPER_NOTES_SKILLS_DIR",
    "REPO_SKILLS_DIR",
    "SKILLS_TOOLSET",
    "SkillStore",
    "create_skill_view_tool_definition",
    "create_skills_list_tool_definition",
    "register_skills_tools",
    "skill_view",
    "skills_list",
]
