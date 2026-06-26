from __future__ import annotations

import json

from tools.paper_notes.tool import create_tools
from tools.paper_notes.impl import facade
from tools.paper_notes.impl import paper as paper_impl
from tools.paper_notes.schemas import get_paper_context_parameters, inspect_paper_visuals_parameters, read_paper_parameters


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


def test_query_paper_content_schema_accepts_single_query():
    tool = next(tool for tool in create_tools() if tool.name == "query_paper_content")
    schema = tool.args_schema

    assert "Semantic RAG tool for reading and answering questions about a paper" in tool.description
    assert "when RAG querying is enabled" in tool.description
    assert "library metadata" in tool.description
    assert "Send one short retrieval query" in tool.description
    assert "Figure 3" in tool.description
    assert "picture/image/visual N" in tool.description
    assert "query" in schema["properties"]
    assert schema["properties"]["query"]["type"] == "string"
    query_description = schema["properties"]["query"]["description"]
    assert "Prefer exact labels and keywords" in query_description
    assert "user 'what does Figure 3 show?' -> query 'Figure 3'" in query_description
    assert "user 'what is picture 8 in the paper?' -> query 'Figure 8'" in query_description
    assert "active reconstruction passive retrieval memory graph" in query_description
    assert "queries" not in schema["properties"]
    assert "embedding_provider" not in schema["properties"]
    assert "embedding_model" not in schema["properties"]
    assert "similarity_top_k" not in schema["properties"]
    assert "bm25_similarity_top_k" not in schema["properties"]
    assert "vector_top_k" not in schema["properties"]
    assert "bm25_top_k" not in schema["properties"]
    assert "result_top_k" not in schema["properties"]
    assert schema["required"] == ["note_id", "query"]


def test_read_paper_schema_exposes_direct_text_actions():
    schema = read_paper_parameters()

    assert schema["properties"]["action"]["enum"] == ["search_text", "read_pages"]
    assert {"note_id", "query", "page_start", "page_end", "limit", "max_chars"} <= set(schema["properties"])
    assert "render_page" not in schema["properties"]["action"]["enum"]
    assert schema["required"] == ["note_id"]


def test_read_paper_uses_cached_text_for_search_and_pages(tmp_path):
    library_path = tmp_path / "notes.json"
    cache_dir = tmp_path / "Paper-text"
    cache_dir.mkdir()
    library_path.write_text(
        json.dumps({"notes": [{"id": "note-1", "title": "Cached Paper"}]}),
        encoding="utf-8",
    )
    (cache_dir / "note-1.json").write_text(
        json.dumps({
            "pages": [
                {"page": 1, "text": "The model uses active reconstruction for memory."},
                {"page": 2, "text": "Passive retrieval is compared with active reconstruction."},
            ]
        }),
        encoding="utf-8",
    )

    search = facade.read_paper(
        {"note_id": "note-1", "action": "search_text", "query": "active reconstruction"},
        library_path=library_path,
        paper_text_cache_dir=cache_dir,
    )
    pages = facade.read_paper(
        {"note_id": "note-1", "action": "read_pages", "page_start": 2, "page_end": 2},
        library_path=library_path,
        paper_text_cache_dir=cache_dir,
    )

    assert search["success"] is True
    assert search["source"] == "cache"
    assert search["matches"][0]["page"] == 1
    assert pages["success"] is True
    assert pages["text"].startswith("[Page 2]")
    assert "Passive retrieval" in pages["text"]


def test_paper_notes_tools_hide_visual_inspection_when_unavailable():
    tools = create_tools(visual_inspection_available=False)
    names = [tool.name for tool in tools]
    query_tool = next(tool for tool in tools if tool.name == "query_paper_content")

    assert "read_paper" not in names
    assert "inspect_paper_visuals" not in names
    assert "This model cannot inspect paper images" in query_tool.description


def test_paper_notes_tools_hide_query_when_rag_disabled(monkeypatch, tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"rag": {"enabled": False}}), encoding="utf-8")
    monkeypatch.setenv("PAPER_NOTES_CONFIG", str(config_path))

    names = [tool.name for tool in create_tools()]

    assert "read_paper" in names
    assert "query_paper_content" not in names


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


def test_inspect_paper_visuals_schema_supports_render_extract_and_analysis():
    schema = inspect_paper_visuals_parameters()

    assert schema["properties"]["action"]["enum"] == ["render_page", "extract_images", "analyze_image"]
    assert "max_chars" not in schema["properties"]
    assert {"artifact_id", "path", "query", "question", "figure_label"} <= set(schema["properties"])
    assert "not a Figure/Table number" in schema["properties"]["page"]["description"]


def test_inspect_paper_visuals_rejects_removed_text_actions():
    result = facade.inspect_paper_visuals({"note_id": "note-1", "action": "read_pages"})

    assert result["success"] is False
    assert result["code"] == "invalid_action"
    assert "render_page, extract_images, or analyze_image" in result["error"]


def test_inspect_paper_visuals_analyzes_registered_artifact(tmp_path):
    library_path = tmp_path / "notes.json"
    library_path.write_text(
        json.dumps({"notes": [{"id": "note-1", "title": "Visual Paper"}]}),
        encoding="utf-8",
    )
    analyzer_calls = []

    def fake_analyzer(args):
        analyzer_calls.append(args)
        return {
            "success": True,
            "artifact": {"id": args["artifact_id"], "kind": "image"},
            "analysis": "The chart visually compares model accuracy and efficiency.",
        }

    result = facade.inspect_paper_visuals(
        {
            "note_id": "note-1",
            "action": "analyze_image",
            "artifact_id": "img-test",
            "query": "Explain Figure 1 from the visible chart.",
        },
        library_path=library_path,
        paper_image_analyzer=fake_analyzer,
    )

    assert result["success"] is True
    assert result["artifact_id"] == "img-test"
    assert result["artifact"]["id"] == "img-test"
    assert result["analysis"] == "The chart visually compares model accuracy and efficiency."
    assert analyzer_calls == [{
        "artifact_id": "img-test",
        "path": None,
        "question": "Explain Figure 1 from the visible chart.",
    }]


def test_inspect_paper_visuals_analyzes_rendered_page(monkeypatch, tmp_path):
    library_path = tmp_path / "notes.json"
    library_path.write_text(
        json.dumps({"notes": [{"id": "note-1", "title": "Rendered Paper"}]}),
        encoding="utf-8",
    )
    render_calls = []
    analyzer_calls = []

    def fake_render(args, **kwargs):
        render_calls.append((args, kwargs))
        return {
            "success": True,
            "artifact_id": "img-page-3",
            "artifact": {"id": "img-page-3", "kind": "image"},
            "width": 1200,
            "height": 1600,
            "relative_path": "resources/Paper-visuals/note-1/pages/page-0003-scale-2.png",
            "preview_url": "/media/img-page-3",
        }

    def fake_analyzer(args):
        analyzer_calls.append(args)
        return {"success": True, "analysis": "The rendered page shows a full figure with labels."}

    monkeypatch.setattr(paper_impl, "render_paper_page", fake_render)

    result = facade.inspect_paper_visuals(
        {
            "note_id": "note-1",
            "page": 3,
            "query": "What is visible on this page?",
        },
        library_path=library_path,
        paper_image_analyzer=fake_analyzer,
    )

    assert result["success"] is True
    assert result["source"] == "pdf_page"
    assert result["page"] == 3
    assert result["artifact_id"] == "img-page-3"
    assert result["analysis"] == "The rendered page shows a full figure with labels."
    assert result["rendered"]["width"] == 1200
    assert render_calls[0][0] == {"note_id": "note-1", "page": 3, "scale": 2.0}
    assert analyzer_calls == [{
        "artifact_id": "img-page-3",
        "path": None,
        "question": "What is visible on this page?",
    }]


def test_inspect_paper_visuals_corrects_figure_label_page_for_image_extraction(monkeypatch, tmp_path):
    library_path = tmp_path / "notes.json"
    library_path.write_text(
        json.dumps({"notes": [{"id": "note-1", "title": "Visual Paper"}]}),
        encoding="utf-8",
    )
    extraction_calls = []

    monkeypatch.setattr(
        paper_impl,
        "_load_or_extract_paper_text",
        lambda note, **kwargs: {
            "success": True,
            "source": "cache",
            "pages": [
                {"page": 2, "text": "Regular body text without the target figure."},
                {"page": 6, "text": "Figure 2 | Overall architecture of the model."},
            ],
        },
    )
    monkeypatch.setattr(
        paper_impl,
        "_resolved_pdf_path_for_note",
        lambda note, **kwargs: {"pdf_path": tmp_path / "paper.pdf"},
    )

    def fake_extract_pdf_images(**kwargs):
        extraction_calls.append(kwargs)
        return {
            "success": True,
            "note_id": kwargs["note_id"],
            "page_start": kwargs["page_start"],
            "page_end": kwargs["page_end"],
            "count": 0,
            "images": [],
            "source_pdf": "paper.pdf",
            "limit": kwargs["limit"],
        }

    monkeypatch.setattr(paper_impl, "_extract_pdf_images", fake_extract_pdf_images)

    result = facade.inspect_paper_visuals(
        {
            "note_id": "note-1",
            "action": "extract_images",
            "query": "Figure 2 page 2",
            "page_start": 2,
            "page_end": 2,
        },
        library_path=library_path,
    )

    assert result["success"] is True
    assert extraction_calls[0]["page_start"] == 6
    assert extraction_calls[0]["page_end"] == 6
    assert result["resolved_figure"] == {"label": "Figure 2", "page": 6, "source": "cache"}
    assert result["page_correction"]["requested_page"] == 2
    assert result["page_correction"]["resolved_page"] == 6
    assert "No embedded raster images" in result["hint"]


def test_inspect_paper_visuals_analyzes_chinese_figure_label_on_resolved_page(monkeypatch, tmp_path):
    library_path = tmp_path / "notes.json"
    library_path.write_text(
        json.dumps({"notes": [{"id": "note-1", "title": "Visual Paper"}]}),
        encoding="utf-8",
    )
    render_calls = []
    analyzer_calls = []

    monkeypatch.setattr(
        paper_impl,
        "_load_or_extract_paper_text",
        lambda note, **kwargs: {
            "success": True,
            "source": "cache",
            "pages": [{"page": 6, "text": "Figure 2 | Overall architecture of the model."}],
        },
    )
    monkeypatch.setattr(
        paper_impl,
        "_resolved_pdf_path_for_note",
        lambda note, **kwargs: {"pdf_path": tmp_path / "paper.pdf"},
    )

    def fake_render_pdf_page(**kwargs):
        render_calls.append(kwargs)
        return {
            "success": True,
            "note_id": kwargs["note_id"],
            "page": kwargs["page_number"],
            "artifact_id": "img-page-6",
            "artifact": {"id": "img-page-6", "kind": "image"},
            "image_path": str(tmp_path / "page-6.png"),
            "width": 1200,
            "height": 1600,
            "relative_path": "page-6.png",
            "preview_url": "/media/img-page-6",
            "download_url": "/media/img-page-6/download",
        }

    def fake_analyzer(args):
        analyzer_calls.append(args)
        return {"success": True, "analysis": "The rendered page shows the model architecture diagram."}

    monkeypatch.setattr(paper_impl, "_render_pdf_page", fake_render_pdf_page)

    result = facade.inspect_paper_visuals(
        {
            "note_id": "note-1",
            "action": "analyze_image",
            "query": "图二说什么",
            "page": 2,
            "scale": 2,
        },
        library_path=library_path,
        paper_image_analyzer=fake_analyzer,
    )

    assert result["success"] is True
    assert render_calls[0]["page_number"] == 6
    assert analyzer_calls[0]["artifact_id"] == "img-page-6"
    assert result["resolved_figure"] == {"label": "Figure 2", "page": 6, "source": "cache"}
    assert result["page_correction"]["requested_page"] == 2
    assert result["page_correction"]["resolved_page"] == 6
    assert result["analysis"] == "The rendered page shows the model architecture diagram."


def test_paper_visual_cache_paths_share_one_root():
    page_path = paper_impl._paper_page_cache_path("note-1", page_number=2, scale=2)
    image_dir = paper_impl._paper_visual_images_dir("note-1")

    visual_root = paper_impl.PAPER_VISUALS_DIR / "note-1"
    assert page_path.parent == visual_root / "pages"
    assert image_dir == visual_root / "images"
