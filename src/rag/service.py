"""说明：提供 RAG 索引和查询的服务层。

作用：负责索引任务状态、暂停恢复、进度事件和对外查询接口。
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.parse import unquote

from app_config import load_app_config
from app_config.config import DEFAULT_INDEX_KEY, safe_index_key
from app_infra.formatting import normalize_text
from library.store import find_note, read_library
from app_infra.files import PAPERS_DIR, PROJECT_ROOT, is_relative_to
from rag.bm25_indexing import BM25Index
from rag.qdrant_indexing import QdrantIndex


_SERVICE: PaperRAGService | None = None
_SERVICE_LOCK = threading.Lock()


class RAGServiceError(RuntimeError):
    def __init__(self, message: str, *, code: str = "rag_error") -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class _RagIndexSpec:
    key: str
    text_collection: str
    qdrant_path: Path
    bm25_path: Path


class PaperRAGService:
    """Backend facade for the local Paper Notes RAG indexes."""

    def status(
        self,
        *,
        index_key: str = "",
        note_id: str = "",
        pdf_path: str | Path | None = None,
        library_path: str | Path | None = None,
    ) -> dict[str, Any]:
        resolved = self.resolve_target(
            note_id=note_id,
            pdf_path=pdf_path,
            library_path=library_path,
            require_pdf=False,
        )
        rag_config = load_app_config().rag
        spec = _index_spec(rag_config, index_key or resolved.get("index_key") or DEFAULT_INDEX_KEY)
        qdrant_exists = QdrantIndex.exists(
            collection_name=spec.text_collection,
            storage_path=spec.qdrant_path,
        )
        bm25_exists = BM25Index.exists_at(spec.bm25_path)

        return {
            "success": True,
            "indexKey": spec.key,
            "noteId": resolved.get("note_id", ""),
            "pdfPath": resolved.get("pdf_path", ""),
            "indexes": {
                "qdrant": {
                    "exists": qdrant_exists,
                    "path": str(spec.qdrant_path),
                    "textCollection": spec.text_collection,
                },
                "bm25": {
                    "exists": bm25_exists,
                    "path": str(spec.bm25_path),
                },
            },
            "ready": qdrant_exists and bm25_exists,
        }

    def build_index(
        self,
        *,
        note_id: str = "",
        pdf_path: str | Path | None = None,
        index_key: str = "",
        loader: str | None = None,
        include_images: bool | None = None,
        rebuild: bool = False,
        build_qdrant: bool | None = None,
        build_bm25: bool | None = None,
        embedding_provider: str | None = None,
        embedding_model: str | None = None,
        caption_images: bool | None = None,
        caption_provider: str | None = None,
        caption_model: str | None = None,
        caption_prompt: str | None = None,
        caption_max_images: int | None = None,
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
        library_path: str | Path | None = None,
    ) -> dict[str, Any]:
        rag_config = load_app_config().rag
        _report_progress(progress_callback, stage="loading", message="Preparing RAG index build.", percent=3)
        loader = _normalize_loader(loader or rag_config.build.loader)
        include_images = rag_config.build.include_images if include_images is None else include_images
        caption_images = rag_config.image_captioning.enabled if caption_images is None else caption_images
        if caption_images:
            include_images = True
        build_qdrant = rag_config.build.qdrant if build_qdrant is None else build_qdrant
        build_bm25 = rag_config.build.bm25 if build_bm25 is None else build_bm25
        resolved = self.resolve_target(
            note_id=note_id,
            pdf_path=pdf_path,
            library_path=library_path,
            require_pdf=True,
        )
        _report_progress(progress_callback, stage="loading", message="Resolved paper PDF.", percent=6)
        spec = _index_spec(rag_config, index_key or resolved["index_key"])
        before = self.status(index_key=spec.key, note_id=note_id, pdf_path=resolved["pdf_path"], library_path=library_path)
        should_build_qdrant = bool(build_qdrant and (rebuild or not before["indexes"]["qdrant"]["exists"]))
        should_build_bm25 = bool(build_bm25 and (rebuild or not before["indexes"]["bm25"]["exists"]))

        if should_build_qdrant or should_build_bm25:
            from rag.index_builder import RagIndexBuildRequest, build_indexes

            build_indexes(
                request=RagIndexBuildRequest(
                    pdf_path=Path(resolved["pdf_path"]),
                    build_qdrant=should_build_qdrant,
                    build_bm25=should_build_bm25,
                    index_key=spec.key,
                    loader=loader,
                    include_images=bool(include_images),
                    qdrant_storage_dir=spec.qdrant_path,
                    bm25_persist_dir=spec.bm25_path,
                    text_collection=spec.text_collection,
                    embedding_provider=embedding_provider,
                    embedding_model=embedding_model,
                    caption_images=bool(caption_images),
                    caption_provider=caption_provider,
                    caption_model=caption_model,
                    caption_prompt=caption_prompt,
                    caption_max_images=caption_max_images,
                    progress_callback=progress_callback,
                )
            )
        else:
            _report_progress(progress_callback, stage="complete", message="RAG indexes are already ready.", percent=100)

        after = self.status(index_key=spec.key, note_id=note_id, pdf_path=resolved["pdf_path"], library_path=library_path)
        return {
            **after,
            "built": {
                "qdrant": should_build_qdrant,
                "bm25": should_build_bm25,
            },
            "loader": loader,
            "includeImages": include_images,
            "captionImages": caption_images,
        }

    def query(
        self,
        *,
        query: str,
        note_id: str = "",
        pdf_path: str | Path | None = None,
        index_key: str = "",
        vector_top_k: int | None = None,
        bm25_top_k: int | None = None,
        embedding_provider: str | None = None,
        embedding_model: str | None = None,
        library_path: str | Path | None = None,
    ) -> dict[str, Any]:
        normalized_query = normalize_text(query)
        if not normalized_query:
            raise RAGServiceError("query is required.", code="query_required")

        resolved = self.resolve_target(
            note_id=note_id,
            pdf_path=pdf_path,
            library_path=library_path,
            require_pdf=False,
        )
        rag_config = load_app_config().rag
        spec = _index_spec(rag_config, index_key or resolved.get("index_key") or DEFAULT_INDEX_KEY)
        status = self.status(index_key=spec.key, note_id=note_id, pdf_path=resolved.get("pdf_path"), library_path=library_path)
        if not status["ready"]:
            raise RAGServiceError("RAG indexes are not ready. Build the index before querying.", code="index_not_ready")

        from rag.retriever import close_retriever, get_retriever

        reranking_config = rag_config.reranking
        retriever_result_top_k = rag_config.retrieval.retriever_result_top_k_for()

        retriever = get_retriever(
            vector_top_k=rag_config.retrieval.vector_top_k_for(vector_top_k),
            bm25_top_k=rag_config.retrieval.bm25_top_k_for(bm25_top_k),
            retriever_result_top_k=retriever_result_top_k,
            bm25_persist_dir=spec.bm25_path,
            qdrant_storage_dir=spec.qdrant_path,
            collection_name=spec.text_collection,
            embedding_provider=embedding_provider,
            embedding_model=embedding_model,
        )
        try:
            results = retriever.retrieve(normalized_query)
        finally:
            close_retriever(retriever)

        reranking_status: dict[str, Any] = {"enabled": bool(reranking_config.enabled), "applied": False}
        if reranking_config.enabled:
            from rag.reranker import rerank_results

            rerank_top_n = reranking_config.top_n
            reranking_status.update({
                "provider": reranking_config.provider,
                "model": reranking_config.model,
                "retrieverResultTopK": retriever_result_top_k,
                "candidateCount": len(results),
                "topN": rerank_top_n,
            })
            try:
                results = rerank_results(
                    normalized_query,
                    results,
                    reranking_config,
                    top_n=rerank_top_n,
                )
                reranking_status["applied"] = True
            except Exception as error:
                reranking_status["error"] = f"{type(error).__name__}: {error}"
                reranking_status["fallbackTopN"] = rerank_top_n
                results = _fallback_rerank_results(results, top_n=rerank_top_n)

        payload: dict[str, Any] = {
            "success": True,
            "query": normalized_query,
            "indexKey": spec.key,
            "noteId": resolved.get("note_id", ""),
            "pdfPath": resolved.get("pdf_path", ""),
            "results": [_result_payload(result, index=index) for index, result in enumerate(results, start=1)],
            "resultCount": len(results),
            "reranking": reranking_status,
        }
        return payload

    def resolve_target(
        self,
        *,
        note_id: str = "",
        pdf_path: str | Path | None = None,
        library_path: str | Path | None = None,
        require_pdf: bool = True,
    ) -> dict[str, str]:
        requested_pdf = normalize_text(pdf_path)
        requested_note_id = normalize_text(note_id)
        if requested_pdf:
            resolved_pdf = _resolve_local_pdf_path(requested_pdf)
            if require_pdf and not resolved_pdf.is_file():
                raise RAGServiceError(f"PDF file not found: {resolved_pdf}", code="pdf_not_found")
            return {
                "note_id": requested_note_id,
                "pdf_path": str(resolved_pdf),
                "index_key": safe_index_key(requested_note_id or resolved_pdf.stem),
            }

        if requested_note_id:
            library = read_library(Path(library_path)) if library_path is not None else read_library()
            note = find_note(library, requested_note_id)
            if note is None:
                raise RAGServiceError(f"Note not found: {requested_note_id}", code="note_not_found")
            href = normalize_text(note.get("href"))
            if not href:
                raise RAGServiceError(f"Note has no PDF href: {requested_note_id}", code="pdf_not_found")
            resolved_pdf = _resolve_note_href(href)
            if require_pdf and not resolved_pdf.is_file():
                raise RAGServiceError(f"PDF file not found: {resolved_pdf}", code="pdf_not_found")
            return {
                "note_id": requested_note_id,
                "pdf_path": str(resolved_pdf),
                "index_key": safe_index_key(requested_note_id),
            }

        return {"note_id": "", "pdf_path": "", "index_key": DEFAULT_INDEX_KEY}


def get_rag_service() -> PaperRAGService:
    global _SERVICE
    with _SERVICE_LOCK:
        if _SERVICE is None:
            _SERVICE = PaperRAGService()
        return _SERVICE


def _resolve_note_href(href: str) -> Path:
    unquoted = unquote(href)
    if unquoted.startswith("resources/Papers/"):
        return (PROJECT_ROOT / unquoted).resolve()
    return (PAPERS_DIR / Path(unquoted).name).resolve()


def _resolve_local_pdf_path(value: str) -> Path:
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = PROJECT_ROOT / candidate
    resolved = candidate.resolve()
    if is_relative_to(resolved, PROJECT_ROOT.resolve()) or is_relative_to(resolved, PAPERS_DIR.resolve()):
        return resolved
    raise RAGServiceError("PDF path must be inside the Paper Notes project.", code="invalid_pdf_path")


def _index_spec(rag_config: Any, index_key: object = DEFAULT_INDEX_KEY) -> _RagIndexSpec:
    key = safe_index_key(index_key or DEFAULT_INDEX_KEY)
    return _RagIndexSpec(
        key=key,
        text_collection=rag_config.text_collection_name(key),
        qdrant_path=rag_config.qdrant_storage_path(key),
        bm25_path=rag_config.bm25_storage_path(key),
    )


def _result_payload(result: Any, *, index: int) -> dict[str, Any]:
    node = getattr(result, "node", None)
    metadata = dict(getattr(node, "metadata", {}) or {})
    content = ""
    if node is not None and callable(getattr(node, "get_content", None)):
        content = str(node.get_content() or "")
    return {
        "index": index,
        "score": getattr(result, "score", None),
        "text": content[:4000],
        "metadata": metadata,
        "source": _source_label(metadata),
    }


def _fallback_rerank_results(results: list[Any], *, top_n: int) -> list[Any]:
    return results[: max(1, top_n)]


def _source_label(metadata: dict[str, Any]) -> str:
    file_name = metadata.get("file_name") or metadata.get("paper_id") or "unknown source"
    source_anchor = metadata.get("source_anchor")
    page_number = metadata.get("page_number")
    if source_anchor:
        return f"{file_name}, {source_anchor}"
    if page_number is not None:
        return f"{file_name}, page {page_number}"
    return str(file_name)


def _normalize_loader(value: object) -> str:
    loader = normalize_text(value).lower() or "pymupdf"
    if loader not in {"pymupdf", "llamaparse"}:
        raise RAGServiceError("loader must be 'pymupdf' or 'llamaparse'.", code="invalid_loader")
    return loader


def _report_progress(
    callback: Callable[[dict[str, Any]], None] | None,
    *,
    stage: str,
    message: str,
    percent: int | float | None = None,
    **extra: Any,
) -> None:
    if not callable(callback):
        return
    payload: dict[str, Any] = {"stage": stage, "message": message}
    if percent is not None:
        payload["percent"] = max(0, min(100, int(percent)))
    payload.update({key: value for key, value in extra.items() if value is not None})
    callback(payload)
