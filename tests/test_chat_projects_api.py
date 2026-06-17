from __future__ import annotations

import json

import pytest

from agent_sessions import AgentSessionStore
from ui.backend.chat_projects_api import (
    ChatProjectAPIError,
    create_chat_project,
    delete_chat_project,
    list_chat_projects,
    rename_chat_project,
    sync_chat_project_session_metadata,
    update_chat_session_project,
)


class StubAgentService:
    def __init__(self, session_store: AgentSessionStore) -> None:
        self.session_store = session_store


def test_create_chat_project_persists_custom_project(tmp_path):
    path = tmp_path / "chat-projects.json"

    created = create_chat_project({"name": "Literature Review"}, path=path)
    listed = list_chat_projects(path=path)

    assert created["project"]["id"].startswith("project-")
    assert created["project"]["name"] == "Literature Review"
    assert listed["projects"] == created["projects"]
    assert json.loads(path.read_text(encoding="utf-8"))["projects"][0]["name"] == "Literature Review"


def test_create_chat_project_requires_name(tmp_path):
    with pytest.raises(ChatProjectAPIError) as error:
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


def test_update_chat_session_project_updates_session_metadata(tmp_path):
    service = StubAgentService(AgentSessionStore(tmp_path / "sessions"))
    session = service.session_store.create_session(title="Draft")

    updated = update_chat_session_project(
        {
            "sessionId": session.metadata.session_id,
            "projectId": "project-rag",
            "projectName": "RAG Review",
        },
        service=service,
    )
    listed = service.session_store.list_sessions()[0]
    assert listed.metadata["projectId"] == "project-rag"
    assert listed.metadata["projectName"] == "RAG Review"

    cleared = update_chat_session_project(
        {
            "sessionId": session.metadata.session_id,
            "projectId": "",
            "projectName": "",
        },
        service=service,
    )

    assert updated["session"]["projectId"] == "project-rag"
    assert updated["session"]["projectName"] == "RAG Review"
    assert set(updated["session"]["metadata"]) == {"projectId", "projectName"}
    assert cleared["session"]["projectId"] == ""
    assert cleared["session"]["projectName"] == ""
    assert set(cleared["session"]["metadata"]) == {"projectId", "projectName"}


def test_sync_chat_project_session_metadata_renames_and_clears_assignments(tmp_path):
    service = StubAgentService(AgentSessionStore(tmp_path / "sessions"))
    first = service.session_store.create_session(title="First")
    second = service.session_store.create_session(title="Second")
    update_chat_session_project(
        {"sessionId": first.metadata.session_id, "projectId": "project-rag", "projectName": "RAG"},
        service=service,
    )
    update_chat_session_project(
        {"sessionId": second.metadata.session_id, "projectId": "project-other", "projectName": "Other"},
        service=service,
    )

    renamed = sync_chat_project_session_metadata("project-rag", project_name="RAG Review", service=service)
    cleared = sync_chat_project_session_metadata("project-rag", clear=True, service=service)
    sessions = {metadata.session_id: metadata for metadata in service.session_store.list_sessions(include_archived=True)}

    assert renamed["updatedSessions"] == 1
    assert cleared["updatedSessions"] == 1
    assert sessions[first.metadata.session_id].metadata["projectId"] == ""
    assert sessions[first.metadata.session_id].metadata["projectName"] == ""
    assert sessions[second.metadata.session_id].metadata["projectId"] == "project-other"
