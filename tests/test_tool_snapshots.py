from __future__ import annotations

import json

import pytest

from tool_safety import PaperNotesSnapshotManager, ToolSnapshotConflictError
from library import write_library
from model_providers.types import ToolCall
from tools.executor import ToolExecutorAdapter
from tools.paper_notes import create_paper_notes_registry


def _snapshot_fixture(tmp_path):
    library_path = tmp_path / "notes.json"
    html_dir = tmp_path / "Paper-html"
    annotations_dir = tmp_path / "Paper-annotations"
    html_dir.mkdir(parents=True)
    html_path = html_dir / "note-1.html"
    html_path.write_text(
        "<html><body><main class=\"note-body\"><h2>Existing</h2><p>Old.</p></main></body></html>",
        encoding="utf-8",
    )
    write_library({
        "notes": [{
            "id": "note-1",
            "title": "Paper",
            "htmlHref": "resources/Paper-html/note-1.html",
        }],
    }, library_path)
    registry = create_paper_notes_registry(
        library_path=library_path,
        html_dir=html_dir,
        annotations_dir=annotations_dir,
    )
    manager = PaperNotesSnapshotManager(
        tmp_path / ".paper-notes" / "snapshots",
        project_root=tmp_path,
        notes_path=library_path,
        html_dir=html_dir,
        annotations_dir=annotations_dir,
    )
    return registry, manager, html_path


def test_mutating_paper_note_tool_creates_snapshot_and_can_restore(tmp_path):
    registry, manager, html_path = _snapshot_fixture(tmp_path)
    executor = ToolExecutorAdapter(
        registry,
        snapshot_manager=manager,
        session_id_provider=lambda: "session-1",
    )

    result = executor.execute(ToolCall(
        id="call-1",
        name="write_note",
        arguments=json.dumps({
            "action": "append_to_section",
            "note_id": "note-1",
            "heading": "Agent Notes",
            "html": "<p>New note.</p>",
        }),
    ))
    snapshot = result.metadata["snapshot"]

    assert result.is_error is False
    assert snapshot["changed"] is True
    assert snapshot["changedFiles"][0]["path"] == "Paper-html/note-1.html"
    assert "Agent Notes" in html_path.read_text(encoding="utf-8")

    restored = manager.restore(session_id="session-1", snapshot_id=snapshot["snapshotId"])

    assert restored["success"] is True
    assert restored["restoredFiles"] == ["Paper-html/note-1.html"]
    assert "Agent Notes" not in html_path.read_text(encoding="utf-8")

    redone = manager.redo(session_id="session-1", snapshot_id=snapshot["snapshotId"])

    assert redone["success"] is True
    assert redone["redoneFiles"] == ["Paper-html/note-1.html"]
    assert "Agent Notes" in html_path.read_text(encoding="utf-8")


def test_write_note_facade_creates_snapshot(tmp_path):
    registry, manager, html_path = _snapshot_fixture(tmp_path)
    executor = ToolExecutorAdapter(
        registry,
        snapshot_manager=manager,
        session_id_provider=lambda: "session-1",
    )

    result = executor.execute(ToolCall(
        id="call-1",
        name="write_note",
        arguments=json.dumps({
            "action": "append_to_section",
            "note_id": "note-1",
            "heading": "Facade Notes",
            "html": "<p>New note.</p>",
        }),
    ))
    snapshot = result.metadata["snapshot"]

    assert result.is_error is False
    assert snapshot["changed"] is True
    assert snapshot["changedFiles"][0]["path"] == "Paper-html/note-1.html"
    assert "Facade Notes" in html_path.read_text(encoding="utf-8")


def test_snapshot_preview_diff_returns_text_diff(tmp_path):
    registry, manager, _ = _snapshot_fixture(tmp_path)
    executor = ToolExecutorAdapter(
        registry,
        snapshot_manager=manager,
        session_id_provider=lambda: "session-1",
    )

    result = executor.execute(ToolCall(
        id="call-1",
        name="write_note",
        arguments=json.dumps({
            "action": "append_to_section",
            "note_id": "note-1",
            "heading": "Agent Notes",
            "html": "<p>New note.</p>",
        }),
    ))
    snapshot = result.metadata["snapshot"]

    preview = manager.preview_diff(session_id="session-1", snapshot_id=snapshot["snapshotId"])

    assert preview["success"] is True
    assert preview["snapshotId"] == snapshot["snapshotId"]
    assert preview["files"][0]["path"] == "Paper-html/note-1.html"
    assert preview["files"][0]["currentMatchesSnapshot"] is True
    assert "+<h2 id=\"agent-notes\">Agent Notes</h2>" in preview["files"][0]["diff"]


def test_snapshot_preview_diff_stays_stable_after_restore(tmp_path):
    registry, manager, html_path = _snapshot_fixture(tmp_path)
    executor = ToolExecutorAdapter(
        registry,
        snapshot_manager=manager,
        session_id_provider=lambda: "session-1",
    )

    result = executor.execute(ToolCall(
        id="call-1",
        name="write_note",
        arguments=json.dumps({
            "action": "append_to_section",
            "note_id": "note-1",
            "heading": "Agent Notes",
            "html": "<p>New note.</p>",
        }),
    ))
    snapshot = result.metadata["snapshot"]
    preview_before_restore = manager.preview_diff(session_id="session-1", snapshot_id=snapshot["snapshotId"])

    manager.restore(session_id="session-1", snapshot_id=snapshot["snapshotId"])
    assert "Agent Notes" not in html_path.read_text(encoding="utf-8")
    preview_after_restore = manager.preview_diff(session_id="session-1", snapshot_id=snapshot["snapshotId"])

    assert preview_after_restore["files"][0]["currentMatchesSnapshot"] is False
    assert preview_after_restore["files"][0]["diff"] == preview_before_restore["files"][0]["diff"]
    assert "+<h2 id=\"agent-notes\">Agent Notes</h2>" in preview_after_restore["files"][0]["diff"]


def test_duplicate_tool_call_ids_do_not_overwrite_existing_snapshot(tmp_path):
    registry, manager, _ = _snapshot_fixture(tmp_path)
    executor = ToolExecutorAdapter(
        registry,
        snapshot_manager=manager,
        session_id_provider=lambda: "session-1",
    )

    first = executor.execute(ToolCall(
        id="call-duplicate",
        name="write_note",
        arguments=json.dumps({
            "action": "append_to_section",
            "note_id": "note-1",
            "heading": "First Snapshot",
            "html": "<p>First.</p>",
        }),
    )).metadata["snapshot"]
    second = executor.execute(ToolCall(
        id="call-duplicate",
        name="write_note",
        arguments=json.dumps({
            "action": "append_to_section",
            "note_id": "note-1",
            "heading": "Second Snapshot",
            "html": "<p>Second.</p>",
        }),
    )).metadata["snapshot"]

    first_preview = manager.preview_diff(session_id="session-1", snapshot_id=first["snapshotId"])
    second_preview = manager.preview_diff(session_id="session-1", snapshot_id=second["snapshotId"])

    assert first["snapshotId"] == "call-duplicate"
    assert second["snapshotId"] == "call-duplicate-2"
    assert "First Snapshot" in first_preview["files"][0]["diff"]
    assert "Second Snapshot" not in first_preview["files"][0]["diff"]
    assert "Second Snapshot" in second_preview["files"][0]["diff"]


def test_read_only_tool_does_not_create_snapshot(tmp_path):
    registry, manager, _ = _snapshot_fixture(tmp_path)
    executor = ToolExecutorAdapter(
        registry,
        snapshot_manager=manager,
        session_id_provider=lambda: "session-1",
    )

    result = executor.execute(ToolCall(id="call-1", name="get_note_context", arguments='{"action":"append_to_section","note_id": "note-1"}'))

    assert result.is_error is False
    assert "snapshot" not in result.metadata


def test_snapshot_restore_detects_newer_file_changes(tmp_path):
    registry, manager, html_path = _snapshot_fixture(tmp_path)
    executor = ToolExecutorAdapter(
        registry,
        snapshot_manager=manager,
        session_id_provider=lambda: "session-1",
    )
    result = executor.execute(ToolCall(
        id="call-1",
        name="write_note",
        arguments='{"action":"append_to_section","note_id":"note-1","heading":"Agent Notes","html":"<p>New note.</p>"}',
    ))
    snapshot = result.metadata["snapshot"]
    html_path.write_text(html_path.read_text(encoding="utf-8") + "\n<p>User changed it.</p>", encoding="utf-8")

    with pytest.raises(ToolSnapshotConflictError) as error:
        manager.restore(session_id="session-1", snapshot_id=snapshot["snapshotId"])

    assert error.value.conflicts[0]["path"] == "Paper-html/note-1.html"
    forced = manager.restore(session_id="session-1", snapshot_id=snapshot["snapshotId"], force=True)
    assert forced["forced"] is True
    assert "User changed it" not in html_path.read_text(encoding="utf-8")


def test_snapshot_restore_and_redo_conflict_with_later_snapshot(tmp_path):
    registry, manager, html_path = _snapshot_fixture(tmp_path)
    executor = ToolExecutorAdapter(
        registry,
        snapshot_manager=manager,
        session_id_provider=lambda: "session-1",
    )

    first = executor.execute(ToolCall(
        id="call-1",
        name="write_note",
        arguments='{"action":"append_to_section","note_id":"note-1","heading":"First","html":"<p>First.</p>"}',
    )).metadata["snapshot"]
    second = executor.execute(ToolCall(
        id="call-2",
        name="write_note",
        arguments='{"action":"append_to_section","note_id":"note-1","heading":"Second","html":"<p>Second.</p>"}',
    )).metadata["snapshot"]
    snapshots_after_second = {snapshot["snapshotId"]: snapshot for snapshot in manager.list_snapshots(session_id="session-1")}

    assert snapshots_after_second[first["snapshotId"]]["canUndo"] is False
    assert snapshots_after_second[second["snapshotId"]]["canUndo"] is True

    with pytest.raises(ToolSnapshotConflictError):
        manager.restore(session_id="session-1", snapshot_id=first["snapshotId"])
    assert "Second" in html_path.read_text(encoding="utf-8")

    manager.restore(session_id="session-1", snapshot_id=first["snapshotId"], force=True)
    snapshots_after_force_restore = {snapshot["snapshotId"]: snapshot for snapshot in manager.list_snapshots(session_id="session-1")}
    assert snapshots_after_force_restore[second["snapshotId"]]["canRedo"] is False
    with pytest.raises(ToolSnapshotConflictError):
        manager.redo(session_id="session-1", snapshot_id=second["snapshotId"])
    assert "First" not in html_path.read_text(encoding="utf-8")


def test_snapshot_list_and_cleanup(tmp_path):
    registry, manager, _ = _snapshot_fixture(tmp_path)
    executor = ToolExecutorAdapter(
        registry,
        snapshot_manager=manager,
        session_id_provider=lambda: "session-1",
    )
    for index in range(3):
        executor.execute(ToolCall(
            id=f"call-{index}",
            name="write_note",
            arguments=json.dumps({
                "action": "append_to_section",
                "note_id": "note-1",
                "heading": f"Agent Notes {index}",
                "html": "<p>New note.</p>",
            }),
        ))

    snapshots = manager.list_snapshots(session_id="session-1")
    cleanup = manager.cleanup(session_id="session-1", keep_per_session=1)

    assert len(snapshots) == 3
    assert snapshots[0]["snapshotId"] == "call-2"
    assert cleanup["deletedCount"] == 2
    assert len(manager.list_snapshots(session_id="session-1")) == 1
