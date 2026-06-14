from __future__ import annotations

from pathlib import Path
from typing import Any

from app_config import load_app_config
from app_config.config import DEFAULT_IMAGE_COLLECTION, DEFAULT_TEXT_COLLECTION
from rag.bm25_indexing import BM25Index
from rag.embedding_model import get_embedding_model, get_image_embedding_model
from rag.qdrant_indexing import QdrantIndex


class HybridRetriever:
    def __init__(
        self,
        *,
        vector_retriever: Any,
        bm25_retriever: Any,
        qdrant_index: QdrantIndex,
        similarity_top_k: int,
        weights: tuple[float, float] | None = None,
    ) -> None:
        self.vector_retriever = vector_retriever
        self.bm25_retriever = bm25_retriever
        self._qdrant_index = qdrant_index
        self.similarity_top_k = similarity_top_k
        self.weights = weights or load_app_config().rag.retrieval.hybrid_weights

    def retrieve(self, query: str):
        combined: dict[str, dict[str, Any]] = {}
        for retriever, weight in (
            (self.vector_retriever, self.weights[0]),
            (self.bm25_retriever, self.weights[1]),
        ):
            for rank, result in enumerate(retriever.retrieve(query), start=1):
                key = _result_key(result)
                entry = combined.setdefault(key, {"score": 0.0, "result": result})
                entry["score"] += weight / (60 + rank)
                if getattr(result, "score", None) is not None and getattr(entry["result"], "score", None) is None:
                    entry["result"] = result

        ranked = sorted(combined.values(), key=lambda entry: float(entry["score"]), reverse=True)
        results = []
        for entry in ranked[: self.similarity_top_k]:
            result = entry["result"]
            try:
                result.score = entry["score"]
            except Exception:
                pass
            results.append(result)
        return results


def get_retriever(
    similarity_top_k: int | None = None,
    image_similarity_top_k: int | None = None,
    bm25_similarity_top_k: int | None = None,
    bm25_persist_dir: str | Path | None = None,
    qdrant_storage_dir: str | Path | None = None,
    collection_name: str = DEFAULT_TEXT_COLLECTION,
    image_collection_name: str = DEFAULT_IMAGE_COLLECTION,
    embedding_provider: str | None = None,
    embedding_model: str | None = None,
):
    rag_config = load_app_config().rag
    similarity_top_k = rag_config.retrieval.similarity_top_k_for(similarity_top_k)
    image_similarity_top_k = rag_config.retrieval.image_similarity_top_k_for(image_similarity_top_k)
    bm25_similarity_top_k = rag_config.retrieval.bm25_similarity_top_k_for(bm25_similarity_top_k)
    text_embed_model = get_embedding_model(provider=embedding_provider, model=embedding_model)
    image_embed_model = get_image_embedding_model()

    qdrant_index = QdrantIndex(
        text_embed_model=text_embed_model,
        image_embed_model=image_embed_model,
        collection_name=collection_name,
        image_collection_name=image_collection_name,
        storage_path=qdrant_storage_dir or rag_config.qdrant_storage_path(),
    )
    index = qdrant_index.load()
    vector_retriever = index.as_retriever(
        similarity_top_k=similarity_top_k,
        image_similarity_top_k=image_similarity_top_k,
    )
    bm25_retriever = BM25Index(
        similarity_top_k=bm25_similarity_top_k,
        persist_dir=bm25_persist_dir or rag_config.bm25_storage_path(),
    ).load()

    return HybridRetriever(
        vector_retriever=vector_retriever,
        bm25_retriever=bm25_retriever,
        qdrant_index=qdrant_index,
        similarity_top_k=similarity_top_k,
        weights=rag_config.retrieval.hybrid_weights,
    )


def close_retriever(retriever) -> None:
    qdrant_index = getattr(retriever, "_qdrant_index", None)
    if qdrant_index is None:
        return

    qdrant_index.close()
    retriever._qdrant_index = None


def _result_key(result: Any) -> str:
    node = getattr(result, "node", None)
    for attr in ("node_id", "id_", "id"):
        value = getattr(node, attr, "")
        if value:
            return str(value)
    if node is not None and callable(getattr(node, "get_content", None)):
        return str(node.get_content() or "")[:500]
    return repr(result)
