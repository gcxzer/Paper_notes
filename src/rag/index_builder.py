"""说明：协调论文 RAG 索引构建流程。

作用：把加载、切分、向量化、BM25 和图片说明等步骤串成一次可恢复的索引任务。
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from app_config import load_app_config
from rag.bm25_indexing import BM25Index
from rag.embedding_model import get_embedding_model
from rag.image_captioning import caption_image_records
from rag.llamaparse_loader import parse_pdf_with_llamaparse
from rag.node_parser import NodeParser
from rag.pymupdf_loader import extract_images_from_pdf, extract_text_from_pdf
from rag.qdrant_indexing import QdrantIndex


@dataclass(frozen=True, slots=True)
class RagIndexBuildRequest:
    pdf_path: Path
    build_qdrant: bool
    build_bm25: bool
    index_key: str
    loader: str
    include_images: bool
    qdrant_storage_dir: Path
    bm25_persist_dir: Path
    text_collection: str
    embedding_provider: str | None = None
    embedding_model: str | None = None
    caption_images: bool = False
    caption_provider: str | None = None
    caption_model: str | None = None
    caption_prompt: str | None = None
    caption_max_images: int | None = None
    progress_callback: Callable[[dict[str, Any]], None] | None = None
    text_chunk_size: int | None = None
    text_chunk_overlap: int | None = None

    @classmethod
    def from_options(
        cls,
        *,
        rag_config: Any,
        pdf_path: str | Path,
        build_qdrant: bool | None = None,
        build_bm25: bool | None = None,
        index_key: str = "",
        loader: str | None = None,
        include_images: bool | None = None,
        qdrant_storage_dir: str | Path | None = None,
        bm25_persist_dir: str | Path | None = None,
        text_collection: str | None = None,
        embedding_provider: str | None = None,
        embedding_model: str | None = None,
        caption_images: bool | None = None,
        caption_provider: str | None = None,
        caption_model: str | None = None,
        caption_prompt: str | None = None,
        caption_max_images: int | None = None,
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
        text_chunk_size: int | None = None,
        text_chunk_overlap: int | None = None,
    ) -> "RagIndexBuildRequest":
        resolved_pdf_path = Path(pdf_path)
        resolved_index_key = index_key or resolved_pdf_path.stem
        resolved_caption_images = rag_config.image_captioning.enabled if caption_images is None else bool(caption_images)
        return cls(
            pdf_path=resolved_pdf_path,
            build_qdrant=rag_config.build.qdrant if build_qdrant is None else bool(build_qdrant),
            build_bm25=rag_config.build.bm25 if build_bm25 is None else bool(build_bm25),
            index_key=resolved_index_key,
            loader=loader or rag_config.build.loader,
            include_images=resolved_caption_images or (rag_config.build.include_images if include_images is None else bool(include_images)),
            qdrant_storage_dir=Path(qdrant_storage_dir) if qdrant_storage_dir is not None else rag_config.qdrant_storage_path(resolved_index_key),
            bm25_persist_dir=Path(bm25_persist_dir) if bm25_persist_dir is not None else rag_config.bm25_storage_path(resolved_index_key),
            text_collection=text_collection or rag_config.text_collection_name(resolved_index_key),
            embedding_provider=embedding_provider,
            embedding_model=embedding_model,
            caption_images=resolved_caption_images,
            caption_provider=caption_provider,
            caption_model=caption_model,
            caption_prompt=caption_prompt,
            caption_max_images=caption_max_images,
            progress_callback=progress_callback,
            text_chunk_size=text_chunk_size,
            text_chunk_overlap=text_chunk_overlap,
        )


def build_indexes(
    pdf_path: str | Path = "",
    build_qdrant: bool | None = None,
    build_bm25: bool | None = None,
    *,
    request: RagIndexBuildRequest | None = None,
    index_key: str = "",
    loader: str | None = None,
    include_images: bool | None = None,
    qdrant_storage_dir: str | Path | None = None,
    bm25_persist_dir: str | Path | None = None,
    text_collection: str | None = None,
    embedding_provider: str | None = None,
    embedding_model: str | None = None,
    caption_images: bool | None = None,
    caption_provider: str | None = None,
    caption_model: str | None = None,
    caption_prompt: str | None = None,
    caption_max_images: int | None = None,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
    text_chunk_size: int | None = None,
    text_chunk_overlap: int | None = None,
) -> None:
    rag_config = load_app_config().rag
    request = request or RagIndexBuildRequest.from_options(
        rag_config=rag_config,
        pdf_path=pdf_path,
        build_qdrant=build_qdrant,
        build_bm25=build_bm25,
        index_key=index_key,
        loader=loader,
        include_images=include_images,
        qdrant_storage_dir=qdrant_storage_dir,
        bm25_persist_dir=bm25_persist_dir,
        text_collection=text_collection,
        embedding_provider=embedding_provider,
        embedding_model=embedding_model,
        caption_images=caption_images,
        caption_provider=caption_provider,
        caption_model=caption_model,
        caption_prompt=caption_prompt,
        caption_max_images=caption_max_images,
        progress_callback=progress_callback,
        text_chunk_size=text_chunk_size,
        text_chunk_overlap=text_chunk_overlap,
    )
    if not request.build_qdrant and not request.build_bm25:
        print("Qdrant and BM25 indexes already exist.")
        _report_progress(request.progress_callback, stage="complete", message="RAG indexes already exist.", percent=100)
        return

    if request.loader == "llamaparse":
        _report_progress(request.progress_callback, stage="parsing", message="Parsing PDF with LlamaParse.", percent=10)
        pages, image_records = parse_pdf_with_llamaparse(
            request.pdf_path,
            image_output_dir=rag_config.image_output_path(request.index_key, loader="llamaparse"),
            include_images=request.include_images,
        )
    elif request.loader == "pymupdf":
        _report_progress(request.progress_callback, stage="parsing", message="Extracting PDF text with PyMuPDF.", percent=10)
        pages = extract_text_from_pdf(request.pdf_path)
        _report_progress(
            request.progress_callback,
            stage="parsing",
            message="Extracted PDF text.",
            percent=22,
            total=len(pages),
        )
        image_records = (
            extract_images_from_pdf(request.pdf_path, output_dir=rag_config.image_output_path(request.index_key, loader="pymupdf"))
            if request.include_images
            else []
        )
    else:
        raise ValueError("loader must be 'pymupdf' or 'llamaparse'.")

    _report_progress(
        request.progress_callback,
        stage="parsing",
        message=f"Parsed {len(pages)} pages and extracted {len(image_records)} images.",
        percent=28,
        pages=len(pages),
        images=len(image_records),
    )

    if request.caption_images:
        image_records = caption_image_records(
            image_records,
            provider=request.caption_provider,
            model=request.caption_model,
            prompt=request.caption_prompt,
            max_images=request.caption_max_images,
            progress_callback=request.progress_callback,
        )
    elif request.include_images and image_records:
        _report_progress(
            request.progress_callback,
            stage="captioning",
            message="Image captioning is disabled; extracted images will not be indexed.",
            percent=42,
            total=len(image_records),
        )

    _report_progress(request.progress_callback, stage="chunking", message="Chunking paper text.", percent=45)
    node_parser = NodeParser(text_chunk_size=request.text_chunk_size, text_chunk_overlap=request.text_chunk_overlap)
    nodes = node_parser.parse(pages=pages, image_records=image_records)
    _report_progress(
        request.progress_callback,
        stage="chunking",
        message=f"Built {len(nodes)} text nodes.",
        percent=55,
        total=len(nodes),
    )

    built_indexes = []

    if request.build_qdrant:
        _report_progress(request.progress_callback, stage="qdrant", message="Building vector index.", percent=62)
        text_embed_model = get_embedding_model(provider=request.embedding_provider, model=request.embedding_model)

        qdrant_index = QdrantIndex(
            text_embed_model=text_embed_model,
            collection_name=request.text_collection,
            storage_path=request.qdrant_storage_dir,
        )

        try:
            qdrant_index.build(nodes)
        finally:
            qdrant_index.close()
        built_indexes.append("Qdrant")
        _report_progress(request.progress_callback, stage="qdrant", message="Vector index built.", percent=82)

    if request.build_bm25:
        _report_progress(request.progress_callback, stage="bm25", message="Building BM25 index.", percent=86)
        BM25Index(persist_dir=request.bm25_persist_dir).build(nodes)
        built_indexes.append("BM25")
        _report_progress(request.progress_callback, stage="bm25", message="BM25 index built.", percent=96)

    print(f"Built {len(nodes)} nodes and built {' + '.join(built_indexes)} indexes.")
    _report_progress(
        request.progress_callback,
        stage="complete",
        message=f"Built {' + '.join(built_indexes)} indexes.",
        percent=100,
        nodes=len(nodes),
    )


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
