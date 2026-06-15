from __future__ import annotations

import json

from tools.paper_notes.tool import create_tools
from tools.paper_notes.impl import facade
from tools.paper_notes.schemas import get_paper_context_parameters, inspect_paper_visuals_parameters


def test_paper_notes_tools_register_public_tool_set():
    tools = create_tools()

    assert [tool.name for tool in tools] == [
        "get_paper_context",
        "inspect_paper_visuals",
        "query_paper_content",
        "manage_annotations",
        "write_note",
        "write_note_media",
        "review_note",
    ]
    assert all(callable(tool.func) for tool in tools)
    assert "search_notes" not in [tool.name for tool in tools]
    assert "get_note_context" not in [tool.name for tool in tools]


def test_get_paper_context_schema_fuses_search_and_context():
    schema = get_paper_context_parameters()

    assert {"note_id", "query", "limit", "include_html", "html_mode"} <= set(schema["properties"])
    assert schema["required"] == []


def test_query_paper_content_schema_accepts_multiple_queries():
    tool = next(tool for tool in create_tools() if tool.name == "query_paper_content")
    schema = tool.args_schema

    assert "Primary tool for reading and answering questions about a paper" in tool.description
    assert "library metadata" in tool.description
    assert "queries" in schema["properties"]
    assert schema["properties"]["queries"]["maxItems"] == 5
    assert schema["required"] == ["note_id"]


def test_paper_notes_tools_hide_visual_inspection_when_unavailable():
    tools = create_tools(visual_inspection_available=False)
    names = [tool.name for tool in tools]
    query_tool = next(tool for tool in tools if tool.name == "query_paper_content")

    assert "inspect_paper_visuals" not in names
    assert "This model cannot inspect paper images" in query_tool.description


def test_get_paper_context_searches_metadata(tmp_path):
    library_path = tmp_path / "notes.json"
    library_path.write_text(
        json.dumps({
            "notes": [
                {"id": "note-1", "title": "Attention Is All You Need", "summary": "Transformer attention."},
                {"id": "note-2", "title": "Graph Networks", "summary": "Message passing."},
            ]
        }),
        encoding="utf-8",
    )

    result = facade.get_paper_context({"query": "attention", "limit": 5}, library_path=library_path)

    assert result["success"] is True
    assert result["operation"] == "search"
    assert [note["id"] for note in result["notes"]] == ["note-1"]


def test_get_paper_context_reads_one_note_context(tmp_path):
    library_path = tmp_path / "notes.json"
    html_dir = tmp_path / "Paper-html"
    html_dir.mkdir()
    (html_dir / "Attention.html").write_text(
        '<html><body><section class="note-body"><h2>Motivation</h2><p>Why attention matters.</p></section></body></html>',
        encoding="utf-8",
    )
    library_path.write_text(
        json.dumps({
            "notes": [
                {
                    "id": "note-1",
                    "title": "Attention Is All You Need",
                    "htmlHref": "resources/Paper-html/Attention.html",
                }
            ]
        }),
        encoding="utf-8",
    )

    result = facade.get_paper_context(
        {"note_id": "note-1", "include_html": True},
        library_path=library_path,
        annotations_dir=tmp_path / "annotations",
        html_dir=html_dir,
    )

    assert result["success"] is True
    assert result["operation"] == "context"
    assert result["note"]["title"] == "Attention Is All You Need"
    assert result["sections"][0]["heading"] == "Motivation"
    assert "Why attention matters." in result["html"]["html"]


def test_inspect_paper_visuals_schema_is_visual_only():
    schema = inspect_paper_visuals_parameters()

    assert schema["properties"]["action"]["enum"] == ["render_page", "extract_images"]
    assert "max_chars" not in schema["properties"]
    assert "artifact_id" not in schema["properties"]


def test_inspect_paper_visuals_schema_includes_analysis_only_when_available():
    schema = inspect_paper_visuals_parameters(image_analysis=True)

    assert schema["properties"]["action"]["enum"] == ["render_page", "extract_images", "analyze_image"]
    assert "artifact_id" in schema["properties"]


def test_inspect_paper_visuals_rejects_removed_text_actions():
    result = facade.inspect_paper_visuals({"note_id": "note-1", "action": "read_pages"})

    assert result["success"] is False
    assert result["code"] == "invalid_action"
    assert "render_page, extract_images, or analyze_image" in result["error"]
