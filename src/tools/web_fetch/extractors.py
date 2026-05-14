from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any


@dataclass(slots=True)
class ExtractedContent:
    title: str = ""
    text: str = ""
    links: list[dict[str, str]] = field(default_factory=list)
    code: str = ""
    error: str = ""


def extract_content(
    data: bytes,
    *,
    content_type: str = "",
    final_url: str = "",
    output_format: str = "markdown",
) -> ExtractedContent:
    media_type = _media_type(content_type)
    if media_type == "application/pdf" or data.startswith(b"%PDF"):
        return extract_pdf_text(data)
    if _looks_like_binary(data):
        return ExtractedContent(
            error=f"Fetched content looks binary and cannot be read as text: {content_type or 'unknown'}.",
            code="unsupported_content_type",
        )
    if media_type in {"text/html", "application/xhtml+xml"} or _looks_like_html(data):
        return extract_html(data, final_url=final_url, output_format=output_format)
    if _is_text_media_type(media_type) or _looks_like_text(data):
        text = decode_text(data)
        if media_type == "application/json":
            text = _pretty_json(text)
        return ExtractedContent(text=_normalize_text(text))
    return ExtractedContent(
        error=f"Unsupported content type: {content_type or 'unknown'}.",
        code="unsupported_content_type",
    )


def extract_pdf_text(data: bytes) -> ExtractedContent:
    try:
        import pymupdf  # type: ignore[import-not-found]
    except Exception as error:
        return ExtractedContent(error=f"PDF extraction requires pymupdf: {error}", code="pdf_extract_failed")
    try:
        with pymupdf.open(stream=data, filetype="pdf") as document:
            pages = [page.get_text("text") for page in document]
    except Exception as error:
        return ExtractedContent(error=f"Could not extract PDF text: {error}", code="pdf_extract_failed")
    return ExtractedContent(text=_normalize_text("\n\n".join(pages)))


def extract_html(data: bytes, *, final_url: str = "", output_format: str = "markdown") -> ExtractedContent:
    parser = ReadableHTMLParser(final_url=final_url)
    parser.feed(decode_text(data))
    parser.close()
    text = parser.markdown() if output_format == "markdown" else parser.plain_text()
    return ExtractedContent(
        title=_normalize_text(parser.title),
        text=_normalize_text(text),
        links=parser.links,
    )


class ReadableHTMLParser(HTMLParser):
    _SKIP_TAGS = {"script", "style", "noscript", "svg", "canvas", "template"}
    _BLOCK_TAGS = {"p", "div", "section", "article", "main", "header", "footer", "br", "li", "tr", "blockquote"}
    _HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}

    def __init__(self, *, final_url: str = "") -> None:
        super().__init__(convert_charrefs=True)
        self.final_url = final_url
        self.title = ""
        self.links: list[dict[str, str]] = []
        self._parts: list[str] = []
        self._skip_depth = 0
        self._in_title = False
        self._current_link: dict[str, str] | None = None
        self._current_link_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        attrs_dict = {name.lower(): value or "" for name, value in attrs}
        if tag in self._SKIP_TAGS:
            self._skip_depth += 1
            return
        if tag == "title":
            self._in_title = True
        if self._skip_depth:
            return
        if tag in self._HEADING_TAGS:
            level = int(tag[1])
            self._parts.append("\n\n" + ("#" * min(6, level)) + " ")
        elif tag in self._BLOCK_TAGS:
            self._parts.append("\n")
        if tag == "a" and attrs_dict.get("href"):
            self._current_link = {"url": attrs_dict["href"].strip(), "text": ""}
            self._current_link_text = []

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in self._SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1
            return
        if tag == "title":
            self._in_title = False
        if self._skip_depth:
            return
        if tag in self._HEADING_TAGS or tag in {"p", "div", "section", "article", "li", "tr", "blockquote"}:
            self._parts.append("\n")
        if tag == "a" and self._current_link is not None:
            text = _normalize_inline(" ".join(self._current_link_text))
            if text:
                self._current_link["text"] = text
            if self._current_link.get("url"):
                self.links.append(dict(self._current_link))
            self._current_link = None
            self._current_link_text = []

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        text = html.unescape(data)
        if self._in_title:
            self.title += text
            return
        if self._current_link is not None:
            self._current_link_text.append(text)
        self._parts.append(text)

    def plain_text(self) -> str:
        return _normalize_text("".join(self._parts))

    def markdown(self) -> str:
        return _normalize_markdown("".join(self._parts))


def decode_text(data: bytes) -> str:
    for encoding in ("utf-8", "utf-16", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _media_type(content_type: str) -> str:
    return str(content_type or "").split(";", 1)[0].strip().lower()


def _is_text_media_type(media_type: str) -> bool:
    return (
        media_type.startswith("text/")
        or media_type in {
            "application/json",
            "application/xml",
            "application/xhtml+xml",
            "application/javascript",
            "application/x-javascript",
            "application/ld+json",
        }
        or media_type.endswith("+json")
        or media_type.endswith("+xml")
    )


def _looks_like_html(data: bytes) -> bool:
    sample = data[:1024].lstrip().lower()
    return sample.startswith(b"<!doctype html") or sample.startswith(b"<html") or b"<body" in sample[:512]


def _looks_like_text(data: bytes) -> bool:
    sample = data[:4096]
    if b"\x00" in sample:
        return False
    if not sample:
        return True
    controls = sum(1 for byte in sample if byte < 32 and byte not in {9, 10, 13})
    return controls / max(1, len(sample)) < 0.08


def _looks_like_binary(data: bytes) -> bool:
    sample = data[:4096]
    if not sample:
        return False
    if b"\x00" in sample:
        return True
    controls = sum(1 for byte in sample if byte < 32 and byte not in {9, 10, 13})
    return controls / len(sample) >= 0.08


def _pretty_json(text: str) -> str:
    try:
        parsed: Any = json.loads(text)
    except Exception:
        return text
    return json.dumps(parsed, ensure_ascii=False, indent=2)


def _normalize_inline(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _normalize_text(text: str) -> str:
    text = re.sub(r"[ \t\r\f\v]+", " ", text or "")
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _normalize_markdown(text: str) -> str:
    text = re.sub(r"[ \t\r\f\v]+", " ", text or "")
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"\n(#{1,6}) ", r"\n\n\1 ", text)
    return text.strip()
