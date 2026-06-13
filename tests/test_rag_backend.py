from __future__ import annotations

import base64

from fastapi.testclient import TestClient

from rag.config import DEFAULT_IMAGE_COLLECTION, DEFAULT_TEXT_COLLECTION, safe_index_key
from rag.service import PaperRAGService, RAGServiceError
from tools import create_tools
from tools.paper_notes.impl import facade
import library.store as library_store
from library.store import write_library
from ui.backend.server import create_app


def client() -> TestClient:
    return TestClient(create_app())


def test_rag_status_reports_missing_indexes_without_heavy_dependencies():
    index_key = "unit-test-rag-missing-index"

    payload = PaperRAGService().status(index_key=index_key)

    assert payload["success"] is True
    assert payload["indexKey"] == safe_index_key(index_key)
    assert payload["ready"] is False
    assert payload["indexes"]["qdrant"]["exists"] is False
    assert payload["indexes"]["bm25"]["exists"] is False
    assert payload["indexes"]["qdrant"]["textCollection"] != DEFAULT_TEXT_COLLECTION
    assert payload["indexes"]["qdrant"]["imageCollection"] != DEFAULT_IMAGE_COLLECTION


def test_rag_service_query_requires_query_text():
    service = PaperRAGService()

    try:
        service.query(query="")
    except RAGServiceError as error:
        assert error.code == "query_required"
    else:
        raise AssertionError("expected query_required")


def test_rag_status_endpoint_accepts_camel_case_query_params():
    response = client().get("/api/rag/status", params={"indexKey": "Unit Test Index"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["indexKey"] == "unit-test-index"
    assert payload["ready"] is False
    assert payload["indexes"]["qdrant"]["textCollection"] == "paper_notes_unit_test_index"


def test_rag_rejects_pdf_paths_outside_project():
    service = PaperRAGService()

    try:
        service.resolve_target(pdf_path="/tmp/outside-paper-notes.pdf")
    except RAGServiceError as error:
        assert error.code == "invalid_pdf_path"
    else:
        raise AssertionError("expected invalid_pdf_path")


def test_search_paper_rag_tool_is_registered():
    tool_names = {tool.name for tool in create_tools()}

    assert "search_paper_rag" in tool_names


def test_import_pdf_triggers_rag_index(monkeypatch, tmp_path):
    import pymupdf

    papers_dir = tmp_path / "Papers"
    html_dir = tmp_path / "Paper-html"
    notes_path = tmp_path / "notes.json"
    monkeypatch.setattr(library_store, "PAPERS_DIR", papers_dir)
    monkeypatch.setattr(library_store, "HTML_DIR", html_dir)
    monkeypatch.setattr(library_store, "NOTES_PATH", notes_path)
    calls = []

    def fake_index_imported_pdf(*, note, pdf_path):
        calls.append({"note_id": note["id"], "pdf_path": pdf_path})
        return {"success": True, "ready": True, "indexKey": note["id"], "built": {"qdrant": True, "bm25": True}}

    monkeypatch.setattr(library_store, "_index_imported_pdf", fake_index_imported_pdf)

    document = pymupdf.open()
    document.new_page().insert_text((72, 72), "Semantic retrieval should be indexed after upload.")
    pdf_data = document.tobytes()
    document.close()

    note = library_store.import_pdf(
        {
            "fileName": "RAG Paper.pdf",
            "dataBase64": base64.b64encode(pdf_data).decode("ascii"),
        }
    )

    assert note["ragIndex"]["success"] is True
    assert note["ragIndex"]["built"] == {"qdrant": True, "bm25": True}
    assert calls == [{"note_id": note["id"], "pdf_path": papers_dir / "RAG Paper.pdf"}]


def test_search_paper_rag_facade_routes_to_service(monkeypatch, tmp_path):
    library_path = tmp_path / "notes.json"
    write_library(
        {
            "notes": [
                {
                    "id": "note-1",
                    "title": "Paper",
                    "href": "resources/Papers/paper.pdf",
                }
            ]
        },
        library_path,
    )
    calls = []

    class FakeRAGService:
        def query(self, **kwargs):
            calls.append(kwargs)
            return {
                "success": True,
                "query": kwargs["query"],
                "noteId": kwargs["note_id"],
                "results": [{"index": 1, "text": "retrieved passage"}],
                "resultCount": 1,
            }

    monkeypatch.setattr(facade, "get_rag_service", lambda: FakeRAGService())

    payload = facade.search_paper_rag(
        {
            "note_id": "note-1",
            "query": "main contribution",
            "similarity_top_k": 8,
        },
        library_path=library_path,
    )

    assert payload["success"] is True
    assert payload["results"][0]["text"] == "retrieved passage"
    assert calls == [
        {
            "query": "main contribution",
            "note_id": "note-1",
            "similarity_top_k": 8,
            "image_similarity_top_k": 3,
            "bm25_similarity_top_k": 5,
            "embedding_provider": "ollama",
            "embedding_model": None,
            "library_path": library_path,
        }
    ]
