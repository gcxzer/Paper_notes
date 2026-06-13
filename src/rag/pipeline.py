from pathlib import Path

from rag.bm25_indexing import BM25Index
from rag.config import (
    DEFAULT_IMAGE_COLLECTION,
    DEFAULT_TEXT_COLLECTION,
    bm25_storage_path,
    image_collection_name,
    image_output_path,
    qdrant_storage_path,
    text_collection_name,
)
from rag.embedding_model import get_embedding_model, get_image_embedding_model
from rag.llamaparse_loader import parse_pdf_with_llamaparse
from rag.node_parser import NodeParser
from rag.pymupdf_loader import extract_images_from_pdf, extract_text_from_pdf
from rag.qdrant_indexing import QdrantIndex
from app_infra.paths import PAPERS_DIR

DEFAULT_PDF_PATH = PAPERS_DIR / "paper.pdf"
DEFAULT_QUERY = "这篇论文的核心贡献是什么？"


def qdrant_index_exists(
    storage_path: str | Path | None = None,
    text_collection: str = DEFAULT_TEXT_COLLECTION,
    image_collection: str = DEFAULT_IMAGE_COLLECTION,
) -> bool:
    return QdrantIndex.exists(
        collection_name=text_collection,
        image_collection_name=image_collection,
        storage_path=storage_path or qdrant_storage_path(),
    )


def bm25_index_exists(persist_dir: str | Path | None = None) -> bool:
    return BM25Index(persist_dir=persist_dir or bm25_storage_path()).exists()


def build_indexes(
    pdf_path: str | Path = DEFAULT_PDF_PATH,
    build_qdrant: bool = True,
    build_bm25: bool = True,
    *,
    index_key: str = "",
    loader: str = "pymupdf",
    include_images: bool = False,
    qdrant_storage_dir: str | Path | None = None,
    bm25_persist_dir: str | Path | None = None,
    text_collection: str | None = None,
    image_collection: str | None = None,
    embedding_provider: str = "ollama",
    embedding_model: str | None = None,
) -> None:
    if not build_qdrant and not build_bm25:
        print("Qdrant and BM25 indexes already exist.")
        return

    pdf_path = Path(pdf_path)
    index_key = index_key or pdf_path.stem
    text_collection = text_collection or text_collection_name(index_key)
    image_collection = image_collection or image_collection_name(index_key)
    qdrant_storage_dir = qdrant_storage_dir or qdrant_storage_path(index_key)
    bm25_persist_dir = bm25_persist_dir or bm25_storage_path(index_key)

    if loader == "llamaparse":
        pages, image_records = parse_pdf_with_llamaparse(
            pdf_path,
            image_output_dir=image_output_path(index_key, loader="llamaparse"),
            include_images=include_images,
        )
    elif loader == "pymupdf":
        pages = extract_text_from_pdf(pdf_path)
        image_records = (
            extract_images_from_pdf(pdf_path, output_dir=image_output_path(index_key, loader="pymupdf"))
            if include_images
            else []
        )
    else:
        raise ValueError("loader must be 'pymupdf' or 'llamaparse'.")

    node_parser = NodeParser()
    nodes = node_parser.parse(pages=pages, image_records=image_records)

    built_indexes = []

    if build_qdrant:
        text_embed_model = get_embedding_model(provider=embedding_provider, model=embedding_model)
        image_embed_model = get_image_embedding_model()

        qdrant_index = QdrantIndex(
            text_embed_model=text_embed_model,
            image_embed_model=image_embed_model,
            collection_name=text_collection,
            image_collection_name=image_collection,
            storage_path=qdrant_storage_dir,
        )

        try:
            qdrant_index.build(nodes)
        finally:
            qdrant_index.close()
        built_indexes.append("Qdrant")

    if build_bm25:
        BM25Index(persist_dir=bm25_persist_dir).build(nodes)
        built_indexes.append("BM25")

    print(f"Built {len(nodes)} nodes and built {' + '.join(built_indexes)} indexes.")


def main(query: str = DEFAULT_QUERY) -> None:
    has_qdrant_index = qdrant_index_exists()
    has_bm25_index = bm25_index_exists()

    if not has_qdrant_index or not has_bm25_index:
        missing_indexes = []
        if not has_qdrant_index:
            missing_indexes.append("Qdrant")
        if not has_bm25_index:
            missing_indexes.append("BM25")

        print(f"{' + '.join(missing_indexes)} index not found. Building missing indexes...")
        build_indexes(
            build_qdrant=not has_qdrant_index,
            build_bm25=not has_bm25_index,
        )

    from rag.retriever import close_retriever, get_retriever

    retriever = get_retriever()
    try:
        results = retriever.retrieve(query)
    finally:
        close_retriever(retriever)

    print(f"Query: {query}")
    print(f"Retrieved {len(results)} results.")

    print("\nSources:")
    for index, result in enumerate(results, start=1):
        metadata = getattr(getattr(result, "node", None), "metadata", {}) or {}
        file_name = metadata.get("file_name") or metadata.get("paper_id") or "unknown source"
        page_number = metadata.get("page_number")
        source_anchor = metadata.get("source_anchor")
        source = f"{file_name}, {source_anchor}" if source_anchor else f"{file_name}, page {page_number}"
        print(f"[{index}] score={getattr(result, 'score', None)} {source}")


if __name__ == "__main__":
    main()
