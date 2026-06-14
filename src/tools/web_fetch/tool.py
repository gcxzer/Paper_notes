from __future__ import annotations

import gzip
import urllib.error
import urllib.request
import zlib
from datetime import datetime, timezone
from typing import Any

from langchain_core.tools import StructuredTool

from tools.web_fetch.extractors import extract_content
from tools.web_fetch.security import SafeRedirectHandler, validate_public_http_url, web_fetch_request


WEB_FETCH_TOOL_NAME = "web_fetch"
WEB_FETCH_TOOLSET = "web_search"
MAX_RESPONSE_BYTES = 10 * 1024 * 1024
DEFAULT_MAX_CHARS = 12_000
MAX_TEXT_CHARS = 50_000


def create_tools() -> list[StructuredTool]:
    return [
        StructuredTool(
            name=WEB_FETCH_TOOL_NAME,
            description=(
                "Fetch and extract readable content from a specific public URL. Use this when the user provides "
                "a URL or when web_search snippets are insufficient. Supports public HTML, plain text, Markdown, "
                "JSON/XML-like text, and PDF URLs."
            ),
            args_schema=web_fetch_parameters(),
            func=lambda **kwargs: web_fetch(dict(kwargs)),
        )
    ]


def web_fetch_parameters() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "Public http or https URL to fetch."},
            "max_chars": {
                "type": "integer",
                "minimum": 1,
                "maximum": MAX_TEXT_CHARS,
                "default": DEFAULT_MAX_CHARS,
                "description": "Maximum extracted text characters to return.",
            },
            "include_links": {
                "type": "boolean",
                "default": False,
                "description": "Whether to include links extracted from HTML pages.",
            },
            "format": {
                "type": "string",
                "enum": ["text", "markdown"],
                "default": "markdown",
                "description": "Preferred output format for extracted text.",
            },
        },
        "required": ["url"],
        "additionalProperties": False,
    }


def web_fetch(args: dict[str, Any]) -> dict[str, Any]:
    url = str(args.get("url") or "").strip()
    validation = validate_public_http_url(url)
    if not validation.ok:
        return _fetch_error(validation.error, validation.code, url=url)
    max_chars = _safe_int(args.get("max_chars"), default=DEFAULT_MAX_CHARS, maximum=MAX_TEXT_CHARS)
    include_links = args.get("include_links", False) is True
    output_format = str(args.get("format") or "markdown").strip().lower()
    if output_format not in {"text", "markdown"}:
        output_format = "markdown"

    try:
        fetched = _fetch_bytes(validation.url)
    except RuntimeError as error:
        code = "content_too_large" if "too large" in str(error).lower() else "fetch_failed"
        return _fetch_error(str(error) or "Fetch failed.", code, url=url)

    final_validation = validate_public_http_url(fetched["final_url"])
    if not final_validation.ok:
        return _fetch_error(final_validation.error, final_validation.code, url=url, final_url=fetched["final_url"])

    extracted = extract_content(
        fetched["data"],
        content_type=fetched["content_type"],
        final_url=fetched["final_url"],
        output_format=output_format,
    )
    if extracted.error:
        return _fetch_error(
            extracted.error,
            extracted.code or "unsupported_content_type",
            url=url,
            final_url=fetched["final_url"],
            content_type=fetched["content_type"],
        )
    text = extracted.text
    truncated = len(text) > max_chars
    if truncated:
        text = text[:max_chars].rstrip()
    return {
        "success": True,
        "url": url,
        "final_url": fetched["final_url"],
        "title": extracted.title,
        "content_type": fetched["content_type"],
        "text": text,
        "links": extracted.links if include_links else [],
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "truncated": truncated,
        "error": "",
        "code": "",
    }


def _fetch_bytes(url: str) -> dict[str, Any]:
    opener = urllib.request.build_opener(SafeRedirectHandler)
    request = web_fetch_request(url)
    try:
        with opener.open(request, timeout=20) as response:
            content_length = response.headers.get("Content-Length")
            if content_length and int(content_length) > MAX_RESPONSE_BYTES:
                raise RuntimeError("Fetched content is too large.")
            data = response.read(MAX_RESPONSE_BYTES + 1)
            if len(data) > MAX_RESPONSE_BYTES:
                raise RuntimeError("Fetched content is too large.")
            content_encoding = response.headers.get("Content-Encoding", "")
            data = _decode_response_body(data, content_encoding)
            return {
                "data": data,
                "final_url": response.geturl(),
                "content_type": response.headers.get("Content-Type", ""),
            }
    except urllib.error.HTTPError as error:
        detail = error.read(500).decode("utf-8", errors="replace")
        raise RuntimeError(f"Fetch failed with HTTP {error.code}: {detail}") from error
    except urllib.error.URLError as error:
        raise RuntimeError(f"Fetch failed: {error.reason}") from error


def _decode_response_body(data: bytes, content_encoding: str) -> bytes:
    encoding = str(content_encoding or "").strip().lower()
    if encoding in {"", "identity"}:
        if data.startswith(b"\x1f\x8b"):
            return gzip.decompress(data)
        return data
    if "gzip" in encoding:
        return gzip.decompress(data)
    if "deflate" in encoding:
        return zlib.decompress(data)
    raise RuntimeError(f"Unsupported content encoding: {content_encoding}.")


def _safe_int(value: Any, *, default: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(1, min(maximum, parsed))


def _fetch_error(
    message: str,
    code: str,
    *,
    url: str = "",
    final_url: str = "",
    content_type: str = "",
) -> dict[str, Any]:
    return {
        "success": False,
        "url": url,
        "final_url": final_url,
        "title": "",
        "content_type": content_type,
        "text": "",
        "links": [],
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "truncated": False,
        "error": message,
        "code": code,
    }
