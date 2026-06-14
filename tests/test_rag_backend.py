from __future__ import annotations

import base64
import json

from fastapi.testclient import TestClient

from app_config import load_app_config
from app_config.config import DEFAULT_IMAGE_COLLECTION, DEFAULT_TEXT_COLLECTION, safe_index_key
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


def test_config_json_controls_rag_and_import_defaults(monkeypatch, tmp_path):
    config_path = tmp_path / "config.json"
    rag_root = tmp_path / "rag-state"
    config_path.write_text(
        json.dumps(
            {
                "rag": {
                    "root_dir": str(rag_root),
                    "index_root": str(rag_root / "custom-indexes"),
                    "image_root": str(rag_root / "custom-images"),
                    "collections": {"text": "custom_text", "image": "custom_image"},
                    "build": {"loader": "llamaparse", "include_images": True, "qdrant": False, "bm25": True},
                    "chunking": {"chunk_size": 512, "chunk_overlap": 64},
                    "embedding": {
                        "provider": "openai",
                        "model": "configured-embedding",
                        "batch_size": 32,
                        "ollama": {"base_url": "http://ollama.test:11434"},
                    },
                    "image_embedding": {"model": "configured-clip"},
                    "retrieval": {
                        "similarity_top_k": 9,
                        "image_similarity_top_k": 4,
                        "bm25_similarity_top_k": 6,
                        "hybrid_weights": [0.8, 0.2],
                    },
                    "llamaparse": {
                        "tier": "cost_effective",
                        "version": "v2",
                        "timeout": 123,
                        "image_categories": ["embedded"],
                    },
                },
                "library": {
                    "import": {
                        "max_pdf_bytes": 1024,
                        "max_html_bytes": 2048,
                        "timeout_seconds": 3,
                        "chunk_size": 4096,
                        "user_agent": "Paper Notes Test",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("PAPER_NOTES_CONFIG", str(config_path))

    rag_config = load_app_config().rag

    assert rag_config.qdrant_storage_path("Paper One") == (rag_root / "custom-indexes" / "paper-one" / "qdrant").resolve()
    assert rag_config.image_output_path("Paper One", loader="pymupdf") == (
        rag_root / "custom-images" / "paper-one" / "pymupdf"
    ).resolve()
    assert rag_config.text_collection_name("Paper One") == "custom_text_paper_one"
    assert rag_config.image_collection_name("Paper One") == "custom_image_paper_one"
    assert rag_config.build.loader == "llamaparse"
    assert rag_config.build.include_images is True
    assert rag_config.build.qdrant is False
    assert rag_config.chunking.chunk_size == 512
    assert rag_config.chunking.chunk_overlap == 64
    assert rag_config.embedding.provider_name() == "openai"
    assert rag_config.embedding.model_for("openai") == "configured-embedding"
    assert rag_config.embedding.batch_size == 32
    assert rag_config.image_embedding.model == "configured-clip"
    assert rag_config.retrieval.similarity_top_k == 9
    assert rag_config.retrieval.image_similarity_top_k == 4
    assert rag_config.retrieval.bm25_similarity_top_k == 6
    assert rag_config.retrieval.hybrid_weights == (0.8, 0.2)
    assert rag_config.llamaparse.tier == "cost_effective"
    assert rag_config.llamaparse.timeout == 123

    assert library_store.max_remote_pdf_bytes() == 1024
    assert library_store.max_remote_html_bytes() == 2048
    assert library_store.remote_fetch_timeout_seconds() == 3
    assert library_store.remote_fetch_chunk_size() == 4096
    assert library_store.remote_fetch_headers()["User-Agent"] == "Paper Notes Test"


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


def test_import_pdf_does_not_trigger_rag_index(monkeypatch, tmp_path):
    import pymupdf

    papers_dir = tmp_path / "Papers"
    html_dir = tmp_path / "Paper-html"
    notes_path = tmp_path / "notes.json"
    monkeypatch.setattr(library_store, "PAPERS_DIR", papers_dir)
    monkeypatch.setattr(library_store, "HTML_DIR", html_dir)
    monkeypatch.setattr(library_store, "NOTES_PATH", notes_path)

    document = pymupdf.open()
    document.new_page().insert_text((72, 72), "Semantic retrieval should wait for Settings RAG indexing.")
    pdf_data = document.tobytes()
    document.close()

    note = library_store.import_pdf(
        {
            "fileName": "RAG Paper.pdf",
            "dataBase64": base64.b64encode(pdf_data).decode("ascii"),
        }
    )

    assert "ragIndex" not in note
    assert (papers_dir / "RAG Paper.pdf").exists()


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


def test_search_paper_rag_facade_uses_configured_rag_defaults(monkeypatch, tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "rag": {
                    "embedding": {"provider": "openai"},
                    "retrieval": {
                        "similarity_top_k": 9,
                        "image_similarity_top_k": 4,
                        "bm25_similarity_top_k": 6,
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("PAPER_NOTES_CONFIG", str(config_path))

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
                "results": [],
                "resultCount": 0,
            }

    monkeypatch.setattr(facade, "get_rag_service", lambda: FakeRAGService())

    payload = facade.search_paper_rag(
        {
            "note_id": "note-1",
            "query": "main contribution",
        },
        library_path=library_path,
    )

    assert payload["success"] is True
    assert calls[0]["similarity_top_k"] == 9
    assert calls[0]["image_similarity_top_k"] == 4
    assert calls[0]["bm25_similarity_top_k"] == 6
    assert calls[0]["embedding_provider"] == "openai"


def test_search_paper_rag_returns_read_paper_fallback_when_not_indexed(monkeypatch, tmp_path):
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

    class FakeRAGService:
        def query(self, **kwargs):
            raise RAGServiceError("RAG indexes are not ready.", code="index_not_ready")

    monkeypatch.setattr(facade, "get_rag_service", lambda: FakeRAGService())

    payload = facade.search_paper_rag(
        {
            "note_id": "note-1",
            "query": "main contribution",
        },
        library_path=library_path,
    )

    assert payload["success"] is False
    assert payload["code"] == "index_not_ready"
    assert payload["fallbackTool"] == "read_paper"
    assert payload["fallbackArguments"] == {
        "action": "search_text",
        "note_id": "note-1",
        "query": "main contribution",
    }
