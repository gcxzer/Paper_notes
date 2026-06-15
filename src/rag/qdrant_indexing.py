from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from app_config import load_app_config

if TYPE_CHECKING:
    from llama_index.core.indices.vector_store import VectorStoreIndex
    from llama_index.core.schema import BaseNode


class QdrantIndex:
    """Local Qdrant-backed text vector index for paper nodes."""

    def __init__(
        self,
        text_embed_model: Any,
        collection_name: str = "paper_notes",
        storage_path: str | Path | None = None,
    ) -> None:
        self.text_embed_model = text_embed_model
        self.collection_name = collection_name
        self.storage_path = Path(storage_path) if storage_path is not None else load_app_config().rag.qdrant_storage_path()
        self._closed = False

        import qdrant_client
        from llama_index.core import StorageContext
        from llama_index.vector_stores.qdrant import QdrantVectorStore

        self.client = qdrant_client.QdrantClient(path=str(self.storage_path))
        self.vector_store = QdrantVectorStore(
            client=self.client,
            collection_name=self.collection_name,
        )
        self.storage_context = StorageContext.from_defaults(
            vector_store=self.vector_store,
        )

    def build(self, nodes: list[BaseNode]) -> VectorStoreIndex:
        """Embed text nodes and store them in a local Qdrant collection."""
        from llama_index.core import VectorStoreIndex

        return VectorStoreIndex(
            nodes=nodes,
            storage_context=self.storage_context,
            embed_model=self.text_embed_model,
            show_progress=True,
        )

    def load(self) -> VectorStoreIndex:
        """Load an existing Qdrant collection as a LlamaIndex text index."""
        from llama_index.core import VectorStoreIndex

        return VectorStoreIndex.from_vector_store(
            vector_store=self.vector_store,
            embed_model=self.text_embed_model,
        )

    def close(self) -> None:
        """Close the local Qdrant client and release its storage lock."""
        if self._closed:
            return

        close = getattr(self.client, "close", None)
        if callable(close):
            close()
        self._closed = True

    @classmethod
    def exists(
        cls,
        collection_name: str = "paper_notes",
        storage_path: str | Path | None = None,
    ) -> bool:
        """Return True when the text Qdrant collection exists."""
        storage_path = Path(storage_path) if storage_path is not None else load_app_config().rag.qdrant_storage_path()
        if not storage_path.exists():
            return False

        meta_path = storage_path / "meta.json"
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
            collection_name in collections
            and cls._collection_storage_exists(storage_path, collection_name)
        )

    @staticmethod
    def _collection_storage_exists(storage_path: Path, collection_name: str) -> bool:
        return (storage_path / "collection" / collection_name / "storage.sqlite").exists()
