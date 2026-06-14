from __future__ import annotations

from tools.paper_notes.tool import create_tools


def test_paper_notes_tools_register_public_tool_set():
    tools = create_tools()

    assert [tool.name for tool in tools] == [
        "search_notes",
        "get_note_context",
        "read_paper",
        "search_paper_rag",
        "write_note",
        "manage_annotations",
        "write_note_media",
        "review_note",
    ]
    assert all(callable(tool.func) for tool in tools)
