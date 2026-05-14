from __future__ import annotations

import json

from tools.registry import ToolRegistry
from tools.skills import SkillStore, register_skills_tools


def test_skills_list_empty_root_returns_message(tmp_path):
    store = SkillStore([tmp_path / "skills"])

    listed = store.list()

    assert listed["success"] is True
    assert listed["skills"] == []
    assert listed["categories"] == []
    assert listed["count"] == 0
    assert listed["message"]


def test_skills_list_and_view_use_progressive_disclosure(tmp_path):
    flat_dir = tmp_path / "skills" / "flat-skill"
    flat_dir.mkdir(parents=True)
    (flat_dir / "SKILL.md").write_text(
        "---\nname: flat-skill\ndescription: Flat test skill.\n---\n\nFlat body.",
        encoding="utf-8",
    )
    skill_dir = tmp_path / "skills" / "research" / "paper-skim"
    (skill_dir / "references").mkdir(parents=True)
    (skill_dir / "scripts").mkdir()
    (skill_dir / "templates").mkdir()
    (skill_dir / "assets").mkdir()
    (skill_dir / "SKILL.md").write_text(
        """---
name: paper-skim
description: Skim a paper and extract claims.
tags: [papers, reading]
related_skills: [flat-skill]
required_environment_variables:
  - PAPER_NOTES_TEST_KEY
prerequisites:
  commands: [echo]
---

# Paper Skim

Use the current Paper Notes context to identify the paper's contribution.
""",
        encoding="utf-8",
    )
    (skill_dir / "references" / "rubric.md").write_text("Prefer concrete evidence.", encoding="utf-8")
    (skill_dir / "templates" / "outline.yaml").write_text("sections: []\n", encoding="utf-8")
    (skill_dir / "scripts" / "score.py").write_text("print('ok')\n", encoding="utf-8")
    (skill_dir / "assets" / "sample.bin").write_bytes(b"\x00\x01")
    store = SkillStore([tmp_path / "skills"])

    listed = store.list()
    filtered = store.list(category="research")
    viewed = store.view(name="paper-skim")
    slash_viewed = store.view(name="research/paper-skim")
    colon_viewed = store.view(name="research:paper-skim")
    reference = store.view(name="paper-skim", file_path="references/rubric.md")
    template = store.view(name="paper-skim", file_path="templates/outline.yaml")
    binary = store.view(name="paper-skim", file_path="assets/sample.bin")

    assert listed["count"] == 2
    assert listed["categories"] == ["research"]
    assert [skill["name"] for skill in listed["skills"]] == ["flat-skill", "paper-skim"]
    assert filtered["count"] == 1
    assert filtered["skills"][0] == {
        "name": "paper-skim",
        "description": "Skim a paper and extract claims.",
        "category": "research",
        "path": "research/paper-skim/SKILL.md",
        "source": "external",
    }
    assert viewed["success"] is True
    assert viewed["tags"] == ["papers", "reading"]
    assert viewed["related_skills"] == ["flat-skill"]
    assert viewed["linked_files"] == {
        "references": ["references/rubric.md"],
        "templates": ["templates/outline.yaml"],
        "assets": ["assets/sample.bin"],
        "scripts": ["scripts/score.py"],
    }
    assert viewed["required_environment_variables"][0]["name"] == "PAPER_NOTES_TEST_KEY"
    assert viewed["missing_required_environment_variables"] == ["PAPER_NOTES_TEST_KEY"]
    assert viewed["required_commands"] == ["echo"]
    assert viewed["missing_required_commands"] == []
    assert viewed["setup_needed"] is True
    assert viewed["setup_skipped"] is False
    assert viewed["readiness_status"] == "setup_needed"
    assert slash_viewed["name"] == "paper-skim"
    assert colon_viewed["name"] == "paper-skim"
    assert "Use the current Paper Notes context" in viewed["content"]
    assert reference["content"] == "Prefer concrete evidence."
    assert template["content"] == "sections: []\n"
    assert binary["is_binary"] is True


def test_skill_view_supports_top_level_tags_legacy_markdown_and_missing_files(tmp_path):
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    (skills_dir / "legacy.md").write_text(
        "---\nname: legacy\ndescription: Legacy markdown skill.\ntags: [legacy, test]\nrelated_skills: [paper-skim]\n---\n\nLegacy body.",
        encoding="utf-8",
    )
    skill_dir = skills_dir / "paper-skim"
    (skill_dir / "references").mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: paper-skim\n---\n\nBody.", encoding="utf-8")
    (skill_dir / "references" / "rubric.md").write_text("Rubric", encoding="utf-8")
    store = SkillStore([skills_dir])

    legacy = store.view(name="legacy")
    missing = store.view(name="paper-skim", file_path="references/missing.md")

    assert legacy["success"] is True
    assert legacy["path"] == "legacy.md"
    assert legacy["skill_dir"] is None
    assert legacy["tags"] == ["legacy", "test"]
    assert legacy["related_skills"] == ["paper-skim"]
    assert missing["success"] is False
    assert missing["available_files"] == {"references": ["references/rubric.md"]}
    assert missing["hint"] == "Use one of the available file paths listed above"


def test_skill_view_reports_unsupported_platform_for_direct_load(tmp_path):
    skill_dir = tmp_path / "skills" / "windows-only"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: windows-only\nplatforms: [windows]\n---\n\nOnly on Windows.",
        encoding="utf-8",
    )
    store = SkillStore([tmp_path / "skills"])

    listed = store.list()
    viewed = store.view(name="windows-only")

    assert listed["skills"] == []
    assert viewed["success"] is False
    assert viewed["readiness_status"] == "unsupported"


def test_skill_view_blocks_path_traversal(tmp_path):
    skill_dir = tmp_path / "skills" / "safe"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: safe\n---\n\nDo safe work.", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("nope", encoding="utf-8")
    store = SkillStore([tmp_path / "skills"])

    result = store.view(name="safe", file_path="../secret.txt")

    assert result["success"] is False
    assert "Path traversal" in result["error"]


def test_skills_tools_register_and_dispatch(tmp_path):
    skill_dir = tmp_path / "skills" / "writer"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: writer\ndescription: Draft notes.\n---\n\nWrite clearly.",
        encoding="utf-8",
    )
    registry = ToolRegistry()
    register_skills_tools(registry, store=SkillStore([tmp_path / "skills"]))

    listed = json.loads(registry.dispatch("skills_list", {}).content)
    viewed = json.loads(registry.dispatch("skill_view", {"name": "writer"}).content)

    assert registry.tool_names_for_toolset("skills") == ["skill_view", "skills_list"]
    assert listed["skills"][0]["name"] == "writer"
    assert viewed["content"].endswith("Write clearly.")
