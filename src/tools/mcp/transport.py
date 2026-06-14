from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit


_CROSS_ORIGIN_STRIPPED_HEADER_NAMES = frozenset({
    "authorization",
    "proxy-authorization",
    "cookie",
    "x-api-key",
    "api-key",
    "openai-api-key",
    "anthropic-api-key",
    "x-auth-token",
    "x-access-token",
    "mcp-session-id",
})


def mcp_http_request_hook(initial_url: str, configured_headers: dict[str, Any]):
    initial_origin = _http_origin(initial_url)
    stripped_names = _configured_header_names(configured_headers) | set(_CROSS_ORIGIN_STRIPPED_HEADER_NAMES)

    async def _strip_cross_origin_headers(request: Any) -> None:
        if _http_origin(request.url) == initial_origin:
            return
        for name in stripped_names:
            _drop_request_header(request.headers, name)

    return _strip_cross_origin_headers


def _default_http_port(scheme: str) -> int | None:
    scheme = str(scheme or "").lower()
    if scheme == "http":
        return 80
    if scheme == "https":
        return 443
    return None


def _http_origin(url: Any) -> tuple[str, str, int | None]:
    parsed = urlsplit(str(url or ""))
    return (
        parsed.scheme.lower(),
        (parsed.hostname or "").lower(),
        parsed.port or _default_http_port(parsed.scheme),
    )


def _configured_header_names(headers: dict[str, Any] | None) -> set[str]:
    if not isinstance(headers, dict):
        return set()
    return {
        normalized
        for name in headers
        if (normalized := str(name).strip().lower()) and normalized != "mcp-protocol-version"
    }


def _drop_request_header(headers: Any, name: str) -> None:
    try:
        del headers[name]
    except KeyError:
        pass


__all__ = ["mcp_http_request_hook"]
