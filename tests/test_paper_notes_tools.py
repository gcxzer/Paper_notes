from __future__ import annotations

import base64
import json

from library.annotations import write_annotations
from library import write_library
from media import MediaStore
from model_providers.types import ToolCall
from tools.executor import ToolExecutorAdapter
from tools.paper_notes import create_paper_notes_registry


def _paper_note_fixture(tmp_path):
    library_path = tmp_path / "notes.json"
    html_dir = tmp_path / "Paper-html"
    cache_dir = tmp_path / "paper-text"
    html_dir.mkdir(parents=True)
    html_path = html_dir / "note-1.html"
    html_path.write_text(
        "<html><body><main class=\"note-body\">\n"
        "<h2>Background</h2>\n"
        "<p>Old background.</p>\n"
        "<h2>Findings</h2>\n"
        "<p>Old findings.</p>\n"
        "</main></body></html>",
        encoding="utf-8",
    )
    write_library({
        "categories": [],
        "notes": [{
            "id": "note-1",
            "title": "Paper",
            "htmlHref": "resources/Paper-html/note-1.html",
            "href": "resources/Papers/paper.pdf",
            "summary": "Old summary",
            "tags": ["old"],
        }],
    }, library_path)
    cache_dir.mkdir()
    (cache_dir / "note-1.json").write_text(json.dumps({
        "pages": [
            {"page": 1, "text": "This paper introduces retrieval augmented notes and local writing agents."},
            {"page": 2, "text": "The experiments compare annotation workflows and note quality."},
        ],
    }), encoding="utf-8")
    registry = create_paper_notes_registry(library_path=library_path, html_dir=html_dir, paper_text_cache_dir=cache_dir)
    return registry, library_path, html_path


def test_search_library_returns_matching_notes(tmp_path):
    library_path = tmp_path / "notes.json"
    write_library({
        "categories": [],
        "notes": [
            {
                "id": "note-1",
                "title": "Attention Is All You Need",
                "summary": "Transformer architecture.",
                "tags": ["transformer"],
            },
            {
                "id": "note-2",
                "title": "Diffusion Models",
                "summary": "Image generation.",
                "tags": ["vision"],
            },
        ],
    }, library_path)
    registry = create_paper_notes_registry(library_path=library_path)

    result = registry.dispatch("search_library", {"query": "attention", "limit": 5})
    payload = json.loads(result.content)

    assert result.is_error is False
    assert payload["count"] == 1
    assert payload["notes"][0]["id"] == "note-1"
    assert "score" not in payload["notes"][0]


def test_search_library_lists_notes_for_empty_or_wildcard_query(tmp_path):
    library_path = tmp_path / "notes.json"
    write_library({
        "categories": [],
        "notes": [
            {"id": "note-1", "title": "Attention Is All You Need", "date": "2017-06-12"},
            {"id": "note-2", "title": "DeepSeek V4", "date": "2026-04-26"},
        ],
    }, library_path)
    registry = create_paper_notes_registry(library_path=library_path)

    empty = json.loads(registry.dispatch("paper_notes_search", {"query": "", "limit": 10}).content)
    wildcard = json.loads(registry.dispatch("paper_notes_search", {"query": "*", "limit": 10}).content)

    assert empty["mode"] == "list"
    assert empty["total"] == 2
    assert empty["count"] == 2
    assert empty["notes"][0]["id"] == "note-2"
    assert wildcard["mode"] == "list"
    assert wildcard["total"] == 2


def test_search_tools_describe_multilingual_keyword_rewriting(tmp_path):
    registry = create_paper_notes_registry(library_path=tmp_path / "notes.json")

    internal = registry.get("search_library")
    facade = registry.get("paper_notes_search")

    assert internal is not None
    assert facade is not None
    assert "English-first paper keywords" in internal.description
    assert "English-first paper keywords" in facade.description
    assert "original-language terms" in internal.parameters["properties"]["query"]["description"]
    assert "original-language terms" in facade.parameters["properties"]["query"]["description"]


def test_get_note_returns_sanitized_note(tmp_path):
    library_path = tmp_path / "notes.json"
    write_library({
        "notes": [{
            "id": "note-1",
            "title": "Paper",
            "summary": "A useful paper.",
            "pdfS3Key": "legacy",
            "pdfStorageKey": "local-key",
        }],
    }, library_path)
    registry = create_paper_notes_registry(library_path=library_path)

    result = registry.dispatch("get_note", {"note_id": "note-1"})
    payload = json.loads(result.content)

    assert result.is_error is False
    assert payload["note"]["title"] == "Paper"
    assert payload["note"]["pdfStorageKey"] == "local-key"
    assert "pdfS3Key" not in payload["note"]


def test_read_annotations_returns_note_annotations(tmp_path):
    annotations_dir = tmp_path / "annotations"
    write_annotations("note-1", [{"id": "a1", "page": 2, "comment": "Important"}], annotations_dir)
    registry = create_paper_notes_registry(annotations_dir=annotations_dir)

    result = registry.dispatch("read_annotations", {"note_id": "note-1"})
    payload = json.loads(result.content)

    assert result.is_error is False
    assert payload == {
        "note_id": "note-1",
        "annotations": [{"id": "a1", "page": 2, "comment": "Important"}],
    }


def test_missing_note_is_reported_as_tool_error(tmp_path):
    library_path = tmp_path / "notes.json"
    write_library({"notes": []}, library_path)
    registry = create_paper_notes_registry(library_path=library_path)

    result = registry.dispatch("get_note", {"note_id": "missing"})

    assert result.is_error is True
    assert json.loads(result.content)["error"] == "Note not found: missing"


def test_paper_notes_registry_can_be_used_by_executor(tmp_path):
    library_path = tmp_path / "notes.json"
    write_library({"notes": [{"id": "note-1", "title": "Graph RAG", "summary": "Retrieval"}]}, library_path)
    registry = create_paper_notes_registry(library_path=library_path)
    executor = ToolExecutorAdapter(registry)

    result = executor.execute(ToolCall(id="call_1", name="search_library", arguments='{"query": "rag"}'))

    assert result.is_error is False
    assert json.loads(result.content)["notes"][0]["id"] == "note-1"


def test_read_note_html_and_list_sections_use_note_body(tmp_path):
    registry, _, _ = _paper_note_fixture(tmp_path)

    html_result = registry.dispatch("read_note_html", {"note_id": "note-1"})
    sections_result = registry.dispatch("list_note_sections", {"note_id": "note-1"})

    assert html_result.is_error is False
    html_payload = json.loads(html_result.content)
    assert html_payload["mode"] == "body"
    assert "<main" not in html_payload["html"]
    assert "Old background" in html_payload["html"]
    assert json.loads(sections_result.content)["sections"] == [
        {"level": 2, "id": "", "heading": "Background"},
        {"level": 2, "id": "", "heading": "Findings"},
    ]


def test_paper_text_search_read_and_build_context_use_cache(tmp_path):
    registry, _, _ = _paper_note_fixture(tmp_path)

    search = registry.dispatch("search_paper_text", {"note_id": "note-1", "query": "annotation", "limit": 3})
    read = registry.dispatch("read_paper_text", {"note_id": "note-1", "page_start": 2, "page_end": 2})
    context = registry.dispatch("build_note_context", {"note_id": "note-1", "query": "retrieval"})

    assert search.is_error is False
    assert json.loads(search.content)["matches"][0]["page"] == 2
    assert read.is_error is False
    assert "annotation workflows" in json.loads(read.content)["text"]
    assert context.is_error is False
    context_payload = json.loads(context.content)
    assert context_payload["note"]["id"] == "note-1"
    assert context_payload["sections"][0]["heading"] == "Background"
    assert context_payload["paper_matches"][0]["page"] == 1


def test_paper_notes_facade_tools_route_to_internal_capabilities(tmp_path):
    registry, _, html_path = _paper_note_fixture(tmp_path)

    search = registry.dispatch("paper_notes_search", {"query": "paper", "limit": 3})
    context = registry.dispatch("paper_notes_context", {"note_id": "note-1", "query": "retrieval", "include_html": True})
    paper = registry.dispatch("paper_notes_read_paper", {"note_id": "note-1", "action": "search_text", "query": "annotation"})
    review = registry.dispatch("paper_notes_review", {"note_id": "note-1", "action": "validate_html"})
    edit = registry.dispatch("paper_notes_edit", {
        "note_id": "note-1",
        "action": "append_section",
        "heading": "Agent Notes",
        "html": "<p>Facade write.</p>",
    })

    assert json.loads(search.content)["count"] == 1
    context_payload = json.loads(context.content)
    assert context_payload["note"]["id"] == "note-1"
    assert "Old background" in context_payload["html"]["html"]
    assert json.loads(paper.content)["matches"][0]["page"] == 2
    assert json.loads(review.content)["valid"] is True
    edit_payload = json.loads(edit.content)
    assert edit_payload["success"] is True
    assert edit_payload["validation"]["valid"] is True
    assert "Facade write" in html_path.read_text(encoding="utf-8")


def test_validate_and_preview_note_html_do_not_write(tmp_path):
    registry, _, html_path = _paper_note_fixture(tmp_path)
    before = html_path.read_text(encoding="utf-8")

    validation = registry.dispatch("validate_note_html", {"note_id": "note-1"})
    preview = registry.dispatch("preview_note_diff", {
        "note_id": "note-1",
        "heading": "Takeaways",
        "html": "<p>New preview text.</p>",
    })

    assert validation.is_error is False
    assert json.loads(validation.content)["valid"] is True
    assert preview.is_error is False
    preview_payload = json.loads(preview.content)
    assert preview_payload["changed"] is True
    assert preview_payload["added_headings"] == ["Takeaways"]
    assert html_path.read_text(encoding="utf-8") == before


def test_write_note_from_paper_image_analyzes_previews_writes_and_validates(tmp_path):
    _, library_path, html_path = _paper_note_fixture(tmp_path)
    analyzer_calls = []

    def fake_analyzer(args):
        analyzer_calls.append(args)
        return {
            "success": True,
            "artifact": {"id": args["artifact_id"]},
            "analysis": (
                "```html\n"
                "<p>The chart shows <strong>higher retrieval accuracy</strong>.</p>"
                "<script>alert(1)</script>\n"
                "```"
            ),
        }

    registry = create_paper_notes_registry(
        library_path=library_path,
        html_dir=html_path.parent,
        paper_image_analyzer=fake_analyzer,
    )

    result = registry.dispatch("write_note_from_paper_image", {
        "note_id": "note-1",
        "artifact_id": "img-test",
        "heading": "Figure Notes",
        "question": "Summarize the evidence for the results section.",
    })
    payload = json.loads(result.content)
    saved_html = html_path.read_text(encoding="utf-8")

    assert result.is_error is False
    assert payload["success"] is True
    assert payload["changed"] is True
    assert payload["preview"]["changed"] is True
    assert payload["validation"]["valid"] is True
    assert analyzer_calls[0]["artifact_id"] == "img-test"
    assert "safe HTML" in analyzer_calls[0]["question"]
    assert "Summarize the evidence" in analyzer_calls[0]["question"]
    assert '<h2 id="figure-notes">Figure Notes</h2>' in saved_html
    assert "<script" not in saved_html
    assert "higher retrieval accuracy" in saved_html


def test_validate_html_allows_template_scripts_but_rejects_body_scripts(tmp_path):
    registry, _, html_path = _paper_note_fixture(tmp_path)
    html_path.write_text(
        "<!doctype html><html><head>"
        "<script src=\"/scripts/shared/theme.js\"></script>"
        "</head><body><main class=\"note-body\">"
        "<h2>1. Introduction</h2>"
        "<p>Safe body.</p>"
        "</main>"
        "<script src=\"/scripts/note/app.js\"></script>"
        "</body></html>",
        encoding="utf-8",
    )

    safe_result = registry.dispatch("paper_notes_review", {"note_id": "note-1", "action": "validate_html"})
    safe_payload = json.loads(safe_result.content)

    html_path.write_text(
        html_path.read_text(encoding="utf-8").replace("<p>Safe body.</p>", "<script>alert(1)</script>"),
        encoding="utf-8",
    )
    unsafe_result = registry.dispatch("paper_notes_review", {"note_id": "note-1", "action": "validate_html"})
    unsafe_payload = json.loads(unsafe_result.content)

    assert safe_payload["valid"] is True
    assert safe_payload["issues"] == []
    assert unsafe_payload["valid"] is False
    assert unsafe_payload["issues"][0]["code"] == "script_tag"


def test_write_note_section_sanitizes_html_and_appends(tmp_path):
    registry, _, html_path = _paper_note_fixture(tmp_path)

    result = registry.dispatch("write_note_section", {
        "note_id": "note-1",
        "heading": "Takeaways",
        "html": (
            "<script>alert(1)</script>"
            "<p onclick=\"bad()\">Keep this</p>"
            "<a href=\"javascript:alert(1)\">unsafe link</a>"
            "<a href=\"https://example.com\" title=\"source\">safe link</a>"
        ),
    })
    payload = json.loads(result.content)
    saved_html = html_path.read_text(encoding="utf-8")

    assert result.is_error is False
    assert payload["success"] is True
    assert payload["changed"] is True
    assert '<h2 id="takeaways">Takeaways</h2>' in saved_html
    assert "<script" not in saved_html
    assert "onclick" not in saved_html
    assert "javascript:" not in saved_html
    assert '<a href="https://example.com" title="source">safe link</a>' in saved_html


def test_replace_note_section_preserves_html_document(tmp_path):
    registry, _, html_path = _paper_note_fixture(tmp_path)

    result = registry.dispatch("replace_note_section", {
        "note_id": "note-1",
        "heading": "Background",
        "html": "<p>New background.</p>",
    })
    saved_html = html_path.read_text(encoding="utf-8")

    assert result.is_error is False
    assert "<html><body><main class=\"note-body\">" in saved_html
    assert '<h2 id="background">Background</h2>\n<p>New background.</p>' in saved_html
    assert "Old background" not in saved_html
    assert "<h2>Findings</h2>" in saved_html


def test_update_note_metadata_allows_only_known_fields(tmp_path):
    registry, library_path, _ = _paper_note_fixture(tmp_path)

    rejected = registry.dispatch("update_note_metadata", {
        "note_id": "note-1",
        "title": "Renames are not allowed",
    })
    result = registry.dispatch("update_note_metadata", {
        "note_id": "note-1",
        "summary": "New summary",
        "tags": "agent, notes",
        "venue": "ICLR",
        "date": "2026",
    })
    library = json.loads(library_path.read_text(encoding="utf-8"))
    note = library["notes"][0]

    assert rejected.is_error is True
    assert json.loads(rejected.content)["code"] == "unknown_metadata_fields"
    assert result.is_error is False
    assert note["summary"] == "New summary"
    assert note["tags"] == ["agent", "notes"]
    assert note["venue"] == "ICLR"
    assert note["date"] == "2026"


def test_paper_notes_edit_update_metadata_ignores_facade_action(tmp_path):
    registry, library_path, _ = _paper_note_fixture(tmp_path)

    result = registry.dispatch("paper_notes_edit", {
        "action": "update_metadata",
        "note_id": "note-1",
        "summary": "Facade summary",
        "tags": ["facade", "metadata"],
    })
    library = json.loads(library_path.read_text(encoding="utf-8"))
    note = library["notes"][0]

    assert result.is_error is False
    assert note["summary"] == "Facade summary"
    assert note["tags"] == ["facade", "metadata"]


def test_update_note_metadata_accepts_collection_name(tmp_path):
    library_path = tmp_path / "notes.json"
    write_library({
        "categories": [
            {"id": "models", "name": "Models", "parentId": None, "order": 2},
            {"id": "reasoning", "name": "Reasoning", "parentId": "models", "order": 0},
        ],
        "notes": [{"id": "note-1", "title": "Paper", "categoryId": "uncategorized"}],
    }, library_path)
    registry = create_paper_notes_registry(library_path=library_path)

    result = registry.dispatch("paper_notes_edit", {
        "action": "update_metadata",
        "note_id": "note-1",
        "collection": "Models / Reasoning",
    })
    payload = json.loads(result.content)
    library = json.loads(library_path.read_text(encoding="utf-8"))
    note = library["notes"][0]

    assert result.is_error is False
    assert note["categoryId"] == "reasoning"
    assert payload["after"]["collectionName"] == "Reasoning"
    assert payload["after"]["collectionPath"] == "Models / Reasoning"


def test_paper_notes_context_includes_collection_metadata(tmp_path):
    library_path = tmp_path / "notes.json"
    write_library({
        "categories": [
            {"id": "models", "name": "Models", "parentId": None, "order": 2},
            {"id": "reasoning", "name": "Reasoning", "parentId": "models", "order": 0},
        ],
        "notes": [{"id": "note-1", "title": "Paper", "categoryId": "reasoning"}],
    }, library_path)
    registry = create_paper_notes_registry(library_path=library_path)

    result = registry.dispatch("paper_notes_context", {"note_id": "note-1"})
    payload = json.loads(result.content)

    assert result.is_error is False
    assert payload["note"]["categoryId"] == "reasoning"
    assert payload["note"]["collectionName"] == "Reasoning"
    assert payload["note"]["collectionPath"] == "Models / Reasoning"


def test_paper_notes_edit_deletes_note_section(tmp_path):
    registry, _, html_path = _paper_note_fixture(tmp_path)

    result = registry.dispatch("paper_notes_edit", {
        "action": "delete_section",
        "note_id": "note-1",
        "heading": "Background",
    })
    payload = json.loads(result.content)
    saved_html = html_path.read_text(encoding="utf-8")

    assert result.is_error is False
    assert payload["success"] is True
    assert payload["validation"]["valid"] is True
    assert "Old background" not in saved_html
    assert "<h2>Findings</h2>" in saved_html


def test_paper_notes_edit_inserts_generated_image_into_section(tmp_path):
    registry, library_path, html_path = _paper_note_fixture(tmp_path)
    media_store = MediaStore(tmp_path / ".paper-notes" / "media", project_root=tmp_path)
    image = media_store.create_generated_image(
        base64.b64encode(
            base64.b64decode(
                "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
            )
        ).decode("ascii"),
        session_id="session-1",
    )
    registry = create_paper_notes_registry(library_path=library_path, html_dir=html_path.parent, media_store=media_store)

    result = registry.dispatch("paper_notes_edit", {
        "action": "insert_image",
        "note_id": "note-1",
        "heading": "Findings",
        "artifact_id": image.id,
        "caption": "Generated comparison sketch.",
        "alt": "Comparison sketch",
    })
    payload = json.loads(result.content)
    saved_html = html_path.read_text(encoding="utf-8")

    assert result.is_error is False
    assert payload["success"] is True
    assert payload["validation"]["valid"] is True
    assert '<figure class="note-figure">' in saved_html
    assert f'src="/api/media/{image.id}"' in saved_html
    assert 'alt="Comparison sketch"' in saved_html
    assert "<figcaption>Generated comparison sketch.</figcaption>" in saved_html
    assert saved_html.index("<h2>Findings</h2>") < saved_html.index(f"/api/media/{image.id}")


def test_paper_notes_edit_insert_image_accepts_generated_path_fragment(tmp_path):
    registry, library_path, html_path = _paper_note_fixture(tmp_path)
    media_store = MediaStore(tmp_path / ".paper-notes" / "media", project_root=tmp_path)
    image = media_store.create_generated_image(
        base64.b64encode(
            base64.b64decode(
                "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
            )
        ).decode("ascii"),
        session_id="session-1",
    )
    registry = create_paper_notes_registry(library_path=library_path, html_dir=html_path.parent, media_store=media_store)
    path_fragment = f"session-1/{image.file_name}"

    result = registry.dispatch("paper_notes_edit", {
        "action": "insert_image",
        "note_id": "note-1",
        "heading": "Findings",
        "artifact_id": path_fragment,
        "alt": "Path fragment image",
    })
    payload = json.loads(result.content)
    saved_html = html_path.read_text(encoding="utf-8")

    assert result.is_error is False
    assert payload["success"] is True
    assert payload["artifact_id"] == image.id
    assert f'src="/api/media/{image.id}"' in saved_html
    assert path_fragment not in saved_html


def test_paper_notes_edit_rewrites_local_media_img_paths_in_section_writes(tmp_path):
    registry, library_path, html_path = _paper_note_fixture(tmp_path)
    media_store = MediaStore(tmp_path / ".paper-notes" / "media", project_root=tmp_path)
    image = media_store.create_generated_image(
        base64.b64encode(
            base64.b64decode(
                "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
            )
        ).decode("ascii"),
        session_id="session-1",
    )
    registry = create_paper_notes_registry(library_path=library_path, html_dir=html_path.parent, media_store=media_store)

    result = registry.dispatch("paper_notes_edit", {
        "action": "write_section",
        "note_id": "note-1",
        "heading": "Findings",
        "position": "replace_heading",
        "html": f'<h2>Findings</h2><p><img src="{image.path}" alt="Generated figure"></p>',
    })
    payload = json.loads(result.content)
    saved_html = html_path.read_text(encoding="utf-8")

    assert result.is_error is False
    assert payload["success"] is True
    assert payload["validation"]["valid"] is True
    assert f'src="/api/media/{image.id}"' in saved_html
    assert image.path not in saved_html
    assert 'alt="Generated figure"' in saved_html


def test_paper_notes_edit_rewrites_local_media_img_paths_in_append_section(tmp_path):
    registry, library_path, html_path = _paper_note_fixture(tmp_path)
    media_store = MediaStore(tmp_path / ".paper-notes" / "media", project_root=tmp_path)
    image = media_store.create_generated_image(
        base64.b64encode(
            base64.b64decode(
                "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
            )
        ).decode("ascii"),
        session_id="session-1",
    )
    registry = create_paper_notes_registry(library_path=library_path, html_dir=html_path.parent, media_store=media_store)

    result = registry.dispatch("paper_notes_edit", {
        "action": "append_section",
        "note_id": "note-1",
        "heading": "Findings",
        "html": f'<p><img src="{image.path}" alt="Inserted image" /></p>',
    })
    payload = json.loads(result.content)
    saved_html = html_path.read_text(encoding="utf-8")

    assert result.is_error is False
    assert payload["success"] is True
    assert payload["changed"] is True
    assert f'src="/api/media/{image.id}"' in saved_html
    assert image.path not in saved_html
    assert 'alt="Inserted image"' in saved_html


def test_paper_notes_edit_append_existing_heading_does_not_duplicate_heading(tmp_path):
    registry, _, html_path = _paper_note_fixture(tmp_path)

    result = registry.dispatch("paper_notes_edit", {
        "action": "append_section",
        "note_id": "note-1",
        "heading": "Findings",
        "html": "<p>Extra finding.</p>",
    })
    payload = json.loads(result.content)
    saved_html = html_path.read_text(encoding="utf-8")

    assert result.is_error is False
    assert payload["success"] is True
    assert saved_html.count("<h2>Findings</h2>") == 1
    assert "Old findings." in saved_html
    assert "Extra finding." in saved_html


def test_internal_write_note_section_rewrites_local_media_img_paths(tmp_path):
    registry, library_path, html_path = _paper_note_fixture(tmp_path)
    media_store = MediaStore(tmp_path / ".paper-notes" / "media", project_root=tmp_path)
    image = media_store.create_generated_image(
        base64.b64encode(
            base64.b64decode(
                "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
            )
        ).decode("ascii"),
        session_id="session-1",
    )
    registry = create_paper_notes_registry(library_path=library_path, html_dir=html_path.parent, media_store=media_store)

    result = registry.dispatch("write_note_section", {
        "note_id": "note-1",
        "heading": "Findings",
        "position": "replace_heading",
        "html": f'<h2>Findings</h2><p><img src="{image.path}" alt="Internal figure"></p>',
    })
    payload = json.loads(result.content)
    saved_html = html_path.read_text(encoding="utf-8")

    assert result.is_error is False
    assert payload["success"] is True
    assert f'src="/api/media/{image.id}"' in saved_html
    assert image.path not in saved_html


def test_paper_notes_edit_rewrites_file_uri_media_img_paths(tmp_path):
    registry, library_path, html_path = _paper_note_fixture(tmp_path)
    media_store = MediaStore(tmp_path / ".paper-notes" / "media", project_root=tmp_path)
    image = media_store.create_generated_image(
        base64.b64encode(
            base64.b64decode(
                "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
            )
        ).decode("ascii"),
        session_id="session-1",
    )
    registry = create_paper_notes_registry(library_path=library_path, html_dir=html_path.parent, media_store=media_store)

    preview = registry.dispatch("paper_notes_review", {
        "action": "preview_note_diff",
        "note_id": "note-1",
        "heading": "Findings",
        "position": "replace_heading",
        "html": f'<h2>Findings</h2><p><img src="{image.filesystem_path.as_uri()}" alt="File URI figure"></p>',
    })
    preview_payload = json.loads(preview.content)
    result = registry.dispatch("paper_notes_edit", {
        "action": "replace_section",
        "note_id": "note-1",
        "heading": "Findings",
        "html": f'<h2>Findings</h2><p><img src="{image.filesystem_path.as_uri()}" alt="File URI figure"></p>',
    })
    payload = json.loads(result.content)
    saved_html = html_path.read_text(encoding="utf-8")

    assert preview.is_error is False
    assert preview_payload["success"] is True
    assert result.is_error is False
    assert payload["success"] is True
    assert payload["validation"]["valid"] is True
    assert f'src="/api/media/{image.id}"' in saved_html
    assert "file://" not in saved_html
    assert 'alt="File URI figure"' in saved_html


def test_paper_notes_edit_rejects_unresolved_local_image_paths(tmp_path):
    registry, _, html_path = _paper_note_fixture(tmp_path)

    result = registry.dispatch("paper_notes_edit", {
        "action": "replace_section",
        "note_id": "note-1",
        "heading": "Findings",
        "html": '<h2>Findings</h2><img src="/tmp/missing-generated-image.png" alt="Missing figure">',
    })
    payload = json.loads(result.content)
    saved_html = html_path.read_text(encoding="utf-8")

    assert result.is_error is True
    assert payload["success"] is False
    assert payload["code"] == "media_store_unavailable"
    assert "missing-generated-image" not in saved_html


def test_paper_notes_edit_manages_annotations(tmp_path):
    annotations_dir = tmp_path / "annotations"
    write_annotations("note-1", [{
        "id": "a1",
        "page": 2,
        "x": 10,
        "y": 20,
        "w": 30,
        "h": 40,
        "comment": "old",
        "color": "yellow",
    }], annotations_dir)
    registry = create_paper_notes_registry(annotations_dir=annotations_dir)

    created = registry.dispatch("paper_notes_edit", {
        "action": "create_annotation",
        "note_id": "note-1",
        "annotation_id": "a2",
        "annotation_type": "highlight",
        "page": 3,
        "x": 0.1,
        "y": 0.2,
        "w": 0.3,
        "h": 0.04,
        "comment": "created",
        "quote": "quoted text",
        "color": "purple",
    })
    result = registry.dispatch("paper_notes_edit", {
        "action": "update_annotation",
        "note_id": "note-1",
        "annotation_id": "a1",
        "comment": "new comment",
        "color": "green",
    })
    deleted = registry.dispatch("paper_notes_edit", {
        "action": "delete_annotation",
        "note_id": "note-1",
        "annotation_id": "a2",
    })
    saved_annotations = json.loads((annotations_dir / "note-1.json").read_text(encoding="utf-8"))["annotations"]
    saved = next(annotation for annotation in saved_annotations if annotation["id"] == "a1")

    assert created.is_error is False
    assert result.is_error is False
    assert deleted.is_error is False
    assert all(annotation["id"] != "a2" for annotation in saved_annotations)
    assert saved["comment"] == "new comment"
    assert "text" not in saved
    assert saved["color"] == "green"
    assert {key: saved[key] for key in ("page", "x", "y", "w", "h")} == {
        "page": 2,
        "x": 10,
        "y": 20,
        "w": 30,
        "h": 40,
    }


def test_paper_notes_edit_creates_annotation_by_locating_pdf_quote(tmp_path):
    import pymupdf

    library_path = tmp_path / "notes.json"
    papers_dir = tmp_path / "Papers"
    annotations_dir = tmp_path / "annotations"
    papers_dir.mkdir()
    pdf_path = papers_dir / "paper.pdf"
    document = pymupdf.open()
    page = document.new_page(width=300, height=200)
    page.insert_text((40, 80), "Locate this important phrase in the paper.")
    document.save(str(pdf_path))
    document.close()
    write_library({
        "notes": [{
            "id": "note-1",
            "title": "Paper",
            "href": "resources/Papers/paper.pdf",
        }],
    }, library_path)
    registry = create_paper_notes_registry(
        library_path=library_path,
        papers_dir=papers_dir,
        annotations_dir=annotations_dir,
    )

    result = registry.dispatch("paper_notes_edit", {
        "action": "create_annotation",
        "note_id": "note-1",
        "annotation_id": "located-annotation",
        "annotation_type": "highlight",
        "quote": "important phrase",
        "comment": "Found by quote.",
        "color": "yellow",
    })
    payload = json.loads(result.content)
    saved = json.loads((annotations_dir / "note-1.json").read_text(encoding="utf-8"))["annotations"][0]

    assert result.is_error is False
    assert payload["success"] is True
    assert saved["id"] == "located-annotation"
    assert saved["page"] == 1
    assert saved["quote"] == "important phrase"
    assert saved["comment"] == "Found by quote."
    assert saved["rects"]
    assert 0 <= saved["x"] <= 1
    assert 0 <= saved["y"] <= 1
    assert saved["w"] > 0
    assert saved["h"] > 0


def test_paper_notes_edit_locates_annotation_across_spacing_and_line_breaks(tmp_path):
    import pymupdf

    library_path = tmp_path / "notes.json"
    papers_dir = tmp_path / "Papers"
    annotations_dir = tmp_path / "annotations"
    papers_dir.mkdir()
    pdf_path = papers_dir / "paper.pdf"
    document = pymupdf.open()
    page = document.new_page(width=500, height=240)
    page.insert_text((40, 80), "Compressed Sparse Attention (CSA)")
    page.insert_text((40, 100), "and Heavily Compressed Attention (HCA) to improve long-context efficiency")
    document.save(str(pdf_path))
    document.close()
    write_library({
        "notes": [{
            "id": "note-1",
            "title": "Paper",
            "href": "resources/Papers/paper.pdf",
        }],
    }, library_path)
    registry = create_paper_notes_registry(
        library_path=library_path,
        papers_dir=papers_dir,
        annotations_dir=annotations_dir,
    )

    result = registry.dispatch("paper_notes_edit", {
        "action": "create_annotation",
        "note_id": "note-1",
        "annotation_id": "flexible-annotation",
        "annotation_type": "underline",
        "quote": "Compressed Sparse Attention (CSA)and Heavily Compressed Attention (HCA) to improve long-context efficiency",
        "comment": "Found despite missing space.",
        "color": "yellow",
        "page": 1,
    })
    payload = json.loads(result.content)
    saved = json.loads((annotations_dir / "note-1.json").read_text(encoding="utf-8"))["annotations"][0]

    assert result.is_error is False
    assert payload["success"] is True
    assert saved["id"] == "flexible-annotation"
    assert saved["page"] == 1
    assert len(saved["rects"]) == 2
    assert saved["quote"] == "Compressed Sparse Attention (CSA) and Heavily Compressed Attention (HCA) to improve long-context efficiency"
    assert saved["comment"] == "Found despite missing space."


def test_paper_note_write_tools_are_marked_mutating(tmp_path):
    registry, _, _ = _paper_note_fixture(tmp_path)

    assert registry.get("paper_notes_search").read_only is True
    assert registry.get("paper_notes_edit").mutating is True
    assert registry.get("paper_notes_edit").risk == "write"
    assert registry.get("search_library").read_only is True
    assert registry.get("write_note_from_paper_image").mutating is True
    assert registry.get("write_note_from_paper_image").risk == "write"
    assert registry.get("write_note_section").mutating is True
    assert registry.get("write_note_section").risk == "write"


def test_render_paper_page_and_extract_images_from_pdf(tmp_path):
    import pymupdf

    library_path = tmp_path / "notes.json"
    papers_dir = tmp_path / "Papers"
    page_cache_dir = tmp_path / "paper-pages"
    image_cache_dir = tmp_path / "paper-images"
    media_store = MediaStore(tmp_path / ".paper-notes" / "media")
    papers_dir.mkdir()
    pdf_path = papers_dir / "paper.pdf"
    png_bytes = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
    )

    document = pymupdf.open()
    page = document.new_page(width=200, height=200)
    page.insert_text((32, 40), "A page with an embedded figure.")
    page.insert_image(pymupdf.Rect(32, 64, 96, 128), stream=png_bytes)
    document.save(str(pdf_path))
    document.close()
    write_library({
        "notes": [{
            "id": "note-1",
            "title": "Paper",
            "href": "resources/Papers/paper.pdf",
        }],
    }, library_path)
    registry = create_paper_notes_registry(
        library_path=library_path,
        papers_dir=papers_dir,
        paper_page_cache_dir=page_cache_dir,
        paper_image_cache_dir=image_cache_dir,
        media_store=media_store,
    )

    rendered = registry.dispatch("render_paper_page", {"note_id": "note-1", "page": 1, "scale": 1.5})
    extracted = registry.dispatch("extract_paper_images", {"note_id": "note-1"})
    rendered_payload = json.loads(rendered.content)
    extracted_payload = json.loads(extracted.content)

    assert rendered.is_error is False
    assert rendered_payload["success"] is True
    assert rendered_payload["width"] > 0
    assert rendered_payload["height"] > 0
    assert rendered_payload["relative_path"].endswith(".png")
    assert rendered_payload["artifact"]["source"] == "pdf_page"
    assert rendered_payload["artifact_id"] == rendered_payload["artifact"]["id"]
    assert (tmp_path / rendered_payload["relative_path"]).exists() or rendered_payload["image_path"].endswith(".png")
    assert extracted.is_error is False
    assert extracted_payload["success"] is True
    assert extracted_payload["count"] >= 1
    assert extracted_payload["images"][0]["page"] == 1
    assert extracted_payload["images"][0]["relative_path"]
    assert extracted_payload["images"][0]["artifact"]["source"] == "pdf_image"
