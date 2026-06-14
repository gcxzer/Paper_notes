from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import NAMESPACE_URL, uuid5

from app_config import load_app_config

if TYPE_CHECKING:
    from llama_index.core.schema import BaseNode


class NodeParser:
    """Build all paper nodes from extracted text pages and image records."""

    def __init__(self, *, text_chunk_size: int | None = None, text_chunk_overlap: int | None = None) -> None:
        chunking = load_app_config().rag.chunking
        self.text_chunk_size = int(text_chunk_size) if text_chunk_size is not None else chunking.chunk_size
        self.text_chunk_overlap = int(text_chunk_overlap) if text_chunk_overlap is not None else chunking.chunk_overlap

    def parse(self, pages: list[dict], image_records: list[dict]) -> list[Any]:
        text_nodes = build_text_nodes(
            pages,
            chunk_size=self.text_chunk_size,
            chunk_overlap=self.text_chunk_overlap,
        )
        image_nodes = build_image_nodes(image_records)

        return text_nodes + image_nodes


def build_image_nodes(image_records: list[dict]):
    from llama_index.core.schema import ImageNode

    image_nodes = []

    for image in image_records:
        image_path = Path(image["image_path"])
        source_anchor = image["source_anchor"]

        image_nodes.append(
            ImageNode(
                id_=_stable_uuid(source_anchor),
                image_path=str(image_path),
                image_mimetype=image.get(
                    "content_type",
                    f"image/{image_path.suffix.lstrip('.')}",
                ),
                text=image.get("caption", ""),
                metadata={
                    "source_type": image.get("source_type", "pdf_image"),
                    "paper_id": image["paper_id"],
                    "file_name": image.get("file_name") or image["paper_id"],
                    "page_number": image["page_number"],
                    "image_index": image["image_index"],
                    "image_path": str(image_path),
                    "source_anchor": source_anchor,
                    "caption": image.get("caption", ""),
                    "bbox": image.get("bbox"),
                },
            )
        )

    return image_nodes


def build_text_nodes(pages: list[dict], *, chunk_size: int | None = None, chunk_overlap: int | None = None):
    from llama_index.core import Document
    from llama_index.core.node_parser import SentenceSplitter

    documents = [
        Document(
            id_=_stable_uuid(_page_anchor(page)),
            text=page["text"],
            metadata=page["metadata"],
        )
        for page in pages
        if page["text"].strip()
    ]

    if chunk_size is None or chunk_overlap is None:
        chunking = load_app_config().rag.chunking
        chunk_size = chunk_size or chunking.chunk_size
        chunk_overlap = chunking.chunk_overlap if chunk_overlap is None else chunk_overlap

    splitter = SentenceSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        id_func=_text_node_id,
    )

    return splitter.get_nodes_from_documents(documents)


def _text_node_id(chunk_index: int, document: BaseNode) -> str:
    return _stable_uuid(f"{document.id_}:chunk:{chunk_index}")


def _page_anchor(page: dict) -> str:
    metadata = page["metadata"]
    return f"{metadata['paper_id']}:page:{metadata['page_number']}"


def _stable_uuid(value: str) -> str:
    return str(uuid5(NAMESPACE_URL, value))
