from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from rag.config import (
    DEFAULT_INDEX_KEY,
    bm25_storage_path,
    image_collection_name,
    qdrant_storage_path,
    safe_index_key,
    text_collection_name,
)
from app_infra.formatting import normalize_text
from library.store import find_note, read_library
from app_infra.paths import PAPERS_DIR, PROJECT_ROOT, is_relative_to


_SERVICE: PaperRAGService | None = None
_SERVICE_LOCK = threading.Lock()


class RAGServiceError(RuntimeError):
    def __init__(self, message: str, *, code: str = "rag_error") -> None:
        super().__init__(message)
        self.code = code


class PaperRAGService:
    """Backend facade for the local Paper Notes RAG indexes."""

    def status(
        self,
        *,
        index_key: str = DEFAULT_INDEX_KEY,
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
        key = safe_index_key(index_key or resolved.get("index_key") or DEFAULT_INDEX_KEY)
        text_collection = text_collection_name(key)
        image_collection = image_collection_name(key)
        qdrant_path = qdrant_storage_path(key)
        bm25_path = bm25_storage_path(key)
        qdrant_exists = _qdrant_index_exists(
            qdrant_path,
            text_collection=text_collection,
            image_collection=image_collection,
        )
        bm25_exists = (bm25_path / "retriever.json").exists()

        return {
            "success": True,
            "indexKey": key,
            "noteId": resolved.get("note_id", ""),
            "pdfPath": resolved.get("pdf_path", ""),
            "indexes": {
                "qdrant": {
                    "exists": qdrant_exists,
                    "path": str(qdrant_path),
                    "textCollection": text_collection,
                    "imageCollection": image_collection,
                },
                "bm25": {
                    "exists": bm25_exists,
                    "path": str(bm25_path),
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
        loader: str = "pymupdf",
        include_images: bool = False,
        rebuild: bool = False,
        build_qdrant: bool = True,
        build_bm25: bool = True,
        embedding_provider: str = "ollama",
        embedding_model: str | None = None,
        library_path: str | Path | None = None,
    ) -> dict[str, Any]:
        resolved = self.resolve_target(
            note_id=note_id,
            pdf_path=pdf_path,
            library_path=library_path,
            require_pdf=True,
        )
        key = safe_index_key(index_key or resolved["index_key"])
        before = self.status(index_key=key, note_id=note_id, pdf_path=resolved["pdf_path"], library_path=library_path)
        should_build_qdrant = bool(build_qdrant and (rebuild or not before["indexes"]["qdrant"]["exists"]))
        should_build_bm25 = bool(build_bm25 and (rebuild or not before["indexes"]["bm25"]["exists"]))

        if should_build_qdrant or should_build_bm25:
            from rag.pipeline import build_indexes

            build_indexes(
                resolved["pdf_path"],
                build_qdrant=should_build_qdrant,
                build_bm25=should_build_bm25,
                index_key=key,
                loader=_normalize_loader(loader),
                include_images=include_images,
                qdrant_storage_dir=qdrant_storage_path(key),
                bm25_persist_dir=bm25_storage_path(key),
                text_collection=text_collection_name(key),
                image_collection=image_collection_name(key),
                embedding_provider=embedding_provider,
                embedding_model=embedding_model,
            )

        after = self.status(index_key=key, note_id=note_id, pdf_path=resolved["pdf_path"], library_path=library_path)
        return {
            **after,
            "built": {
                "qdrant": should_build_qdrant,
                "bm25": should_build_bm25,
            },
            "loader": _normalize_loader(loader),
            "includeImages": include_images,
        }

    def query(
        self,
        *,
        query: str,
        note_id: str = "",
        pdf_path: str | Path | None = None,
        index_key: str = "",
        similarity_top_k: int = 5,
        image_similarity_top_k: int = 3,
        bm25_similarity_top_k: int = 5,
        embedding_provider: str = "ollama",
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
        key = safe_index_key(index_key or resolved.get("index_key") or DEFAULT_INDEX_KEY)
        status = self.status(index_key=key, note_id=note_id, pdf_path=resolved.get("pdf_path"), library_path=library_path)
        if not status["ready"]:
            raise RAGServiceError("RAG indexes are not ready. Build the index before querying.", code="index_not_ready")

        from rag.retriever import close_retriever, get_retriever

        retriever = get_retriever(
            similarity_top_k=max(1, min(int(similarity_top_k), 20)),
            image_similarity_top_k=max(1, min(int(image_similarity_top_k), 20)),
            bm25_similarity_top_k=max(1, min(int(bm25_similarity_top_k), 20)),
            bm25_persist_dir=bm25_storage_path(key),
            qdrant_storage_dir=qdrant_storage_path(key),
            collection_name=text_collection_name(key),
            image_collection_name=image_collection_name(key),
            embedding_provider=embedding_provider,
            embedding_model=embedding_model,
        )
        try:
            results = retriever.retrieve(normalized_query)
        finally:
            close_retriever(retriever)

        payload: dict[str, Any] = {
            "success": True,
            "query": normalized_query,
            "indexKey": key,
            "noteId": resolved.get("note_id", ""),
            "pdfPath": resolved.get("pdf_path", ""),
            "results": [_result_payload(result, index=index) for index, result in enumerate(results, start=1)],
            "resultCount": len(results),
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


def _qdrant_index_exists(path: Path, *, text_collection: str, image_collection: str) -> bool:
    meta_path = path / "meta.json"
    if not meta_path.exists():
        return False
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    collections = meta.get("collections")
    if not isinstance(collections, dict):
        return False
    return (
        text_collection in collections
        and image_collection in collections
        and (path / "collection" / text_collection / "storage.sqlite").exists()
        and (path / "collection" / image_collection / "storage.sqlite").exists()
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
