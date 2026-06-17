"""说明：构建和查询 BM25 关键词索引。

作用：为论文检索提供非向量的关键词召回通道，补充语义检索。
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from app_config import load_app_config

if TYPE_CHECKING:
    from llama_index.core.schema import BaseNode
    from llama_index.retrievers.bm25 import BM25Retriever


class BM25Index:
    """Local BM25 keyword index for paper text nodes."""

    def __init__(
        self,
        top_k: int | None = None,
        persist_dir: str | Path | None = None,
    ) -> None:
        rag_config = load_app_config().rag
        self.top_k = rag_config.retrieval.bm25_top_k_for(top_k)
        self.persist_dir = Path(persist_dir) if persist_dir is not None else rag_config.bm25_storage_path()

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
        return self.exists_at(self.persist_dir)

    @staticmethod
    def exists_at(persist_dir: str | Path) -> bool:
        """Return True when a BM25 retriever exists at the given path."""
        return (Path(persist_dir) / "retriever.json").exists()

    def _effective_top_k(self, corpus_size: int | None) -> int:
        if corpus_size is None:
            return self.top_k
        return min(self.top_k, corpus_size)
