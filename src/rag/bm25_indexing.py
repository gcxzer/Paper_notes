from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from rag.config import bm25_storage_path

if TYPE_CHECKING:
    from llama_index.core.schema import BaseNode
    from llama_index.retrievers.bm25 import BM25Retriever


class BM25Index:
    """Local BM25 keyword index for paper text nodes."""

    def __init__(
        self,
        similarity_top_k: int = 5,
        persist_dir: str | Path | None = None,
    ) -> None:
        self.similarity_top_k = similarity_top_k
        self.persist_dir = Path(persist_dir) if persist_dir is not None else bm25_storage_path()

    def build(self, nodes: list[BaseNode]) -> BM25Retriever:
        """Build and persist a BM25 retriever from text-bearing nodes."""
        from llama_index.retrievers.bm25 import BM25Retriever

        self.persist_dir.mkdir(parents=True, exist_ok=True)
        text_nodes = [node for node in nodes if node.get_content().strip()]
        if not text_nodes:
            raise ValueError("BM25Index requires at least one node with text content.")

        bm25_retriever = BM25Retriever.from_defaults(
            nodes=text_nodes,
            similarity_top_k=self._effective_top_k(len(text_nodes)),
        )
        bm25_retriever.persist(str(self.persist_dir))

        return bm25_retriever

    def load(self) -> BM25Retriever:
        """Load the persisted BM25 retriever."""
        from llama_index.retrievers.bm25 import BM25Retriever

        bm25_retriever = BM25Retriever.from_persist_dir(str(self.persist_dir))
        corpus = getattr(getattr(bm25_retriever, "bm25", None), "corpus", None)
        corpus_size = len(corpus) if corpus is not None else None
        bm25_retriever.similarity_top_k = self._effective_top_k(corpus_size)
        return bm25_retriever

    def exists(self) -> bool:
        """Return True when the BM25 retriever has been persisted."""
        return (self.persist_dir / "retriever.json").exists()

    def _effective_top_k(self, corpus_size: int | None) -> int:
        if corpus_size is None:
            return self.similarity_top_k
        return min(self.similarity_top_k, corpus_size)
