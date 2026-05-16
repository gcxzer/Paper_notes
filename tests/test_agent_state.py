from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest

from agent_sessions import AgentSessionMetadata, AgentSessionStore, AgentTranscriptMessage, SessionNotFoundError, date_bucket_for


class Clock:
    def __init__(self, start: datetime) -> None:
        self.value = start

    def __call__(self) -> datetime:
        current = self.value
        self.value = current + timedelta(minutes=1)
        return current


def test_create_session_writes_index_and_date_bucket_transcript(tmp_path):
    root = tmp_path / ".paper-notes" / "sessions"
    store = AgentSessionStore(root, clock=Clock(datetime(2026, 5, 10, 9, 30, 0)))

    session = store.create_session(title="Attention notes", note_id="note-1", provider="openai", model="gpt-5.2")

    assert (root / "sessions.json").exists()
    assert session.metadata.date_bucket == "10_05_2026"
    assert store.transcript_path(session.metadata.session_id) == root / "10_05_2026" / f"{session.metadata.session_id}.jsonl"
    payload = json.loads((root / "sessions.json").read_text(encoding="utf-8"))
    indexed = payload["sessions"][session.metadata.session_id]
    assert indexed["title"] == "Attention notes"
    assert indexed["note_id"] == "note-1"
    assert indexed["metadata"]["originNoteId"] == "note-1"
    assert indexed["metadata"]["currentNoteId"] == "note-1"
    assert indexed["provider"] == "openai"
    assert indexed["message_count"] == 0
    assert store.transcript_path(session.metadata.session_id).read_text(encoding="utf-8") == ""


def test_append_message_updates_transcript_and_index(tmp_path):
    root = tmp_path / ".paper-notes" / "sessions"
    store = AgentSessionStore(root, clock=Clock(datetime(2026, 5, 10, 9, 30, 0)))
    session = store.create_session()

    updated = store.append_message(session.metadata.session_id, {"role": "user", "content": "Summarize this paper."})
    updated = store.append_message(
        session.metadata.session_id,
        AgentTranscriptMessage(role="assistant", content="Here is the summary.", metadata={"turn": 1}),
    )

    lines = store.transcript_path(session.metadata.session_id).read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["role"] for line in lines] == ["user", "assistant"]
    assert json.loads(lines[1])["metadata"] == {"turn": 1}
    assert updated.metadata.message_count == 2

    payload = json.loads((root / "sessions.json").read_text(encoding="utf-8"))
    assert payload["sessions"][session.metadata.session_id]["message_count"] == 2


def test_transcript_escapes_c1_line_separator_characters(tmp_path):
    root = tmp_path / ".paper-notes" / "sessions"
    store = AgentSessionStore(root, clock=Clock(datetime(2026, 5, 10, 9, 30, 0)))
    session = store.create_session()
    content = "binary-ish\u0085but still one JSONL record"

    store.append_message(session.metadata.session_id, {"role": "tool", "content": content})

    transcript = store.transcript_path(session.metadata.session_id).read_text(encoding="utf-8")
    assert "\\u0085" in transcript
    assert store.require_session(session.metadata.session_id).messages[0]["content"] == content


def test_get_session_loads_messages_in_order(tmp_path):
    store = AgentSessionStore(tmp_path / ".paper-notes" / "sessions", clock=Clock(datetime(2026, 5, 10, 9, 30, 0)))
    session = store.create_session(title="Chat")
    store.append_message(session.metadata.session_id, {"role": "user", "content": "First"})
    store.append_message(session.metadata.session_id, {"role": "assistant", "content": "Second", "finish_reason": "stop"})

    reloaded = AgentSessionStore(store.sessions_root).require_session(session.metadata.session_id)

    assert [message["content"] for message in reloaded.messages] == ["First", "Second"]
    assert reloaded.messages[1]["finish_reason"] == "stop"


def test_session_metadata_backfills_origin_and_current_note_from_legacy_note_id():
    metadata = AgentSessionMetadata.from_dict({
        "session_id": "session-1",
        "title": "Legacy",
        "created_at": "2026-05-10T09:30:00+00:00",
        "updated_at": "2026-05-10T09:30:00+00:00",
        "date_bucket": "10_05_2026",
        "note_id": "legacy-note",
        "metadata": {},
    })

    assert metadata.metadata["originNoteId"] == "legacy-note"
    assert metadata.metadata["currentNoteId"] == "legacy-note"


def test_list_sessions_sorts_by_updated_at_and_hides_archived(tmp_path):
    store = AgentSessionStore(tmp_path / ".paper-notes" / "sessions", clock=Clock(datetime(2026, 5, 10, 9, 30, 0)))
    old_session = store.create_session(title="Old")
    new_session = store.create_session(title="New")
    store.archive_session(old_session.metadata.session_id)

    visible = store.list_sessions()
    archived_sessions = store.list_sessions(state="archived")
    all_sessions = store.list_sessions(include_archived=True)

    assert [session.session_id for session in visible] == [new_session.metadata.session_id]
    assert [session.session_id for session in archived_sessions] == [old_session.metadata.session_id]
    assert [session.title for session in all_sessions] == ["Old", "New"]


def test_session_state_tracks_archive_and_trash_separately(tmp_path):
    store = AgentSessionStore(tmp_path / ".paper-notes" / "sessions", clock=Clock(datetime(2026, 5, 10, 9, 30, 0)))
    session = store.create_session(title="Stateful")

    archived = store.update_session_state(session.metadata.session_id, state="archived")
    assert archived.state == "archived"
    assert archived.archived is True

    trashed = store.update_session_state(session.metadata.session_id, state="trashed")
    assert trashed.state == "trashed"
    assert trashed.archived is False
    assert "archivedAt" in trashed.metadata
    assert "trashedAt" in trashed.metadata

    restored = store.update_session_state(session.metadata.session_id, state="active")
    assert restored.state == "active"
    assert restored.archived is False


def test_replace_messages_rewrites_jsonl_atomically(tmp_path):
    store = AgentSessionStore(tmp_path / ".paper-notes" / "sessions", clock=Clock(datetime(2026, 5, 10, 9, 30, 0)))
    session = store.create_session()
    store.append_message(session.metadata.session_id, {"role": "user", "content": "Old"})

    updated = store.replace_messages(session.metadata.session_id, [{"role": "assistant", "content": "Fresh"}])

    assert updated.metadata.message_count == 1
    assert updated.messages == [{
        "role": "assistant",
        "content": "Fresh",
        "created_at": updated.messages[0]["created_at"],
    }]
    assert store.require_session(session.metadata.session_id).messages[0]["content"] == "Fresh"


def test_delete_session_removes_index_and_transcript(tmp_path):
    store = AgentSessionStore(tmp_path / ".paper-notes" / "sessions", clock=Clock(datetime(2026, 5, 10, 9, 30, 0)))
    session = store.create_session(title="Delete me")
    store.append_message(session.metadata.session_id, {"role": "user", "content": "Hello"})
    transcript_path = store.transcript_path(session.metadata.session_id)

    deleted = store.delete_session(session.metadata.session_id)

    assert deleted.title == "Delete me"
    assert store.get_session(session.metadata.session_id) is None
    assert not transcript_path.exists()
    assert json.loads((store.sessions_root / "sessions.json").read_text(encoding="utf-8"))["sessions"] == {}


def test_update_session_model_persists_provider_and_model(tmp_path):
    store = AgentSessionStore(tmp_path / ".paper-notes" / "sessions", clock=Clock(datetime(2026, 5, 10, 9, 30, 0)))
    session = store.create_session(title="Model lane")

    updated = store.update_session_model(session.metadata.session_id, provider="codex-oauth", model="gpt-5.5")

    assert updated.metadata.provider == "codex-oauth"
    assert updated.metadata.model == "gpt-5.5"
    reloaded = AgentSessionStore(store.sessions_root).require_session(session.metadata.session_id)
    assert reloaded.metadata.provider == "codex-oauth"
    assert reloaded.metadata.model == "gpt-5.5"


def test_branch_session_copies_transcript_and_parent_metadata(tmp_path):
    store = AgentSessionStore(tmp_path / ".paper-notes" / "sessions", clock=Clock(datetime(2026, 5, 10, 9, 30, 0)))
    session = store.create_session(
        title="Original",
        note_id="note-1",
        provider="openai",
        model="gpt-test",
        metadata={"kind": "reader"},
    )
    store.append_message(session.metadata.session_id, {"role": "user", "content": "Question"})
    store.append_message(session.metadata.session_id, {"role": "assistant", "content": "Answer"})

    branch = store.branch_session(session.metadata.session_id, title="Branch")

    assert branch.metadata.session_id != session.metadata.session_id
    assert branch.metadata.title == "Branch"
    assert branch.metadata.note_id == "note-1"
    assert branch.metadata.provider == "openai"
    assert branch.metadata.model == "gpt-test"
    assert branch.metadata.metadata["parent_session_id"] == session.metadata.session_id
    assert [message["content"] for message in branch.messages] == ["Question", "Answer"]
    assert store.require_session(session.metadata.session_id).metadata.title == "Original"


def test_undo_last_turn_removes_last_user_message_and_following_messages(tmp_path):
    store = AgentSessionStore(tmp_path / ".paper-notes" / "sessions", clock=Clock(datetime(2026, 5, 10, 9, 30, 0)))
    session = store.create_session()
    store.replace_messages(session.metadata.session_id, [
        {"role": "user", "content": "First"},
        {"role": "assistant", "content": "First answer"},
        {"role": "user", "content": "Second"},
        {"role": "assistant", "content": "Second answer"},
        {"role": "tool", "content": "Tool output"},
    ])

    updated, removed_count = store.undo_last_turn(session.metadata.session_id)

    assert removed_count == 3
    assert [message["content"] for message in updated.messages] == ["First", "First answer"]
    assert updated.metadata.message_count == 2


def test_undo_last_turn_is_noop_without_user_message(tmp_path):
    store = AgentSessionStore(tmp_path / ".paper-notes" / "sessions")
    session = store.create_session()
    store.append_message(session.metadata.session_id, {"role": "assistant", "content": "Hello"})

    updated, removed_count = store.undo_last_turn(session.metadata.session_id)

    assert removed_count == 0
    assert [message["content"] for message in updated.messages] == ["Hello"]


def test_missing_session_raises(tmp_path):
    store = AgentSessionStore(tmp_path / ".paper-notes" / "sessions")

    with pytest.raises(SessionNotFoundError):
        store.append_message("missing", {"role": "user", "content": "Hello"})


def test_date_bucket_uses_day_month_year():
    assert date_bucket_for(datetime(2026, 5, 10, 9, 30, 0)) == "10_05_2026"
