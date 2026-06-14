from __future__ import annotations

import base64
import copy
import json
import re
from email.utils import unquote as unquote_header
from pathlib import Path
from typing import Any
from urllib.parse import quote as url_quote
from urllib.parse import unquote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from xml.etree import ElementTree

from app_config import load_app_config
from app_infra.formatting import (
    finite_number,
    get_today_label,
    normalize_text,
    note_id_from_title,
    note_title_from_pdf,
    resource_href,
    safe_file_name,
)
from library.note_html import create_paper_note_html, update_note_html_title
from app_infra.paths import HTML_DIR, HTML_HREF_PREFIX, NOTES_PATH, PAPERS_DIR, PAPERS_HREF_PREFIX
from app_infra.storage import atomic_write_json, atomic_write_text


ALL_CATEGORY_ID = "all"
UNCATEGORIZED_ID = "uncategorized"
ARXIV_ID_PATTERN = re.compile(r"^(?:arxiv:\s*)?([a-z-]+(?:\.[A-Z]{2})?/\d{7}(?:v\d+)?|\d{4}\.\d{4,5}(?:v\d+)?)$", re.IGNORECASE)
DOI_PATTERN = re.compile(r"^(?:doi:\s*)?(10\.\d{4,9}/\S+)$", re.IGNORECASE)

BASE_LIBRARY = {
    "categories": [
        {"id": ALL_CATEGORY_ID, "name": "All Notes", "parentId": None, "order": 0, "system": True},
        {"id": UNCATEGORIZED_ID, "name": "Uncategorized", "parentId": None, "order": 1, "system": True},
    ],
    "notes": [],
}


def normalize_tags(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [tag for tag in (normalize_text(item) for item in value) if tag]


def normalize_resource_href(value: Any) -> str:
    href = normalize_text(value)
    if not href:
        return ""
    if href.startswith("resources/"):
        return href
    if href.startswith(("Papers/", "Paper-html/", "Paper-annotations/")):
        return f"resources/{href}"
    return href


def sanitize_library(raw_library: Any) -> dict[str, Any]:
    raw = raw_library if isinstance(raw_library, dict) else {}
    raw_categories = raw.get("categories") if isinstance(raw.get("categories"), list) else []
    category_map: dict[str, dict[str, Any]] = {}

    for index, category in enumerate(raw_categories):
        if not isinstance(category, dict):
            continue
        category_id = normalize_text(category.get("id"))
        if not category_id or category_id in category_map:
            continue
        category_map[category_id] = {
            "id": category_id,
            "name": normalize_text(category.get("name")) or "Untitled",
            "parentId": normalize_text(category.get("parentId")) or None,
            "order": finite_number(category.get("order"), index),
            "system": bool(category.get("system")),
        }

    for category in BASE_LIBRARY["categories"]:
        category_map[category["id"]] = dict(category)

    categories = []
    for category in category_map.values():
        if category["id"] == ALL_CATEGORY_ID:
            categories.append({**category, "parentId": None, "order": 0, "system": True})
        elif category["id"] == UNCATEGORIZED_ID:
            categories.append({**category, "parentId": None, "order": 1, "system": True})
        else:
            categories.append(category)

    valid_ids = {category["id"] for category in categories}
    for category in categories:
        if category.get("parentId") and category["parentId"] not in valid_ids:
            category["parentId"] = None
        if category.get("parentId") in {ALL_CATEGORY_ID, UNCATEGORIZED_ID}:
            category["parentId"] = None

    top_level_ids = {category["id"] for category in categories if category.get("parentId") is None}
    for category in categories:
        if category.get("parentId") and category["parentId"] not in top_level_ids:
            category["parentId"] = None

    child_map: dict[str, list[dict[str, Any]]] = {}
    for category in categories:
        key = category.get("parentId") or "root"
        child_map.setdefault(key, []).append(category)

    for group in child_map.values():
        group.sort(key=lambda category: (category.get("order", 0), category.get("name", "")))
        for index, category in enumerate(group):
            if category.get("parentId") is None:
                if category["id"] == ALL_CATEGORY_ID:
                    category["order"] = 0
                elif category["id"] == UNCATEGORIZED_ID:
                    category["order"] = 1
                else:
                    category["order"] = max(index, 2)
            else:
                category["order"] = index

    parent_ids_with_children = {category["parentId"] for category in categories if category.get("parentId")}
    leaf_ids = {category["id"] for category in categories if category["id"] not in parent_ids_with_children}

    raw_notes = raw.get("notes") if isinstance(raw.get("notes"), list) else []
    notes = []
    for index, note in enumerate(raw_notes):
        if not isinstance(note, dict):
            continue
        requested_category_id = normalize_text(note.get("categoryId"))
        notes.append(
            {
                "id": normalize_text(note.get("id")) or note_id_from_title(note.get("title") or f"note-{index + 1}"),
                "title": normalize_text(note.get("title")) or "Untitled Note",
                "href": normalize_resource_href(note.get("href")),
                "htmlHref": normalize_resource_href(note.get("htmlHref")),
                "pdfStorageKey": normalize_text(note.get("pdfStorageKey")),
                "sourceUrl": normalize_text(note.get("sourceUrl")),
                "date": normalize_text(note.get("date")),
                "order": finite_number(note.get("order"), index),
                "categoryId": requested_category_id if requested_category_id in leaf_ids else UNCATEGORIZED_ID,
                "venue": normalize_text(note.get("venue")),
                "summary": normalize_text(note.get("summary")),
                "tags": normalize_tags(note.get("tags")),
            }
        )

    return {"categories": categories, "notes": notes}


def read_library(path: Path = NOTES_PATH) -> dict[str, Any]:
    try:
        return sanitize_library(json.loads(path.read_text(encoding="utf-8")))
    except Exception:
        return copy.deepcopy(BASE_LIBRARY)


def write_library(library: dict[str, Any], path: Path = NOTES_PATH) -> dict[str, Any]:
    sanitized = sanitize_library(library)
    atomic_write_json(path, sanitized)
    return sanitized


def find_note(library: dict[str, Any], note_id: str) -> dict[str, Any] | None:
    return next((entry for entry in library.get("notes", []) if entry.get("id") == note_id), None)


def import_pdf(body: dict[str, Any]) -> dict[str, Any]:
    original_name = safe_file_name(body.get("fileName"))
    if not original_name.lower().endswith(".pdf"):
        raise ValueError("Only PDF files can be imported.")

    try:
        pdf_data = base64.b64decode(str(body.get("dataBase64") or ""), validate=False)
    except Exception:
        pdf_data = b""
    if not pdf_data:
        raise ValueError("PDF file is empty.")

    return _import_pdf_bytes(
        file_name=original_name,
        pdf_data=pdf_data,
        category_id=normalize_text(body.get("categoryId")) or UNCATEGORIZED_ID,
        source_url=normalize_text(body.get("sourceUrl")),
    )


def import_pdf_from_url(body: dict[str, Any]) -> dict[str, Any]:
    source = normalize_text(body.get("url") or body.get("sourceUrl") or body.get("doi"))
    if not source:
        raise ValueError("A DOI, arXiv link, or PDF URL is required.")

    pdf_url = resolve_paper_pdf_url(source)
    pdf_data, file_name, final_url = download_paper_pdf(pdf_url)
    title_override = title_from_remote_paper(source=source, pdf_url=pdf_url, final_url=final_url, pdf_data=pdf_data)
    return _import_pdf_bytes(
        file_name=file_name,
        pdf_data=pdf_data,
        category_id=normalize_text(body.get("categoryId")) or UNCATEGORIZED_ID,
        source_url=final_url or pdf_url,
        title_override=title_override,
    )


def _import_pdf_bytes(
    *,
    file_name: str,
    pdf_data: bytes,
    category_id: str,
    source_url: str = "",
    title_override: str = "",
) -> dict[str, Any]:
    original_name = safe_file_name(file_name)
    if not original_name.lower().endswith(".pdf"):
        original_name = f"{Path(original_name).stem or 'Untitled Paper'}.pdf"
    if not pdf_data:
        raise ValueError("PDF file is empty.")
    if not looks_like_pdf(pdf_data):
        raise ValueError("The imported file is not a valid PDF.")

    PAPERS_DIR.mkdir(parents=True, exist_ok=True)
    HTML_DIR.mkdir(parents=True, exist_ok=True)

    html_name = f"{Path(original_name).stem}.html"
    title = normalize_paper_title(title_override) or note_title_from_pdf(original_name)
    date = get_today_label()
    pdf_href = resource_href(PAPERS_HREF_PREFIX, original_name)
    html_href = resource_href(HTML_HREF_PREFIX, html_name)
    library = read_library(NOTES_PATH)
    library["categories"] = library.get("categories") if isinstance(library.get("categories"), list) else copy.deepcopy(BASE_LIBRARY["categories"])
    library["notes"] = library.get("notes") if isinstance(library.get("notes"), list) else []

    existing_notes = [entry for entry in library["notes"] if entry.get("href") != pdf_href and entry.get("htmlHref") != html_href]
    next_order = max((finite_number(note.get("order"), index) for index, note in enumerate(existing_notes)), default=-1) + 1
    note = {
        "id": note_id_from_title(title),
        "title": title,
        "href": pdf_href,
        "htmlHref": html_href,
        "pdfStorageKey": "",
        "sourceUrl": source_url,
        "date": date,
        "order": next_order,
        "categoryId": category_id,
        "venue": "",
        "summary": "",
        "tags": [],
    }

    outline = extract_pdf_outline(pdf_data, title=title)
    pdf_path = PAPERS_DIR / original_name
    pdf_path.write_bytes(pdf_data)
    atomic_write_text(HTML_DIR / html_name, create_paper_note_html(title, date, original_name, outline=outline))

    library["notes"] = [*existing_notes, note]
    write_library(library, NOTES_PATH)
    return note


def title_from_remote_paper(*, source: str, pdf_url: str, final_url: str, pdf_data: bytes) -> str:
    for value in (source, pdf_url, final_url):
        arxiv_id = arxiv_id_from_text(value) or arxiv_id_from_url(value)
        if not arxiv_id:
            doi = doi_from_text(value)
            if doi:
                arxiv_id = arxiv_id_from_doi(doi)
        if not arxiv_id:
            continue
        title = fetch_arxiv_title(arxiv_id)
        if title:
            return title
    return title_from_pdf_metadata(pdf_data)


def fetch_arxiv_title(arxiv_id: str) -> str:
    clean_id = normalize_text(arxiv_id)
    if not clean_id:
        return ""
    api_url = f"https://export.arxiv.org/api/query?id_list={url_quote(clean_id, safe='/')}"
    try:
        response = requests.get(api_url, headers=remote_fetch_headers(), timeout=arxiv_fetch_timeout_seconds())
        response.raise_for_status()
    except Exception:
        return ""
    try:
        root = ElementTree.fromstring(response.content)
    except Exception:
        return ""
    namespace = {"atom": "http://www.w3.org/2005/Atom"}
    title_node = root.find("atom:entry/atom:title", namespace)
    return normalize_paper_title(title_node.text if title_node is not None else "")


def title_from_pdf_metadata(pdf_data: bytes) -> str:
    try:
        import pymupdf  # type: ignore[import-not-found]
    except Exception:
        return ""
    try:
        document = pymupdf.open(stream=pdf_data, filetype="pdf")
    except Exception:
        return ""
    try:
        metadata = document.metadata or {}
        return normalize_paper_title(metadata.get("title"))
    finally:
        document.close()


def normalize_paper_title(value: Any) -> str:
    title = re.sub(r"\s+", " ", normalize_text(value)).strip()
    if not title:
        return ""
    generic = title.lower().strip(" ._-")
    if generic in {"untitled", "untitled paper", "paper", "arxiv"}:
        return ""
    if arxiv_id_from_text(title):
        return ""
    if len(title) > 240:
        return ""
    return title


def resolve_paper_pdf_url(source: str) -> str:
    value = normalize_text(source).strip("<>\"'")
    if not value:
        raise ValueError("A DOI, arXiv link, or PDF URL is required.")

    arxiv_id = arxiv_id_from_text(value)
    if arxiv_id:
        return arxiv_pdf_url(arxiv_id)

    doi = doi_from_text(value)
    if doi:
        doi_arxiv_id = arxiv_id_from_doi(doi)
        if doi_arxiv_id:
            return arxiv_pdf_url(doi_arxiv_id)
        return f"https://doi.org/{doi}"

    if not re.match(r"^[a-z][a-z0-9+.-]*://", value, flags=re.IGNORECASE):
        if re.match(r"^[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?:/.*)?$", value):
            value = f"https://{value}"
        else:
            raise ValueError("Enter a DOI, arXiv link, or http(s) PDF URL.")

    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Only http(s) paper links are supported.")
    if parsed.hostname and parsed.hostname.lower() in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("Localhost URLs are not supported for link imports. Use local PDF import instead.")

    arxiv_url_id = arxiv_id_from_url(value)
    if arxiv_url_id:
        return arxiv_pdf_url(arxiv_url_id)
    return value


def arxiv_id_from_text(value: str) -> str:
    candidate = normalize_text(value).strip()
    match = ARXIV_ID_PATTERN.match(candidate)
    return match.group(1) if match else ""


def doi_from_text(value: str) -> str:
    candidate = normalize_text(value).strip()
    parsed = urlparse(candidate if re.match(r"^[a-z][a-z0-9+.-]*://", candidate, flags=re.IGNORECASE) else "")
    if parsed.netloc.lower() in {"doi.org", "dx.doi.org"} and parsed.path.strip("/"):
        candidate = unquote(parsed.path.strip("/"))
    match = DOI_PATTERN.match(candidate)
    return match.group(1).rstrip(".,;") if match else ""


def arxiv_id_from_doi(doi: str) -> str:
    match = re.match(r"10\.48550/arxiv\.(?P<arxiv_id>.+)$", doi, flags=re.IGNORECASE)
    return match.group("arxiv_id") if match else ""


def arxiv_id_from_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.netloc.lower() not in {"arxiv.org", "www.arxiv.org"}:
        return ""
    parts = [unquote(part) for part in parsed.path.split("/") if part]
    if len(parts) >= 2 and parts[0].lower() in {"abs", "pdf"}:
        candidate = parts[1]
        if candidate.lower().endswith(".pdf"):
            candidate = candidate[:-4]
        return arxiv_id_from_text(candidate)
    return ""


def arxiv_pdf_url(arxiv_id: str) -> str:
    clean_id = arxiv_id.strip()
    if clean_id.lower().endswith(".pdf"):
        clean_id = clean_id[:-4]
    return f"https://arxiv.org/pdf/{url_quote(clean_id, safe='/')}.pdf"


def download_paper_pdf(url: str) -> tuple[bytes, str, str]:
    session = requests.Session()
    response = _get_remote(session, url)
    try:
        if response_is_pdf(response):
            data = _read_limited_response(response, max_remote_pdf_bytes())
            if not looks_like_pdf(data):
                raise ValueError("The link returned data, but it was not a valid PDF.")
            return data, file_name_from_response(response), response.url

        html = _read_limited_response(response, max_remote_html_bytes())
        candidates = pdf_candidates_from_html(html, response.url)
        for candidate in candidates[:8]:
            pdf_response = None
            try:
                pdf_response = _get_remote(session, candidate)
                if not response_is_pdf(pdf_response):
                    continue
                data = _read_limited_response(pdf_response, max_remote_pdf_bytes())
                if looks_like_pdf(data):
                    return data, file_name_from_response(pdf_response), pdf_response.url
            except Exception:
                continue
            finally:
                if pdf_response is not None:
                    pdf_response.close()
    finally:
        response.close()

    raise ValueError("Could not find a downloadable PDF from this link. Try an arXiv link or a direct PDF URL.")


def _get_remote(session: requests.Session, url: str) -> requests.Response:
    response = session.get(
        url,
        headers=remote_fetch_headers(),
        timeout=remote_fetch_timeout_seconds(),
        allow_redirects=True,
        stream=True,
    )
    response.raise_for_status()
    return response


def response_is_pdf(response: requests.Response) -> bool:
    content_type = response.headers.get("Content-Type", "").split(";")[0].strip().lower()
    path = unquote(urlparse(response.url).path).lower()
    disposition = response.headers.get("Content-Disposition", "").lower()
    return content_type == "application/pdf" or path.endswith(".pdf") or ".pdf" in disposition


def _read_limited_response(response: requests.Response, max_bytes: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    for chunk in response.iter_content(chunk_size=remote_fetch_chunk_size()):
        if not chunk:
            continue
        total += len(chunk)
        if total > max_bytes:
            raise ValueError("Downloaded content is too large.")
        chunks.append(chunk)
    return b"".join(chunks)


def looks_like_pdf(data: bytes) -> bool:
    return b"%PDF-" in data[:1024]


def max_remote_pdf_bytes() -> int:
    return load_app_config().library.import_settings.max_pdf_bytes


def max_remote_html_bytes() -> int:
    return load_app_config().library.import_settings.max_html_bytes


def remote_fetch_timeout_seconds() -> float:
    return load_app_config().library.import_settings.timeout_seconds


def arxiv_fetch_timeout_seconds() -> float:
    return load_app_config().library.import_settings.arxiv_timeout_seconds


def remote_fetch_chunk_size() -> int:
    return load_app_config().library.import_settings.chunk_size


def remote_fetch_headers() -> dict[str, str]:
    return load_app_config().library.import_settings.headers()


def file_name_from_response(response: requests.Response) -> str:
    disposition = response.headers.get("Content-Disposition", "")
    for pattern in (r"filename\*=UTF-8''([^;]+)", r'filename="([^"]+)"', r"filename=([^;]+)"):
        match = re.search(pattern, disposition, flags=re.IGNORECASE)
        if match:
            file_name = unquote_header(unquote(match.group(1).strip()))
            if file_name:
                return _ensure_pdf_file_name(file_name)

    path_name = Path(unquote(urlparse(response.url).path)).name
    return _ensure_pdf_file_name(path_name or "paper.pdf")


def _ensure_pdf_file_name(file_name: str) -> str:
    safe_name = safe_file_name(file_name)
    if not safe_name.lower().endswith(".pdf"):
        safe_name = f"{Path(safe_name).stem or 'paper'}.pdf"
    return safe_name


def pdf_candidates_from_html(html: bytes, base_url: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    candidates: list[str] = []

    for meta_name in ("citation_pdf_url", "bepress_citation_pdf_url", "dc.identifier", "DC.Identifier"):
        for meta in soup.find_all("meta"):
            name = normalize_text(meta.get("name") or meta.get("property"))
            if name.casefold() != meta_name.casefold():
                continue
            content = normalize_text(meta.get("content"))
            if content and (content.lower().endswith(".pdf") or "pdf" in content.lower()):
                candidates.append(urljoin(base_url, content))

    for link in soup.find_all(["a", "link"]):
        href = normalize_text(link.get("href"))
        if not href:
            continue
        label = normalize_text(link.get_text(" ", strip=True))
        rel = " ".join(link.get("rel") or []) if isinstance(link.get("rel"), list) else normalize_text(link.get("rel"))
        href_lower = href.lower()
        signal = " ".join([href_lower, label.lower(), rel.lower()])
        if ".pdf" in href_lower or "pdf" in signal:
            candidates.append(urljoin(base_url, href))

    seen: set[str] = set()
    unique_candidates: list[str] = []
    for candidate in candidates:
        parsed = urlparse(candidate)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            continue
        key = candidate.rstrip("/")
        if key in seen:
            continue
        seen.add(key)
        unique_candidates.append(candidate)
    return unique_candidates


def extract_pdf_outline(pdf_data: bytes, *, title: str = "") -> list[dict[str, Any]]:
    try:
        import pymupdf  # type: ignore[import-not-found]
    except Exception:
        return []

    try:
        document = pymupdf.open(stream=pdf_data, filetype="pdf")
    except Exception:
        return []
    try:
        toc = document.get_toc(simple=True)
        outline = _outline_from_pdf_toc(toc, title=title)
        if outline:
            return outline
        return _outline_from_pdf_text(document, title=title)
    finally:
        document.close()


def _outline_from_pdf_toc(toc: list[Any], *, title: str = "") -> list[dict[str, Any]]:
    outline: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in toc:
        if not isinstance(entry, (list, tuple)) or len(entry) < 2:
            continue
        level = _outline_level(entry[0])
        heading = _clean_outline_heading(entry[1], title=title)
        if not heading:
            continue
        key = heading.casefold()
        if key in seen:
            continue
        seen.add(key)
        outline.append({"level": level, "title": heading})
        if len(outline) >= 80:
            break
    return outline


def _outline_from_pdf_text(document: Any, *, title: str = "") -> list[dict[str, Any]]:
    outline: list[dict[str, Any]] = []
    seen: set[str] = set()
    max_pages = min(len(document), 10)
    for page_index in range(max_pages):
        try:
            lines = (document[page_index].get_text("text") or "").splitlines()
        except Exception:
            continue
        for raw_line in lines:
            candidate = _heading_candidate_from_line(raw_line, title=title)
            if candidate is None:
                continue
            key = candidate["title"].casefold()
            if key in seen:
                continue
            seen.add(key)
            outline.append(candidate)
            if len(outline) >= 40:
                return outline
    return outline


def _heading_candidate_from_line(raw_line: Any, *, title: str = "") -> dict[str, Any] | None:
    line = normalize_text(raw_line)
    if not line:
        return None
    line = re.sub(r"\s+", " ", line)
    line = re.sub(r"^(?:chapter|section)\s+", "", line, flags=re.IGNORECASE).strip()
    if len(line) < 3 or len(line) > 140:
        return None
    if _clean_outline_heading(line, title=title) != line:
        return None

    numbered = re.match(r"^(?P<number>(?:\d+|[IVXLC]+)(?:\.\d+){0,3})\.?\s+(?P<title>[^\d].{2,})$", line, flags=re.IGNORECASE)
    if numbered:
        number = numbered.group("number").rstrip(".")
        level = min(number.count(".") + 1, 3)
        return {"level": level, "title": f"{number} {normalize_text(numbered.group('title'))}"}

    canonical = {
        "abstract": "Abstract",
        "introduction": "Introduction",
        "background": "Background",
        "related work": "Related Work",
        "method": "Method",
        "methodology": "Methodology",
        "methods": "Methods",
        "experiments": "Experiments",
        "experiment": "Experiment",
        "evaluation": "Evaluation",
        "results": "Results",
        "discussion": "Discussion",
        "limitations": "Limitations",
        "conclusion": "Conclusion",
        "conclusions": "Conclusions",
        "references": "References",
        "appendix": "Appendix",
    }
    lowered = line.casefold()
    if lowered in canonical:
        return {"level": 1, "title": canonical[lowered]}
    return None


def _outline_level(value: Any) -> int:
    try:
        level = int(value)
    except (TypeError, ValueError):
        level = 1
    return min(max(level, 1), 3)


def _clean_outline_heading(value: Any, *, title: str = "") -> str:
    heading = normalize_text(value)
    heading = re.sub(r"\s+", " ", heading).strip(" .\t\r\n")
    if not heading or len(heading) > 140:
        return ""
    if heading.casefold() == normalize_text(title).casefold():
        return ""
    if re.search(r"[@{}<>]|https?://|www\.", heading, flags=re.IGNORECASE):
        return ""
    if len(re.findall(r"[A-Za-z\u4e00-\u9fff]", heading)) < 3:
        return ""
    return heading


def rename_note(note_id: str, next_title: str) -> dict[str, Any] | None:
    library = read_library()
    note = find_note(library, note_id)
    if note is None:
        return None
    note["title"] = next_title
    write_library(library)
    update_note_html_title(note, next_title)
    return note


def update_note_summary(note_id: str, summary: str) -> dict[str, Any] | None:
    library = read_library()
    note = find_note(library, note_id)
    if note is None:
        return None
    note["summary"] = normalize_text(summary)
    write_library(library)
    return note
