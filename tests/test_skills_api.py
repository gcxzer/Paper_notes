from __future__ import annotations

import pytest

from ui.backend.skills_api import list_skills, update_skill, update_skill_settings, view_skill


@pytest.fixture()
def skills_root(tmp_path, monkeypatch):
    root = tmp_path / "skills"
    monkeypatch.setenv("PAPER_NOTES_SKILLS_PATHS", str(root))
    return root


def test_skills_api_lists_and_views_local_skills(skills_root):
    skill_dir = skills_root / "test-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: test-skill\ndescription: Test skill.\n---\n\nUse the test workflow.",
        encoding="utf-8",
    )

    listed = list_skills()
    viewed = view_skill("test-skill")

    assert listed["success"] is True
    assert any(skill["name"] == "test-skill" and skill["enabled"] is True for skill in listed["skills"])
    assert viewed["success"] is True
    assert viewed["enabled"] is True
    assert "Use the test workflow." in viewed["content"]


def test_skills_api_rejects_missing_view_name(skills_root):
    skills_root.mkdir(parents=True)

    with pytest.raises(ValueError, match="Skill name is required"):
        view_skill("")


def test_skills_api_updates_external_directories(tmp_path, monkeypatch):
    monkeypatch.delenv("PAPER_NOTES_SKILLS_PATHS", raising=False)
    external_root = tmp_path / "external-skills"
    skill_dir = external_root / "external-demo"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: external-demo\ndescription: External demo.\n---\n\nUse outside skills.",
        encoding="utf-8",
    )
    settings_path = tmp_path / "skill-settings.json"

    settings = update_skill_settings(
        {"externalDirectories": [str(external_root)]},
        settings_path=settings_path,
    )
    listed = list_skills(settings_path=settings_path)
    viewed = view_skill("external-demo", settings_path=settings_path)

    assert settings["externalDirectories"] == [{"path": str(external_root), "exists": True}]
    assert any(skill["name"] == "external-demo" and skill["source"] == "external" for skill in listed["skills"])
    assert viewed["success"] is True
    assert "Use outside skills." in viewed["content"]


def test_skills_api_saves_disabled_skills_and_preserves_settings(tmp_path, monkeypatch):
    monkeypatch.delenv("PAPER_NOTES_SKILLS_PATHS", raising=False)
    external_root = tmp_path / "external-skills"
    external_root.mkdir()
    settings_path = tmp_path / "skill-settings.json"

    settings = update_skill_settings(
        {"externalDirectories": [str(external_root)], "disabled_skills": ["alpha", "alpha", " "]},
        settings_path=settings_path,
    )
    assert settings["externalDirectories"] == [{"path": str(external_root), "exists": True}]
    assert settings["disabledSkills"] == ["alpha"]

    external_only = update_skill_settings({"externalDirectories": [str(external_root)]}, settings_path=settings_path)
    assert external_only["disabledSkills"] == ["alpha"]

    disabled_only = update_skill_settings({"disabledSkills": ["beta"]}, settings_path=settings_path)
    assert disabled_only["externalDirectories"] == [{"path": str(external_root), "exists": True}]
    assert disabled_only["disabledSkills"] == ["beta"]


def test_skills_api_keeps_disabled_skills_visible_for_settings(skills_root, tmp_path):
    skill_dir = skills_root / "off-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: off-skill\ndescription: Disabled test skill.\n---\n\nDisabled body.",
        encoding="utf-8",
    )
    settings_path = tmp_path / "skill-settings.json"
    update_skill_settings({"disabledSkills": ["off-skill"]}, settings_path=settings_path)

    listed = list_skills(settings_path=settings_path)
    viewed = view_skill("off-skill", settings_path=settings_path)

    listed_skill = next(skill for skill in listed["skills"] if skill["name"] == "off-skill")
    assert listed_skill["enabled"] is False
    assert viewed["success"] is True
    assert viewed["enabled"] is False
    assert "Disabled body." in viewed["content"]


def test_skills_api_updates_skill_description_and_content(skills_root):
    skill_dir = skills_root / "editable-skill"
    skill_dir.mkdir(parents=True)
    skill_md = skill_dir / "SKILL.md"
    skill_md.write_text(
        "---\nname: editable-skill\ndescription: Old description.\ntags: [edit]\n---\n\nOld body.",
        encoding="utf-8",
    )

    updated = update_skill(
        {
            "name": "editable-skill",
            "description": "New description: keep this.",
            "content": "# Updated\n\nUse the new workflow.",
        }
    )
    text = skill_md.read_text(encoding="utf-8")

    assert updated["success"] is True
    assert updated["description"] == "New description: keep this."
    assert "description: 'New description: keep this.'" in text
    assert "tags: [edit]" in text
    assert "# Updated" in text
    assert "Old body." not in text


def test_skills_api_keeps_plain_frontmatter_scalars_unquoted(skills_root):
    skill_dir = skills_root / "plain-skill"
    skill_dir.mkdir(parents=True)
    skill_md = skill_dir / "SKILL.md"
    skill_md.write_text(
        "---\nname: plain-skill\ndescription: Old plain description.\ntags: [edit]\n---\n\nOld body.",
        encoding="utf-8",
    )

    update_skill({
        "name": "plain-skill",
        "description": "Clear trigger description for plain skills.",
        "content": "# Plain\n\nUse the plain workflow.",
    })
    text = skill_md.read_text(encoding="utf-8")

    assert "name: plain-skill" in text
    assert "description: Clear trigger description for plain skills." in text
    assert '"plain-skill"' not in text
    assert '"Clear trigger description for plain skills."' not in text
