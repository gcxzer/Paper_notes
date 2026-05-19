from __future__ import annotations

import json

import pytest

from backend.agent_api import AgentAPIError
from backend.chat_projects_api import create_chat_project, delete_chat_project, list_chat_projects, rename_chat_project


def test_create_chat_project_persists_custom_project(tmp_path):
    path = tmp_path / "chat-projects.json"

    created = create_chat_project({"name": "Literature Review"}, path=path)
    listed = list_chat_projects(path=path)

    assert created["project"]["id"].startswith("project-")
    assert created["project"]["name"] == "Literature Review"
    assert listed["projects"] == created["projects"]
    assert json.loads(path.read_text(encoding="utf-8"))["projects"][0]["name"] == "Literature Review"


def test_create_chat_project_requires_name(tmp_path):
    with pytest.raises(AgentAPIError) as error:
        create_chat_project({"name": "   "}, path=tmp_path / "chat-projects.json")

    assert error.value.code == "project_name_required"


def test_rename_chat_project_updates_existing_project(tmp_path):
    path = tmp_path / "chat-projects.json"
    created = create_chat_project({"name": "Old name"}, path=path)["project"]

    renamed = rename_chat_project({"projectId": created["id"], "name": "New name"}, path=path)

    assert renamed["project"]["id"] == created["id"]
    assert renamed["project"]["name"] == "New name"
    assert list_chat_projects(path=path)["projects"][0]["name"] == "New name"


def test_delete_chat_project_removes_existing_project(tmp_path):
    path = tmp_path / "chat-projects.json"
    created = create_chat_project({"name": "Delete me"}, path=path)["project"]

    deleted = delete_chat_project({"projectId": created["id"]}, path=path)

    assert deleted["deleted"] is True
    assert deleted["projectId"] == created["id"]
    assert list_chat_projects(path=path)["projects"] == []
