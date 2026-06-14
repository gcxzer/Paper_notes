from __future__ import annotations

from tools.paper_notes.tool import create_tools
from tools.paper_notes.impl import workspace


def test_paper_notes_tools_register_public_tool_set():
    tools = create_tools()

    assert [tool.name for tool in tools] == [
        "search_notes",
        "get_note_context",
        "read_paper",
        "read_workspace",
        "search_paper_rag",
        "write_note",
        "manage_annotations",
        "write_note_media",
        "review_note",
    ]
    assert all(callable(tool.func) for tool in tools)


def test_read_workspace_reads_files_under_workspace(monkeypatch, tmp_path):
    monkeypatch.setattr(workspace, "PROJECT_ROOT", tmp_path)
    generated = tmp_path / ".paper-notes" / "media" / "generated" / "summary.md"
    generated.parent.mkdir(parents=True)
    generated.write_text("line one\nline two\nline three\n", encoding="utf-8")

    result = workspace.read_workspace({
        "action": "read",
        "path": ".paper-notes/media/generated/summary.md",
        "offset": 2,
        "limit": 1,
    })

    assert result["success"] is True
    assert result["path"] == ".paper-notes/media/generated/summary.md"
    assert result["content"] == "line two\n"
    assert result["lineStart"] == 2
    assert result["lineEnd"] == 2


def test_read_workspace_blocks_paths_outside_workspace(monkeypatch, tmp_path):
    monkeypatch.setattr(workspace, "PROJECT_ROOT", tmp_path / "workspace")
    outside = tmp_path / "outside.txt"
    outside.write_text("outside", encoding="utf-8")

    result = workspace.read_workspace({"action": "read", "path": str(outside)})

    assert result["success"] is False
    assert result["code"] == "path_outside_workspace"


def test_read_workspace_redacts_credential_like_values(monkeypatch, tmp_path):
    monkeypatch.setattr(workspace, "PROJECT_ROOT", tmp_path)
    secrets = tmp_path / ".paper-notes" / "secrets.env"
    secrets.parent.mkdir(parents=True)
    secrets.write_text("OPENAI_API_KEY=sk-test-secret-value\nplain=value\n", encoding="utf-8")

    result = workspace.read_workspace({"action": "read", "path": ".paper-notes/secrets.env"})

    assert result["success"] is True
    assert result["redacted"] is True
    assert "sk-test-secret-value" not in result["content"]
    assert "OPENAI_API_KEY=[REDACTED]" in result["content"]


def test_read_workspace_lists_and_searches_workspace(monkeypatch, tmp_path):
    monkeypatch.setattr(workspace, "PROJECT_ROOT", tmp_path)
    (tmp_path / "resources").mkdir()
    (tmp_path / "resources" / "note.md").write_text("DeepSeek V4\n", encoding="utf-8")
    (tmp_path / "resources" / "other.txt").write_text("other\n", encoding="utf-8")

    listed = workspace.read_workspace({"action": "list", "path": "resources", "glob": "*.md"})
    searched = workspace.read_workspace({"action": "search", "path": "resources", "query": "deepseek", "glob": "*.md"})

    assert [entry["path"] for entry in listed["entries"]] == ["resources/note.md"]
    assert searched["matches"] == [{"path": "resources/note.md", "line": 1, "text": "DeepSeek V4", "redacted": False}]
