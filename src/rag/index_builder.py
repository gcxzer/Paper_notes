from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app_config import load_app_config
from rag.bm25_indexing import BM25Index
from rag.embedding_model import get_embedding_model, get_image_embedding_model
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
    image_collection: str
    embedding_provider: str | None = None
    embedding_model: str | None = None
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
        image_collection: str | None = None,
        embedding_provider: str | None = None,
        embedding_model: str | None = None,
        text_chunk_size: int | None = None,
        text_chunk_overlap: int | None = None,
    ) -> "RagIndexBuildRequest":
        resolved_pdf_path = Path(pdf_path)
        resolved_index_key = index_key or resolved_pdf_path.stem
        return cls(
            pdf_path=resolved_pdf_path,
            build_qdrant=rag_config.build.qdrant if build_qdrant is None else bool(build_qdrant),
            build_bm25=rag_config.build.bm25 if build_bm25 is None else bool(build_bm25),
            index_key=resolved_index_key,
            loader=loader or rag_config.build.loader,
            include_images=rag_config.build.include_images if include_images is None else bool(include_images),
            qdrant_storage_dir=Path(qdrant_storage_dir) if qdrant_storage_dir is not None else rag_config.qdrant_storage_path(resolved_index_key),
            bm25_persist_dir=Path(bm25_persist_dir) if bm25_persist_dir is not None else rag_config.bm25_storage_path(resolved_index_key),
            text_collection=text_collection or rag_config.text_collection_name(resolved_index_key),
            image_collection=image_collection or rag_config.image_collection_name(resolved_index_key),
            embedding_provider=embedding_provider,
            embedding_model=embedding_model,
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
    image_collection: str | None = None,
    embedding_provider: str | None = None,
    embedding_model: str | None = None,
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
        image_collection=image_collection,
        embedding_provider=embedding_provider,
        embedding_model=embedding_model,
        text_chunk_size=text_chunk_size,
        text_chunk_overlap=text_chunk_overlap,
    )
    if not request.build_qdrant and not request.build_bm25:
        print("Qdrant and BM25 indexes already exist.")
        return

    if request.loader == "llamaparse":
        pages, image_records = parse_pdf_with_llamaparse(
            request.pdf_path,
            image_output_dir=rag_config.image_output_path(request.index_key, loader="llamaparse"),
            include_images=request.include_images,
        )
    elif request.loader == "pymupdf":
        pages = extract_text_from_pdf(request.pdf_path)
        image_records = (
            extract_images_from_pdf(request.pdf_path, output_dir=rag_config.image_output_path(request.index_key, loader="pymupdf"))
            if request.include_images
            else []
        )
    else:
        raise ValueError("loader must be 'pymupdf' or 'llamaparse'.")

    node_parser = NodeParser(text_chunk_size=request.text_chunk_size, text_chunk_overlap=request.text_chunk_overlap)
    nodes = node_parser.parse(pages=pages, image_records=image_records)

    built_indexes = []

    if request.build_qdrant:
        text_embed_model = get_embedding_model(provider=request.embedding_provider, model=request.embedding_model)
        image_embed_model = get_image_embedding_model()

        qdrant_index = QdrantIndex(
            text_embed_model=text_embed_model,
            image_embed_model=image_embed_model,
            collection_name=request.text_collection,
            image_collection_name=request.image_collection,
            storage_path=request.qdrant_storage_dir,
        )

        try:
            qdrant_index.build(nodes)
        finally:
            qdrant_index.close()
        built_indexes.append("Qdrant")

    if request.build_bm25:
        BM25Index(persist_dir=request.bm25_persist_dir).build(nodes)
        built_indexes.append("BM25")

    print(f"Built {len(nodes)} nodes and built {' + '.join(built_indexes)} indexes.")
