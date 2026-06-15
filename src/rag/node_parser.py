from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import NAMESPACE_URL, uuid5

from app_config import load_app_config

if TYPE_CHECKING:
    from llama_index.core.schema import BaseNode

CHUNK_METADATA_EXCLUDED_KEYS = (
    "source_pdf",
    "image_path",
    "bbox",
    "caption",
    "caption_text",
)


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
        image_nodes = build_image_caption_nodes(
            image_records,
            chunk_size=self.text_chunk_size,
            chunk_overlap=self.text_chunk_overlap,
        )

        return text_nodes + image_nodes


def build_image_caption_nodes(
    image_records: list[dict],
    *,
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
):
    caption_pages = []
    for image in image_records:
        caption = str(image.get("caption") or "").strip()
        if not caption:
            continue
        caption_text = str(image.get("caption_text") or "").strip()

        page_number = image.get("page_number")
        image_index = image.get("image_index")
        caption_pages.append({
            "text": _image_caption_node_text(
                page_number=page_number,
                image_index=image_index,
                caption=caption,
                caption_text=caption_text,
            ),
            "metadata": {
                "source_type": "image_caption",
                "paper_id": image["paper_id"],
                "file_name": image.get("file_name") or image["paper_id"],
                "page_number": page_number,
                "image_index": image_index,
                "image_path": str(image.get("image_path") or ""),
                "source_anchor": image["source_anchor"],
                "caption": caption,
                "caption_text": caption_text,
                "caption_provider": image.get("caption_provider", ""),
                "caption_model": image.get("caption_model", ""),
                "caption_generated": bool(image.get("caption_generated")),
                "bbox": image.get("bbox"),
            },
        })

    return build_text_nodes(caption_pages, chunk_size=chunk_size, chunk_overlap=chunk_overlap)


def _image_caption_node_text(*, page_number: object, image_index: object, caption: str, caption_text: str) -> str:
    if caption_text and caption_text != caption:
        return (
            f"Original PDF caption:\n{caption_text}\n\n"
            f"Generated visual caption:\n{caption}"
        )
    return caption


def build_text_nodes(pages: list[dict], *, chunk_size: int | None = None, chunk_overlap: int | None = None):
    from llama_index.core import Document
    from llama_index.core.node_parser import SentenceSplitter

    documents = [
        Document(
            id_=_stable_uuid(_page_anchor(page)),
            text=page["text"],
            metadata=page["metadata"],
            excluded_embed_metadata_keys=list(CHUNK_METADATA_EXCLUDED_KEYS),
            excluded_llm_metadata_keys=list(CHUNK_METADATA_EXCLUDED_KEYS),
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
    if metadata.get("source_anchor"):
        return str(metadata["source_anchor"])
    return f"{metadata['paper_id']}:page:{metadata['page_number']}"


def _stable_uuid(value: str) -> str:
    return str(uuid5(NAMESPACE_URL, value))
