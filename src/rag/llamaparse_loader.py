"""LlamaParse-based PDF loader for text, markdown, and extracted images."""

from __future__ import annotations

import mimetypes
import os
import re
from pathlib import Path
from urllib.parse import unquote, urlparse

import httpx

from app_config import load_app_config
from app_config.config import (
    DEFAULT_LLAMAPARSE_CUSTOM_PROMPT,
    DEFAULT_LLAMAPARSE_IMAGE_CATEGORIES,
)

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

if load_dotenv is not None:
    load_dotenv()

DEFAULT_CUSTOM_PROMPT = DEFAULT_LLAMAPARSE_CUSTOM_PROMPT
DEFAULT_IMAGE_CATEGORIES = DEFAULT_LLAMAPARSE_IMAGE_CATEGORIES


def parse_pdf_with_llamaparse(
    pdf_path: str | Path,
    image_output_dir: str | Path | None = None,
    tier: str | None = None,
    version: str | None = None,
    custom_prompt: str | None = None,
    ocr_languages: list[str] | None = None,
    include_images: bool = True,
    timeout: float | None = None,
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

    rag_config = load_app_config().rag
    config = rag_config.llamaparse
    print(f"Parsing PDF with LlamaParse: {pdf_path}")
    result = client.parsing.parse(
        upload_file=pdf_path,
        tier=str(tier or config.tier).strip(), # fast | cost_effective | agentic | agentic_plus
        version=str(version or config.version).strip(),
        expand=expand,  
        agentic_options={"custom_prompt": str(custom_prompt or config.custom_prompt).strip()},
        output_options=_output_options(
            include_images=include_images,
            image_categories=config.image_categories,
        ),
        processing_options=_processing_options(
            ocr_languages=ocr_languages or list(config.ocr_languages) or None,
        ),
        polling_interval=config.polling_interval,
        max_interval=config.max_interval,
        timeout=max(1.0, float(timeout)) if timeout is not None else config.timeout,
        backoff="linear",
        verbose=True,
    )

    pages = _build_text_pages(result=result, pdf_path=pdf_path)
    image_records = []
    if include_images:
        _log_llamaparse_image_sources(result)
        image_records = _build_image_records(
            result=result,
            pdf_path=pdf_path,
            output_dir=Path(image_output_dir)
            if image_output_dir is not None
            else rag_config.image_output_path(pdf_path.stem),
            download_timeout=config.image_download_timeout,
        )

    print(
        f"LlamaParse returned {len(pages)} text pages and "
        f"{len(image_records)} downloaded images."
    )
    return pages, image_records


def _output_options(include_images: bool, *, image_categories: tuple[str, ...] = DEFAULT_IMAGE_CATEGORIES) -> dict:
    return {
        "images_to_save": list(image_categories) if include_images else [],
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


def _log_llamaparse_image_sources(result) -> None:
    metadata = getattr(result, "images_content_metadata", None)
    metadata_count = len(getattr(metadata, "images", []) or []) if metadata is not None else 0
    image_metadata_by_filename = _image_metadata_by_filename(result)
    item_count = sum(
        1
        for page in _successful_item_pages(result)
        for item in getattr(page, "items", []) or []
        if _is_image_item(item, image_metadata_by_filename)
    )
    markdown_count = sum(
        len(_markdown_image_urls(getattr(page, "markdown", "")))
        for page in (getattr(getattr(result, "markdown", None), "pages", []) or [])
        if getattr(page, "success", False)
    )
    print(
        "LlamaParse image sources: "
        f"{metadata_count} metadata images, {item_count} structured image items, "
        f"{markdown_count} markdown image references."
    )


def _build_image_records(result, pdf_path: Path, output_dir: Path, *, download_timeout: float) -> list[dict]:
    output_dir.mkdir(parents=True, exist_ok=True)
    image_metadata_by_filename = _image_metadata_by_filename(result)
    page_by_filename = _page_number_by_image_filename(result)
    image_records = []
    seen_sources = set()
    seen_filenames = set()

    for page in _successful_item_pages(result):
        if not page.success:
            continue

        image_index = 0
        for item in page.items:
            if not _is_image_item(item, image_metadata_by_filename):
                continue

            image_url = _resolve_image_url(item, image_metadata_by_filename)
            if not image_url:
                print(f"Skipping image on page {page.page_number}: no download URL.")
                continue

            filename = _image_item_filename(item)
            image_metadata = _image_metadata_for_filename(filename, image_metadata_by_filename)
            source_key = (page.page_number, filename or image_url)
            if source_key in seen_sources:
                continue
            seen_sources.add(source_key)
            if filename:
                seen_filenames.add(filename)

            image_index += 1
            image_path, content_type = _download_llamaparse_image(
                url=image_url,
                output_dir=output_dir,
                page_number=page.page_number,
                image_index=image_index,
                timeout=download_timeout,
                source_filename=filename,
            )

            image_records.append(
                _image_record(
                    pdf_path=pdf_path,
                    image_path=image_path,
                    page_number=page.page_number,
                    image_index=image_index,
                    caption_text=getattr(item, "caption", "") or "",
                    content_type=content_type or getattr(image_metadata, "content_type", "") or "",
                    bbox=_dump_bbox(getattr(item, "bbox", None)) or _dump_bbox(getattr(image_metadata, "bbox", None)),
                    category=getattr(image_metadata, "category", "") or "",
                    filename=filename,
                )
            )

    metadata_records = _build_metadata_image_records(
        result=result,
        pdf_path=pdf_path,
        output_dir=output_dir,
        download_timeout=download_timeout,
        page_by_filename=page_by_filename,
        seen_sources=seen_sources,
        seen_filenames=seen_filenames,
    )
    image_records.extend(metadata_records)

    if not image_records and getattr(result, "items", None) is None:
        print("LlamaParse result did not include structured items or downloadable image metadata.")

    return image_records


def _image_metadata_by_filename(result) -> dict[str, object]:
    metadata = getattr(result, "images_content_metadata", None)
    if metadata is None:
        return {}

    images = getattr(metadata, "images", []) or []
    image_metadata_by_filename = {}
    for image in images:
        for filename in _candidate_filenames(getattr(image, "filename", "")):
            image_metadata_by_filename[filename] = image

    return image_metadata_by_filename


def _successful_item_pages(result) -> list[object]:
    items = getattr(result, "items", None)
    if items is None:
        return []
    return [page for page in (getattr(items, "pages", []) or []) if getattr(page, "success", False)]


def _build_metadata_image_records(
    *,
    result,
    pdf_path: Path,
    output_dir: Path,
    download_timeout: float,
    page_by_filename: dict[str, int],
    seen_sources: set,
    seen_filenames: set,
) -> list[dict]:
    metadata = getattr(result, "images_content_metadata", None)
    if metadata is None:
        return []

    image_records = []
    for metadata_index, image_metadata in enumerate(getattr(metadata, "images", []) or [], start=1):
        filename = _first_candidate_filename(getattr(image_metadata, "filename", ""))
        if filename and filename in seen_filenames:
            continue

        image_url = getattr(image_metadata, "presigned_url", "") or ""
        if not image_url:
            print(f"Skipping LlamaParse image metadata {filename or metadata_index}: no download URL.")
            continue

        page_number = _resolve_llamaparse_image_page(
            image_metadata,
            filename=filename,
            image_url=image_url,
            page_by_filename=page_by_filename,
        )
        image_index = _metadata_image_index(image_metadata, fallback=metadata_index)
        source_key = (page_number, filename or image_url)
        if source_key in seen_sources:
            continue
        seen_sources.add(source_key)
        if filename:
            seen_filenames.add(filename)

        image_path, content_type = _download_llamaparse_image(
            url=image_url,
            output_dir=output_dir,
            page_number=page_number,
            image_index=image_index,
            timeout=download_timeout,
            source_filename=filename,
        )
        image_records.append(
            _image_record(
                pdf_path=pdf_path,
                image_path=image_path,
                page_number=page_number,
                image_index=image_index,
                caption_text="",
                content_type=content_type or getattr(image_metadata, "content_type", "") or "",
                bbox=_dump_bbox(getattr(image_metadata, "bbox", None)),
                category=getattr(image_metadata, "category", "") or "",
                filename=filename,
            )
        )

    return image_records


def _image_record(
    *,
    pdf_path: Path,
    image_path: Path,
    page_number: int | None,
    image_index: int,
    caption_text: str,
    content_type: str,
    bbox: list[dict] | None,
    category: str = "",
    filename: str | None = None,
) -> dict:
    page_anchor = f"page:{page_number}" if page_number is not None else "page:unknown"
    source_anchor = f"{pdf_path.stem}:{page_anchor}:llamaparse_image:{image_index}"
    return {
        "image_path": image_path,
        "paper_id": pdf_path.stem,
        "file_name": pdf_path.name,
        "page_number": page_number,
        "image_index": image_index,
        "source_anchor": source_anchor,
        "source_type": "llamaparse_image",
        "caption": caption_text,
        "caption_text": caption_text,
        "content_type": content_type,
        "bbox": bbox,
        "category": category,
        "filename": filename or "",
    }


def _is_image_item(item, image_metadata_by_filename: dict[str, object]) -> bool:
    if getattr(item, "type", None) == "image":
        return True
    if item.__class__.__name__.lower() == "imageitem":
        return True

    filename = _image_item_filename(item)
    return bool(filename and _image_metadata_for_filename(filename, image_metadata_by_filename))


def _image_item_filename(item) -> str | None:
    for value in _image_item_urls(item):
        filename = _filename_from_url(value)
        if filename:
            return filename
    return None


def _image_item_urls(item) -> list[str]:
    urls = []
    for attr in ("url", "image_url", "imageUrl", "src"):
        value = getattr(item, attr, None)
        if isinstance(value, str) and value.strip():
            urls.append(value.strip())
    urls.extend(_markdown_image_urls(getattr(item, "md", "")))
    return urls


def _image_metadata_for_filename(filename: str | None, image_metadata_by_filename: dict[str, object]) -> object | None:
    for candidate in _candidate_filenames(filename or ""):
        image_metadata = image_metadata_by_filename.get(candidate)
        if image_metadata is not None:
            return image_metadata
    return None


def _resolve_image_url(item, image_metadata_by_filename: dict[str, object]) -> str | None:
    for image_url in _image_item_urls(item):
        if _is_http_url(image_url):
            return image_url

        image_metadata = _image_metadata_for_filename(_filename_from_url(image_url), image_metadata_by_filename)
        if image_metadata is not None and getattr(image_metadata, "presigned_url", ""):
            return image_metadata.presigned_url

    return None


def _download_llamaparse_image(
    url: str,
    output_dir: Path,
    page_number: int | None,
    image_index: int,
    *,
    timeout: float,
    source_filename: str | None = None,
) -> tuple[Path, str]:
    with httpx.Client(follow_redirects=True, timeout=timeout) as client:
        response = client.get(url)
        response.raise_for_status()

    content_type = response.headers.get("content-type", "").split(";")[0].strip()
    suffix = _image_suffix(url=url, content_type=content_type, source_filename=source_filename)
    page_part = f"page_{page_number}" if page_number is not None else "page_unknown"
    image_path = output_dir / f"{page_part}_img_{image_index}{suffix}"
    image_path.write_bytes(response.content)

    return image_path, content_type or mimetypes.guess_type(image_path.name)[0] or "image/png"


def _image_suffix(url: str, content_type: str, source_filename: str | None = None) -> str:
    filename = source_filename or _filename_from_url(url)
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


def _markdown_image_urls(markdown: str) -> list[str]:
    image_urls = []
    for match in re.finditer(r"!\[[^\]]*\]\(([^)]+)\)", markdown or ""):
        image_url = _clean_markdown_image_url(match.group(1))
        if image_url:
            image_urls.append(image_url)
    return image_urls


def _clean_markdown_image_url(value: str) -> str:
    url = (value or "").strip()
    if url.startswith("<") and ">" in url:
        return url[1:url.index(">")].strip()

    match = re.match(r"^(.+?)\s+['\"].*['\"]$", url)
    if match:
        return match.group(1).strip()
    return url


def _page_number_by_image_filename(result) -> dict[str, int]:
    page_by_filename = {}
    markdown = getattr(result, "markdown", None)
    for page in getattr(markdown, "pages", []) or []:
        if not getattr(page, "success", False):
            continue
        for image_url in _markdown_image_urls(getattr(page, "markdown", "")):
            for filename in _candidate_filenames(image_url):
                page_by_filename[filename] = page.page_number

    for page in _successful_item_pages(result):
        for item in getattr(page, "items", []) or []:
            filename = _image_item_filename(item)
            if filename:
                page_by_filename[filename] = page.page_number

    return page_by_filename


def _candidate_filenames(value: str) -> list[str]:
    if not value:
        return []

    decoded = unquote(str(value).strip())
    candidates = [decoded]
    filename = _filename_from_url(decoded)
    if filename and filename not in candidates:
        candidates.append(filename)

    return [candidate for candidate in candidates if candidate]


def _first_candidate_filename(value: str) -> str | None:
    candidates = _candidate_filenames(value)
    return candidates[-1] if candidates else None


def _metadata_image_index(image_metadata, *, fallback: int) -> int:
    try:
        return int(getattr(image_metadata, "index", fallback)) + 1
    except (TypeError, ValueError):
        return fallback


def _resolve_llamaparse_image_page(
    image_metadata,
    *,
    filename: str | None,
    image_url: str | None,
    page_by_filename: dict[str, int],
) -> int | None:
    metadata_page_number = _page_number_from_metadata(image_metadata)
    if metadata_page_number is not None:
        return metadata_page_number

    for value in (filename, image_url):
        for candidate in _candidate_filenames(value or ""):
            if candidate in page_by_filename:
                return page_by_filename[candidate]

            page_number = _page_number_from_filename(candidate)
            if page_number is not None:
                return page_number

    return None


def _page_number_from_metadata(image_metadata) -> int | None:
    page_number = _first_int_field(
        image_metadata,
        (
            "page_number",
            "pageNumber",
            "page_num",
            "pageNum",
            "page",
            "pdf_page",
            "pdfPage",
        ),
    )
    if page_number is not None and page_number > 0:
        return page_number

    page_index = _first_int_field(
        image_metadata,
        (
            "page_index",
            "pageIndex",
            "page_idx",
            "pageIdx",
        ),
    )
    if page_index is not None and page_index >= 0:
        return page_index + 1

    for bbox in _bbox_items(getattr(image_metadata, "bbox", None)):
        page_number = _page_number_from_metadata(bbox)
        if page_number is not None:
            return page_number

    return None


def _first_int_field(source, field_names: tuple[str, ...]) -> int | None:
    for field_name in field_names:
        value = _field_value(source, field_name)
        if value is None:
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return None


def _field_value(source, field_name: str):
    if isinstance(source, dict):
        return source.get(field_name)
    return getattr(source, field_name, None)


def _bbox_items(bbox) -> list:
    if not bbox:
        return []
    if hasattr(bbox, "model_dump"):
        return [bbox.model_dump()]
    if isinstance(bbox, dict):
        return [bbox]
    if isinstance(bbox, (list, tuple)):
        return list(bbox)
    return [bbox]


def _page_number_from_filename(filename: str | None) -> int | None:
    match = re.search(r"(?<![A-Za-z0-9])page[_-]?(\d+)(?!\d)", filename or "", flags=re.IGNORECASE)
    if not match:
        return None
    return int(match.group(1))


def _is_http_url(url: str) -> bool:
    scheme = urlparse(url).scheme.lower()
    return scheme in {"http", "https"}


def _dump_bbox(bbox) -> list[dict] | None:
    if not bbox:
        return None

    if hasattr(bbox, "model_dump"):
        return [bbox.model_dump()]
    if isinstance(bbox, dict):
        return [bbox]

    dumped = []
    for box in bbox:
        if hasattr(box, "model_dump"):
            dumped.append(box.model_dump())
        elif isinstance(box, dict):
            dumped.append(box)

    return dumped or None
