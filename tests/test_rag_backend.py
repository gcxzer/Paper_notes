from __future__ import annotations

import base64
import json
import threading
import time
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app_config import load_app_config
from app_config.config import DEFAULT_TEXT_COLLECTION, safe_index_key
from rag.embedding_model import get_embedding_model
import rag.image_captioning as image_captioning
from rag.image_captioning import _caption_one_image
from rag import llamaparse_loader
from rag.node_parser import build_image_caption_nodes
from rag.retriever import HybridRetriever
from rag.service import PaperRAGService, RAGServiceError
from tools import ToolContext, create_tools, tool_name
from tools.paper_notes.impl import facade
import ui.backend.rag_api as rag_api
import library.store as library_store
from library.store import write_library
from ui.backend.server import create_app


def client() -> TestClient:
    return TestClient(create_app())


def wait_for(predicate, timeout: float = 2.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return bool(predicate())


def test_rag_status_reports_missing_indexes_without_heavy_dependencies():
    index_key = "unit-test-rag-missing-index"

    payload = PaperRAGService().status(index_key=index_key)

    assert payload["success"] is True
    assert payload["indexKey"] == safe_index_key(index_key)
    assert payload["ready"] is False
    assert payload["indexes"]["qdrant"]["exists"] is False
    assert payload["indexes"]["bm25"]["exists"] is False
    assert payload["indexes"]["qdrant"]["textCollection"] != DEFAULT_TEXT_COLLECTION


def test_rag_status_resolves_note_id_index_key(tmp_path):
    library_path = tmp_path / "notes.json"
    library_path.write_text(
        json.dumps({
            "notes": [
                {
                    "id": "pdf-2302-04761v1-mqf55hed",
                    "title": "Toolformer",
                    "href": "resources/Papers/2302.04761v1.pdf",
                }
            ]
        }),
        encoding="utf-8",
    )

    payload = PaperRAGService().status(note_id="pdf-2302-04761v1-mqf55hed", library_path=library_path)

    assert payload["indexKey"] == "pdf-2302-04761v1-mqf55hed"
    assert payload["indexes"]["qdrant"]["textCollection"] == "paper_notes_pdf_2302_04761v1_mqf55hed"


def test_rag_service_query_requires_query_text():
    service = PaperRAGService()

    try:
        service.query(query="")
    except RAGServiceError as error:
        assert error.code == "query_required"
    else:
        raise AssertionError("expected query_required")


def test_openai_compatible_embedding_accepts_custom_model_name(monkeypatch, tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "rag": {
                    "embedding": {
                        "provider": "openai",
                        "openai": {
                            "model": "Qwen/Qwen3-Embedding-8B",
                            "api_base": "https://modelscope.test/v1",
                            "api_key_env": "UNIT_TEST_MODELSCOPE_TOKEN",
                        },
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("PAPER_NOTES_CONFIG", str(config_path))
    monkeypatch.setenv("MODELSCOPE_BASEURL", "https://modelscope.test/v1")
    monkeypatch.setenv("UNIT_TEST_MODELSCOPE_TOKEN", "test-token")

    embed_model = get_embedding_model()

    assert embed_model.model_name == "Qwen/Qwen3-Embedding-8B"
    assert embed_model.api_base == "https://modelscope.test/v1"


def test_rag_status_endpoint_accepts_camel_case_query_params():
    response = client().get("/api/rag/status", params={"indexKey": "Unit Test Index"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["indexKey"] == "unit-test-index"
    assert payload["ready"] is False
    assert payload["indexes"]["qdrant"]["textCollection"] == "paper_notes_unit_test_index"


def test_rag_index_stream_emits_progress_and_final(monkeypatch):
    class FakeRAGService:
        def build_index(self, **kwargs):
            kwargs["progress_callback"]({
                "stage": "captioning",
                "message": "Captioning image 1 of 2.",
                "percent": 35,
                "current": 1,
                "total": 2,
            })
            return {
                "success": True,
                "ready": True,
                "noteId": kwargs["note_id"],
                "indexes": {"qdrant": {"exists": True}, "bm25": {"exists": True}},
            }

    monkeypatch.setattr(rag_api, "get_rag_service", lambda: FakeRAGService())

    with client().stream(
        "POST",
        "/api/rag/index/stream",
        json={"noteId": "note-1", "requestId": "request-1"},
    ) as response:
        text = "".join(response.iter_text())

    assert response.status_code == 200
    assert "event: start" in text
    assert "event: progress" in text
    assert "Captioning image 1 of 2." in text
    assert "event: final" in text
    assert '"noteId":"note-1"' in text


def test_rag_index_job_pause_blocks_until_resume(monkeypatch):
    first_progress = threading.Event()
    continue_build = threading.Event()

    class FakeRAGService:
        def build_index(self, **kwargs):
            kwargs["progress_callback"]({"stage": "first", "message": "First checkpoint.", "percent": 20})
            first_progress.set()
            assert continue_build.wait(timeout=2)
            kwargs["progress_callback"]({"stage": "second", "message": "Second checkpoint.", "percent": 70})
            return {
                "success": True,
                "ready": True,
                "noteId": kwargs["note_id"],
                "indexes": {"qdrant": {"exists": True}, "bm25": {"exists": True}},
            }

    monkeypatch.setattr(rag_api, "get_rag_service", lambda: FakeRAGService())

    job = rag_api._start_or_get_rag_index_job({"noteId": "pause-note", "requestId": "pause-request"})
    assert first_progress.wait(timeout=2)

    paused = rag_api._pause_rag_job(job)
    assert paused["status"] == "paused"
    continue_build.set()
    time.sleep(0.1)

    summary = rag_api._rag_job_summary(job)
    assert summary["status"] == "paused"
    assert summary["progress"]["stage"] == "paused"
    assert not any(event.payload.get("stage") == "second" for event in job.events)

    resumed = rag_api._resume_rag_job(job)
    assert resumed["status"] == "running"
    assert wait_for(lambda: rag_api._rag_job_summary(job)["status"] == "succeeded")
    assert any(event.payload.get("stage") == "second" for event in job.events)


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
                    "collections": {"text": "custom_text"},
                    "build": {"loader": "llamaparse", "include_images": True, "qdrant": False, "bm25": True},
                    "chunking": {"chunk_size": 512, "chunk_overlap": 64},
                    "embedding": {
                        "provider": "openai",
                        "model": "configured-embedding",
                        "batch_size": 32,
                        "ollama": {"base_url": "http://ollama.test:11434"},
                    },
                    "image_captioning": {
                        "enabled": True,
                        "provider": "openai",
                        "model": "gpt-5.4-mini",
                        "max_images": 7,
                        "max_image_bytes": 12345,
                        "timeout": 42,
                        "concurrency": 3,
                        "prompt": "Caption for retrieval.",
                    },
                    "retrieval": {
                        "vector_top_k": 9,
                        "bm25_top_k": 6,
                        "result_top_k": 4,
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
    assert rag_config.build.loader == "llamaparse"
    assert rag_config.build.include_images is True
    assert rag_config.build.qdrant is False
    assert rag_config.chunking.chunk_size == 512
    assert rag_config.chunking.chunk_overlap == 64
    assert rag_config.embedding.provider_name() == "openai"
    assert rag_config.embedding.model_for("openai") == "configured-embedding"
    assert rag_config.embedding.batch_size == 32
    assert rag_config.image_captioning.enabled is True
    assert rag_config.image_captioning.provider == "openai"
    assert rag_config.image_captioning.model == "gpt-5.4-mini"
    assert rag_config.image_captioning.max_images == 7
    assert rag_config.image_captioning.max_image_bytes == 12345
    assert rag_config.image_captioning.timeout == 42
    assert rag_config.image_captioning.concurrency == 3
    assert rag_config.image_captioning.prompt == "Caption for retrieval."
    assert rag_config.retrieval.vector_top_k == 9
    assert rag_config.retrieval.bm25_top_k == 6
    assert rag_config.retrieval.result_top_k == 4
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


def test_image_captions_are_indexed_as_text_nodes():
    nodes = build_image_caption_nodes(
        [
            {
                "image_path": "/tmp/figure.png",
                "paper_id": "paper-1",
                "file_name": "paper.pdf",
                "page_number": 3,
                "image_index": 2,
                "source_anchor": "paper-1:page:3:image:2",
                "caption_text": "Figure 1. Retrieval accuracy across model ablations.",
                "caption": "A chart compares retrieval accuracy across ablations.",
                "caption_provider": "codex-oauth",
                "caption_model": "gpt-5.4-mini",
                "caption_generated": True,
            }
        ],
        chunk_size=256,
        chunk_overlap=0,
    )

    assert len(nodes) == 1
    assert "Source: page 3, image 2." in nodes[0].get_content()
    assert "retrieval accuracy" in nodes[0].get_content()
    assert "Original PDF caption:" in nodes[0].get_content()
    assert "Figure 1. Retrieval accuracy across model ablations." in nodes[0].get_content()
    assert "Generated visual caption:" in nodes[0].get_content()
    assert nodes[0].metadata["source_type"] == "image_caption"
    assert nodes[0].metadata["caption_text"] == "Figure 1. Retrieval accuracy across model ablations."
    assert nodes[0].metadata["caption_provider"] == "codex-oauth"
    assert nodes[0].metadata["source_anchor"] == "paper-1:page:3:image:2"


def test_image_caption_nodes_label_missing_page_as_unknown():
    nodes = build_image_caption_nodes(
        [
            {
                "image_path": "/tmp/figure.png",
                "paper_id": "paper-1",
                "file_name": "paper.pdf",
                "page_number": None,
                "image_index": 2,
                "source_anchor": "paper-1:page:unknown:image:2",
                "caption": "A chart compares retrieval accuracy across ablations.",
            }
        ],
        chunk_size=256,
        chunk_overlap=0,
    )

    assert len(nodes) == 1
    assert "Source: image 2; page number was not provided by the parser." in nodes[0].get_content()
    assert "page None" not in nodes[0].get_content()
    assert nodes[0].metadata["page_number"] is None


def test_image_caption_request_sends_prompt_as_instructions(tmp_path):
    image_path = tmp_path / "figure.png"
    image_path.write_bytes(b"png")
    calls = []

    class FakeResponses:
        def create(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(output_text="A concise caption.")

    caption = _caption_one_image(
        SimpleNamespace(responses=FakeResponses()),
        model="gpt-test",
        prompt="Describe the figure.",
        image_record={
            "image_path": image_path,
            "content_type": "image/png",
            "page_number": None,
            "image_index": 3,
            "caption": "This generated caption must not be used as an original PDF caption.",
        },
    )

    assert caption == "A concise caption."
    assert calls[0]["instructions"] == "Describe the figure."
    content = calls[0]["input"][0]["content"]
    assert len(content) == 1
    assert content[0]["type"] == "input_image"
    assert content[0]["image_url"].startswith("data:image/png;base64,")


def test_image_caption_request_uses_caption_text_without_caption_fallback(tmp_path):
    image_path = tmp_path / "figure.png"
    image_path.write_bytes(b"png")
    calls = []

    class FakeResponses:
        def create(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(output_text="A concise caption.")

    _caption_one_image(
        SimpleNamespace(responses=FakeResponses()),
        model="gpt-test",
        prompt="Describe the figure.",
        image_record={
            "image_path": image_path,
            "content_type": "image/png",
            "page_number": 4,
            "image_index": 1,
            "caption": "Generated caption should not be reused as a PDF caption hint.",
            "caption_text": "Figure 2. Original PDF figure caption.",
        },
    )

    hint = calls[0]["input"][0]["content"][0]["text"]
    assert "Original PDF figure caption/text near this image:" in hint
    assert "Figure 2. Original PDF figure caption." in hint
    assert "Source:" not in hint
    assert "Generated caption should not be reused" not in hint


def test_image_caption_records_run_concurrently_and_preserve_order(monkeypatch, tmp_path):
    records = []
    for index in range(1, 4):
        image_path = tmp_path / f"figure-{index}.png"
        image_path.write_bytes(b"png")
        records.append({
            "image_path": image_path,
            "content_type": "image/png",
            "page_number": index,
            "image_index": index,
            "caption_text": f"Figure {index}. Original caption.",
        })

    active = 0
    max_active = 0
    active_lock = threading.Lock()

    def fake_caption_one(_client, *, model, image_record, prompt, stream=False):
        nonlocal active, max_active
        assert model == "gpt-test"
        assert prompt == "Describe."
        assert stream is False
        with active_lock:
            active += 1
            max_active = max(max_active, active)
        try:
            time.sleep(0.08 if image_record["image_index"] == 1 else 0.01)
            return f"Caption {image_record['image_index']}"
        finally:
            with active_lock:
                active -= 1

    events = []
    monkeypatch.setattr(image_captioning, "_caption_client", lambda _provider, *, timeout: SimpleNamespace())
    monkeypatch.setattr(image_captioning, "_caption_one_image", fake_caption_one)

    captioned = image_captioning.caption_image_records(
        records,
        provider="openai",
        model="gpt-test",
        prompt="Describe.",
        concurrency=2,
        progress_callback=events.append,
    )

    assert max_active == 2
    assert [record["caption"] for record in captioned] == ["Caption 1", "Caption 2", "Caption 3"]
    assert [record["caption_text"] for record in captioned] == [
        "Figure 1. Original caption.",
        "Figure 2. Original caption.",
        "Figure 3. Original caption.",
    ]
    assert any(
        event["message"] == "Captioning 3 extracted images with concurrency 2." and event["concurrency"] == 2
        for event in events
    )


def test_image_caption_can_collect_streamed_response_text(tmp_path):
    image_path = tmp_path / "figure.jpg"
    image_path.write_bytes(b"jpg")
    calls = []

    class FakeStream:
        def __enter__(self):
            return self

        def __exit__(self, _exc_type, _exc, _tb):
            return None

        def __iter__(self):
            return iter([
                SimpleNamespace(type="response.output_text.delta", delta="Graph "),
                SimpleNamespace(type="response.output_text.delta", delta="caption."),
            ])

        def get_final_response(self):
            return SimpleNamespace(output_text="")

    class FakeResponses:
        def stream(self, **kwargs):
            calls.append(kwargs)
            return FakeStream()

    caption = _caption_one_image(
        SimpleNamespace(responses=FakeResponses()),
        model="gpt-test",
        prompt="Describe the figure.",
        stream=True,
        image_record={
            "image_path": image_path,
            "content_type": "application/octet-stream",
            "page_number": 2,
            "image_index": 1,
        },
    )

    assert caption == "Graph caption."
    assert calls[0]["instructions"] == "Describe the figure."
    assert calls[0]["input"][0]["content"][0]["image_url"].startswith("data:image/jpeg;base64,")
    assert "stream" not in calls[0]


def test_llamaparse_loader_downloads_images_from_metadata_without_items(monkeypatch, tmp_path):
    downloads = []

    def fake_download(*, url, output_dir, page_number, image_index, timeout, source_filename=None):
        image_path = Path(output_dir) / f"downloaded-{image_index}.png"
        image_path.write_bytes(b"png")
        downloads.append(
            {
                "url": url,
                "page_number": page_number,
                "image_index": image_index,
                "source_filename": source_filename,
            }
        )
        return image_path, "image/png"

    monkeypatch.setattr(llamaparse_loader, "_download_llamaparse_image", fake_download)
    result = SimpleNamespace(
        items=None,
        markdown=SimpleNamespace(
            pages=[
                SimpleNamespace(
                    success=True,
                    page_number=4,
                    markdown="Text before ![Figure 2](image_0.png) text after.",
                )
            ]
        ),
        images_content_metadata=SimpleNamespace(
            images=[
                SimpleNamespace(
                    filename="image_0.png",
                    index=0,
                    presigned_url="https://llamaparse.test/image_0.png",
                    content_type="image/png",
                    category="layout",
                    bbox=SimpleNamespace(model_dump=lambda: {"x": 1, "y": 2, "w": 30, "h": 40}),
                )
            ]
        ),
    )

    records = llamaparse_loader._build_image_records(
        result,
        pdf_path=Path("paper.pdf"),
        output_dir=tmp_path,
        download_timeout=5,
    )

    assert len(records) == 1
    assert downloads == [
        {
            "url": "https://llamaparse.test/image_0.png",
            "page_number": 4,
            "image_index": 1,
            "source_filename": "image_0.png",
        }
    ]
    assert records[0]["page_number"] == 4
    assert records[0]["filename"] == "image_0.png"
    assert records[0]["category"] == "layout"
    assert records[0]["bbox"] == [{"x": 1, "y": 2, "w": 30, "h": 40}]


def test_llamaparse_loader_resolves_image_page_from_metadata_fields():
    assert llamaparse_loader._resolve_llamaparse_image_page(
        SimpleNamespace(pageNumber="7"),
        filename="image_0.png",
        image_url=None,
        page_by_filename={},
    ) == 7
    assert llamaparse_loader._resolve_llamaparse_image_page(
        SimpleNamespace(pageIndex=0),
        filename="image_1.png",
        image_url=None,
        page_by_filename={},
    ) == 1
    assert llamaparse_loader._resolve_llamaparse_image_page(
        SimpleNamespace(bbox={"page": 5}),
        filename="image_2.png",
        image_url=None,
        page_by_filename={},
    ) == 5
    assert llamaparse_loader._resolve_llamaparse_image_page(
        SimpleNamespace(),
        filename="figures/page_9_img_1.png",
        image_url=None,
        page_by_filename={},
    ) == 9


def test_llamaparse_loader_accepts_image_items_without_type(monkeypatch, tmp_path):
    downloads = []

    def fake_download(*, url, output_dir, page_number, image_index, timeout, source_filename=None):
        image_path = Path(output_dir) / f"page-{page_number}-image-{image_index}.png"
        image_path.write_bytes(b"png")
        downloads.append((url, page_number, image_index, source_filename))
        return image_path, "image/png"

    monkeypatch.setattr(llamaparse_loader, "_download_llamaparse_image", fake_download)
    result = SimpleNamespace(
        items=SimpleNamespace(
            pages=[
                SimpleNamespace(
                    success=True,
                    page_number=2,
                    items=[
                        SimpleNamespace(
                            type=None,
                            url="figures/image_3.png",
                            md="![architecture](figures/image_3.png)",
                            caption="Architecture overview.",
                            bbox=[{"x": 5, "y": 6, "w": 70, "h": 80}],
                        )
                    ],
                )
            ]
        ),
        markdown=SimpleNamespace(pages=[]),
        images_content_metadata=SimpleNamespace(
            images=[
                SimpleNamespace(
                    filename="figures/image_3.png",
                    index=3,
                    presigned_url="https://llamaparse.test/image_3.png",
                    content_type="image/png",
                    category="embedded",
                    bbox=None,
                )
            ]
        ),
    )

    records = llamaparse_loader._build_image_records(
        result,
        pdf_path=Path("paper.pdf"),
        output_dir=tmp_path,
        download_timeout=5,
    )

    assert len(records) == 1
    assert downloads == [("https://llamaparse.test/image_3.png", 2, 1, "image_3.png")]
    assert records[0]["caption"] == "Architecture overview."
    assert records[0]["caption_text"] == "Architecture overview."
    assert records[0]["page_number"] == 2
    assert records[0]["category"] == "embedded"


def test_query_paper_content_tool_is_registered():
    tool_names = {tool_name(tool) for tool in create_tools(ToolContext(provider_name="openai", model="gpt-5.5"))}

    assert "query_paper_content" in tool_names
    assert "search_paper_rag" not in tool_names


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


def test_query_paper_content_facade_routes_to_service(monkeypatch, tmp_path):
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

    payload = facade.query_paper_content(
        {
            "note_id": "note-1",
            "query": "main contribution",
            "vector_top_k": 8,
            "bm25_top_k": 8,
            "result_top_k": 8,
        },
        library_path=library_path,
    )

    assert payload["success"] is True
    assert payload["results"][0]["text"] == "retrieved passage"
    rag_config = load_app_config().rag
    embedding_provider = rag_config.embedding.provider_name()
    assert calls == [
        {
            "query": "main contribution",
            "note_id": "note-1",
            "vector_top_k": rag_config.retrieval.vector_top_k,
            "bm25_top_k": rag_config.retrieval.bm25_top_k,
            "result_top_k": rag_config.retrieval.result_top_k,
            "embedding_provider": embedding_provider,
            "embedding_model": rag_config.embedding.model_for(embedding_provider),
            "library_path": library_path,
        }
    ]


def test_query_paper_content_facade_rejects_queries_array(tmp_path):
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

    payload = facade.query_paper_content(
        {
            "note_id": "note-1",
            "queries": ["main contribution", "datasets and experiments"],
        },
        library_path=library_path,
    )

    assert payload["success"] is False
    assert payload["code"] == "query_required"
    assert "query" in payload["error"]


def test_hybrid_retriever_uses_result_top_k_for_final_count():
    class FakeRetriever:
        def __init__(self, results):
            self.results = results

        def retrieve(self, _query):
            return self.results

    results = [
        SimpleNamespace(node=SimpleNamespace(node_id="vector-1"), score=0.9),
        SimpleNamespace(node=SimpleNamespace(node_id="vector-2"), score=0.8),
        SimpleNamespace(node=SimpleNamespace(node_id="bm25-1"), score=0.7),
        SimpleNamespace(node=SimpleNamespace(node_id="bm25-2"), score=0.6),
    ]
    retriever = HybridRetriever(
        vector_retriever=FakeRetriever(results[:2]),
        bm25_retriever=FakeRetriever(results[2:]),
        qdrant_index=SimpleNamespace(),
        result_top_k=3,
        weights=(0.5, 0.5),
    )

    assert len(retriever.retrieve("query")) == 3


def test_query_paper_content_facade_requires_query(tmp_path):
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

    payload = facade.query_paper_content(
        {
            "note_id": "note-1",
        },
        library_path=library_path,
    )

    assert payload["success"] is False
    assert payload["code"] == "query_required"
    assert "query" in payload["error"]


def test_query_paper_content_facade_uses_configured_rag_defaults(monkeypatch, tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "rag": {
                    "embedding": {"provider": "openai"},
                    "retrieval": {
                        "vector_top_k": 9,
                        "bm25_top_k": 6,
                        "result_top_k": 4,
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

    payload = facade.query_paper_content(
        {
            "note_id": "note-1",
            "query": "main contribution",
        },
        library_path=library_path,
    )

    assert payload["success"] is True
    assert calls[0]["vector_top_k"] == 9
    assert calls[0]["bm25_top_k"] == 6
    assert calls[0]["result_top_k"] == 4
    assert calls[0]["embedding_provider"] == "openai"
    assert calls[0]["embedding_model"] == load_app_config().rag.embedding.model_for("openai")


def test_query_paper_content_facade_ignores_model_controlled_rag_args(monkeypatch, tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({
            "rag": {
                "embedding": {
                    "provider": "openai",
                    "openai": {"model": "configured-embedding-model"},
                },
                "retrieval": {
                    "vector_top_k": 9,
                    "bm25_top_k": 6,
                    "result_top_k": 4,
                },
            }
        }),
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

    payload = facade.query_paper_content(
        {
            "note_id": "note-1",
            "query": "main contribution",
            "embedding_provider": "ollama",
            "embedding_model": "model-from-tool-args",
            "vector_top_k": 1,
            "bm25_top_k": 2,
            "result_top_k": 3,
        },
        library_path=library_path,
    )

    assert payload["success"] is True
    assert calls[0]["embedding_provider"] == "openai"
    assert calls[0]["embedding_model"] == "configured-embedding-model"
    assert calls[0]["vector_top_k"] == 9
    assert calls[0]["bm25_top_k"] == 6
    assert calls[0]["result_top_k"] == 4


def test_query_paper_content_reports_index_not_ready_without_visual_tool_fallback(monkeypatch, tmp_path):
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

    payload = facade.query_paper_content(
        {
            "note_id": "note-1",
            "query": "main contribution",
        },
        library_path=library_path,
    )

    assert payload["success"] is False
    assert payload["code"] == "index_not_ready"
    assert "fallbackTool" not in payload
    assert "fallbackArguments" not in payload
