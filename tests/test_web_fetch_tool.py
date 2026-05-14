from __future__ import annotations

import gzip
from types import SimpleNamespace

from tools.registry import ToolRegistry
import tools.web_fetch.tool as web_fetch_tool
from tools.web_fetch import register_web_fetch_tool, web_fetch
from tools.web_fetch.extractors import extract_content
from tools.web_fetch.security import validate_public_http_url


def test_register_web_fetch_tool_shares_web_search_group():
    registry = ToolRegistry()

    register_web_fetch_tool(registry)

    definition = registry.get("web_fetch")
    assert definition is not None
    assert definition.toolset == "web_search"
    assert definition.read_only is True
    assert definition.kind == "read"
    assert registry.get_group("web_search").display_name == "Custom Web Search"
    assert "web_fetch" in registry.get_group("web_search").tools


def test_web_fetch_extracts_html_and_truncates(monkeypatch):
    html = b"""
    <html>
      <head><title>Example Page</title><script>bad()</script></head>
      <body><h1>Hello</h1><p>Readable content here.</p><a href="https://example.com/a">A link</a></body>
    </html>
    """

    monkeypatch.setattr(web_fetch_tool, "validate_public_http_url", lambda url: SimpleNamespace(ok=True, url=url))
    monkeypatch.setattr(web_fetch_tool, "_fetch_bytes", lambda url: {
        "data": html,
        "final_url": "https://example.com/page",
        "content_type": "text/html; charset=utf-8",
    })

    result = web_fetch({
        "url": "https://example.com/page",
        "max_chars": 18,
        "include_links": True,
        "format": "markdown",
    })

    assert result["success"] is True
    assert result["title"] == "Example Page"
    assert result["final_url"] == "https://example.com/page"
    assert result["text"] == "# Hello\n\nReadable"
    assert result["truncated"] is True
    assert result["links"] == [{"url": "https://example.com/a", "text": "A link"}]


def test_web_fetch_rejects_blocked_url():
    result = web_fetch({"url": "file:///tmp/private.txt"})

    assert result["success"] is False
    assert result["code"] == "invalid_url"


def test_validate_public_http_url_blocks_localhost():
    result = validate_public_http_url("http://localhost:8000")

    assert result.ok is False
    assert result.code == "blocked_url"


def test_extract_content_handles_text_and_json():
    text = extract_content(b"hello\nworld", content_type="text/plain")
    json_result = extract_content(b'{"name":"Paper Notes"}', content_type="application/json")

    assert text.text == "hello\nworld"
    assert '"name": "Paper Notes"' in json_result.text


def test_extract_content_rejects_binary():
    result = extract_content(b"\x00\x01\x02\x03", content_type="application/octet-stream")

    assert result.code == "unsupported_content_type"


def test_decode_response_body_handles_gzip_without_header():
    compressed = gzip.compress(b"<html><title>Compressed</title><body>Hello</body></html>")

    assert web_fetch_tool._decode_response_body(compressed, "") == b"<html><title>Compressed</title><body>Hello</body></html>"


def test_extract_content_rejects_binary_even_when_labeled_html():
    result = extract_content(gzip.compress(b"<html></html>"), content_type="text/html; charset=utf-8")

    assert result.code == "unsupported_content_type"
