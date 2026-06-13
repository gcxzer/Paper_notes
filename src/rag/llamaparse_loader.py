"""LlamaParse-based PDF loader for text, markdown, and extracted images."""

from __future__ import annotations

import mimetypes
import os
import re
from pathlib import Path
from urllib.parse import unquote, urlparse

import httpx

from rag.config import image_output_path

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

if load_dotenv is not None:
    load_dotenv()

DEFAULT_CUSTOM_PROMPT = (
    "Parse this academic paper into clean Markdown. Preserve section headings, "
    "equations, citations, figure captions, table captions, tables, and references. "
    "Keep the reading order correct for multi-column paper layouts."
)
DEFAULT_IMAGE_CATEGORIES = ["embedded", "layout"]


def parse_pdf_with_llamaparse(
    pdf_path: str | Path,
    image_output_dir: str | Path | None = None,
    tier: str = "agentic",
    version: str = "latest",
    custom_prompt: str = DEFAULT_CUSTOM_PROMPT,
    ocr_languages: list[str] | None = None,
    include_images: bool = True,
    timeout: float = 7200.0,
) -> tuple[list[dict], list[dict]]:
    """Parse a PDF with LlamaParse and return text pages plus image records."""
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF file does not exist: {pdf_path}")

    api_key = os.getenv("LLAMA_CLOUD_API_KEY")
    if not api_key:
        raise RuntimeError("Set LLAMA_CLOUD_API_KEY before parsing PDFs with LlamaParse.")

    from llama_cloud import LlamaCloud

    client = LlamaCloud(api_key=api_key)
    expand = ["markdown", "metadata", "items"]
    if include_images:
        expand.append("images_content_metadata")

    print(f"Parsing PDF with LlamaParse: {pdf_path}")
    result = client.parsing.parse(
        upload_file=pdf_path,
        tier=tier, # fast | cost_effective | agentic | agentic_plus
        version=version,
        expand=expand,  
        agentic_options={"custom_prompt": custom_prompt},
        output_options=_output_options(include_images=include_images),
        processing_options=_processing_options(ocr_languages=ocr_languages),
        polling_interval=2.0,
        max_interval=20.0,
        timeout=timeout,
        backoff="linear",
        verbose=True,
    )

    pages = _build_text_pages(result=result, pdf_path=pdf_path)
    image_records = []
    if include_images:
        image_records = _build_image_records(
            result=result,
            pdf_path=pdf_path,
            output_dir=Path(image_output_dir) if image_output_dir is not None else image_output_path(pdf_path.stem),
        )

    print(
        f"LlamaParse returned {len(pages)} text pages and "
        f"{len(image_records)} downloaded images."
    )
    return pages, image_records


def _output_options(include_images: bool) -> dict:
    return {
        "images_to_save": DEFAULT_IMAGE_CATEGORIES if include_images else [],
        "markdown": {
            "inline_images": False,
            "tables": {
                "output_tables_as_markdown": True,
                "merge_continued_tables": True,
                "compact_markdown_tables": True,
            },
        },
    }


def _processing_options(ocr_languages: list[str] | None) -> dict:
    options = {"aggressive_table_extraction": True}
    if ocr_languages:
        options["ocr_parameters"] = {"languages": ocr_languages}
    return options


def _build_text_pages(result, pdf_path: Path) -> list[dict]:
    if result.markdown is None:
        raise RuntimeError("LlamaParse result did not include markdown output.")

    metadata_by_page = {
        page.page_number: page
        for page in (result.metadata.pages if result.metadata is not None else [])
    }

    pages = []
    for page in result.markdown.pages:
        if not page.success:
            print(f"Skipping failed LlamaParse page {page.page_number}: {page.error}")
            continue

        page_metadata = metadata_by_page.get(page.page_number)
        metadata = {
            "source_pdf": str(pdf_path),
            "file_name": pdf_path.name,
            "paper_id": pdf_path.stem,
            "page_number": page.page_number,
            "parser": "llamaparse",
        }
        if page_metadata is not None:
            metadata.update(
                {
                    "confidence": page_metadata.confidence,
                    "printed_page_number": page_metadata.printed_page_number,
                }
            )

        pages.append({"text": page.markdown, "metadata": metadata})

    return pages


def _build_image_records(result, pdf_path: Path, output_dir: Path) -> list[dict]:
    if result.items is None:
        print("LlamaParse result did not include structured items; skipping images.")
        return []

    output_dir.mkdir(parents=True, exist_ok=True)
    image_metadata_by_filename = _image_metadata_by_filename(result)
    image_records = []
    seen_sources = set()

    for page in result.items.pages:
        if not page.success:
            continue

        image_index = 0
        for item in page.items:
            if getattr(item, "type", None) != "image":
                continue

            image_url = _resolve_image_url(item, image_metadata_by_filename)
            if not image_url:
                print(f"Skipping image on page {page.page_number}: no download URL.")
                continue

            source_key = (page.page_number, image_url)
            if source_key in seen_sources:
                continue
            seen_sources.add(source_key)

            image_index += 1
            image_path, content_type = _download_llamaparse_image(
                url=image_url,
                output_dir=output_dir,
                page_number=page.page_number,
                image_index=image_index,
            )

            source_anchor = (
                f"{pdf_path.stem}:page:{page.page_number}:"
                f"llamaparse_image:{image_index}"
            )
            image_records.append(
                {
                    "image_path": image_path,
                    "paper_id": pdf_path.stem,
                    "file_name": pdf_path.name,
                    "page_number": page.page_number,
                    "image_index": image_index,
                    "source_anchor": source_anchor,
                    "source_type": "llamaparse_image",
                    "caption": getattr(item, "caption", "") or "",
                    "content_type": content_type,
                    "bbox": _dump_bbox(getattr(item, "bbox", None)),
                }
            )

    return image_records


def _image_metadata_by_filename(result) -> dict[str, object]:
    if result.images_content_metadata is None:
        return {}

    return {
        image.filename: image
        for image in result.images_content_metadata.images
        if image.filename
    }


def _resolve_image_url(item, image_metadata_by_filename: dict[str, object]) -> str | None:
    item_url = getattr(item, "url", None)
    if item_url and _is_http_url(item_url):
        return item_url

    filename = _filename_from_url(item_url) if item_url else None
    if filename:
        image_metadata = image_metadata_by_filename.get(filename)
        if image_metadata is not None and image_metadata.presigned_url:
            return image_metadata.presigned_url

    markdown_url = _markdown_image_url(getattr(item, "md", ""))
    if markdown_url and _is_http_url(markdown_url):
        return markdown_url

    filename = _filename_from_url(markdown_url) if markdown_url else None
    if filename:
        image_metadata = image_metadata_by_filename.get(filename)
        if image_metadata is not None and image_metadata.presigned_url:
            return image_metadata.presigned_url

    return None


def _download_llamaparse_image(
    url: str,
    output_dir: Path,
    page_number: int,
    image_index: int,
) -> tuple[Path, str]:
    with httpx.Client(follow_redirects=True, timeout=60.0) as client:
        response = client.get(url)
        response.raise_for_status()

    content_type = response.headers.get("content-type", "").split(";")[0].strip()
    suffix = _image_suffix(url=url, content_type=content_type)
    image_path = output_dir / f"page_{page_number}_img_{image_index}{suffix}"
    image_path.write_bytes(response.content)

    return image_path, content_type or mimetypes.guess_type(image_path.name)[0] or "image/png"


def _image_suffix(url: str, content_type: str) -> str:
    filename = _filename_from_url(url)
    if filename:
        suffix = Path(filename).suffix
        if suffix:
            return suffix

    return mimetypes.guess_extension(content_type) or ".png"


def _filename_from_url(url: str | None) -> str | None:
    if not url:
        return None

    path = unquote(urlparse(url).path)
    filename = Path(path).name
    return filename or None


def _markdown_image_url(markdown: str) -> str | None:
    match = re.search(r"!\[[^\]]*\]\(([^)]+)\)", markdown or "")
    if not match:
        return None
    return match.group(1).strip()


def _is_http_url(url: str) -> bool:
    scheme = urlparse(url).scheme.lower()
    return scheme in {"http", "https"}


def _dump_bbox(bbox) -> list[dict] | None:
    if not bbox:
        return None

    dumped = []
    for box in bbox:
        if hasattr(box, "model_dump"):
            dumped.append(box.model_dump())
        elif isinstance(box, dict):
            dumped.append(box)

    return dumped or None
