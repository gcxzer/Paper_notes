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
    assert any(skill["name"] == "test-skill" for skill in listed["skills"])
    assert viewed["success"] is True
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
    assert 'description: "New description: keep this."' in text
    assert "tags: [edit]" in text
    assert "# Updated" in text
    assert "Old body." not in text
