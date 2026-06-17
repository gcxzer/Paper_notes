"""说明：创建 agent 可调用的 skills 工具。

作用：提供 skills_list 和 skill_view 等工具，让模型能查看可用技能说明。
"""

from __future__ import annotations

from typing import Any

from langchain_core.tools import StructuredTool

from tools.skills.store import SkillStore

__all__ = [
    "SkillStore",
    "create_tools",
]

def create_tools(*, store: SkillStore | None = None) -> list[StructuredTool]:
    skill_store = store or SkillStore()
    return [
        create_skills_list_tool(skill_store),
        create_skill_view_tool(skill_store),
    ]


def create_skills_list_tool(store: SkillStore) -> StructuredTool:
    return StructuredTool(
        name="skills_list",
        description=(
            "List local agent skills with compact metadata. Use this first when the user asks for a specialized "
            "workflow or mentions skills; call skill_view only for the skill you need."
        ),
        args_schema={
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
        func=lambda **kwargs: skills_list(dict(kwargs), store=store),
        metadata={"mode": "progressive_disclosure", "tier": "metadata"},
    )


def create_skill_view_tool(store: SkillStore) -> StructuredTool:
    return StructuredTool(
        name="skill_view",
        description=(
            "Load a skill's full SKILL.md instructions or a linked supporting file. The first call returns "
            "linked_files for references, templates, scripts, and assets; call again with file_path to load one."
        ),
        args_schema={
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
        func=lambda **kwargs: skill_view(dict(kwargs), store=store),
        metadata={"mode": "progressive_disclosure", "tier": "instructions"},
    )


def skills_list(args: dict[str, Any], *, store: SkillStore | None = None) -> dict[str, Any]:
    return (store or SkillStore()).list(category=str(args.get("category") or "").strip())


def skill_view(args: dict[str, Any], *, store: SkillStore | None = None) -> dict[str, Any]:
    return (store or SkillStore()).view(
        name=str(args.get("name") or "").strip(),
        file_path=str(args.get("file_path") or "").strip(),
    )
