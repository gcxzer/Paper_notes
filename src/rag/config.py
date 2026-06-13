from __future__ import annotations

import re
from pathlib import Path

from app_infra.paths import PROJECT_ROOT


RAG_ROOT = PROJECT_ROOT / ".paper-notes" / "rag"
RAG_INDEX_ROOT = RAG_ROOT / "indexes"
RAG_IMAGE_ROOT = RAG_ROOT / "images"

DEFAULT_INDEX_KEY = "default"
DEFAULT_TEXT_COLLECTION = "paper_notes"
DEFAULT_IMAGE_COLLECTION = "paper_notes_images"


def safe_index_key(value: object = "") -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9._-]+", "-", text)
    text = re.sub(r"-{2,}", "-", text).strip(".-")
    return text or DEFAULT_INDEX_KEY


def qdrant_storage_path(index_key: object = DEFAULT_INDEX_KEY) -> Path:
    return RAG_INDEX_ROOT / safe_index_key(index_key) / "qdrant"


def bm25_storage_path(index_key: object = DEFAULT_INDEX_KEY) -> Path:
    return RAG_INDEX_ROOT / safe_index_key(index_key) / "bm25"


def image_output_path(index_key: object = DEFAULT_INDEX_KEY, *, loader: str = "llamaparse") -> Path:
    suffix = safe_index_key(loader)
    return RAG_IMAGE_ROOT / safe_index_key(index_key) / suffix


def text_collection_name(index_key: object = DEFAULT_INDEX_KEY) -> str:
    key = safe_index_key(index_key).replace("-", "_").replace(".", "_")
    return DEFAULT_TEXT_COLLECTION if key == DEFAULT_INDEX_KEY else f"{DEFAULT_TEXT_COLLECTION}_{key}"


def image_collection_name(index_key: object = DEFAULT_INDEX_KEY) -> str:
    key = safe_index_key(index_key).replace("-", "_").replace(".", "_")
    return DEFAULT_IMAGE_COLLECTION if key == DEFAULT_INDEX_KEY else f"{DEFAULT_IMAGE_COLLECTION}_{key}"
