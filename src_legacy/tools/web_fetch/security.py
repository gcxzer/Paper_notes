from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request


@dataclass(frozen=True, slots=True)
class UrlValidationResult:
    ok: bool
    url: str = ""
    error: str = ""
    code: str = ""


def validate_public_http_url(raw_url: object) -> UrlValidationResult:
    url = str(raw_url or "").strip()
    if not url:
        return UrlValidationResult(False, error="url is required.", code="invalid_url")
    parsed = urlparse(url)
    if parsed.scheme.lower() not in {"http", "https"}:
        return UrlValidationResult(False, error="Only http and https URLs are supported.", code="invalid_url")
    if not parsed.hostname:
        return UrlValidationResult(False, error="URL must include a host.", code="invalid_url")
    host = parsed.hostname.strip().lower().rstrip(".")
    if host == "localhost" or host.endswith(".local"):
        return UrlValidationResult(False, error="Local and private hosts are blocked.", code="blocked_url")
    try:
        addresses = socket.getaddrinfo(host, parsed.port, type=socket.SOCK_STREAM)
    except socket.gaierror as error:
        return UrlValidationResult(False, error=f"Could not resolve URL host: {error}", code="invalid_url")
    for address in addresses:
        ip_text = address[4][0]
        try:
            ip = ipaddress.ip_address(ip_text)
        except ValueError:
            return UrlValidationResult(False, error="Could not validate resolved host address.", code="blocked_url")
        if _blocked_ip(ip):
            return UrlValidationResult(False, error="Local and private network URLs are blocked.", code="blocked_url")
    return UrlValidationResult(True, url=url)


def _blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


class SafeRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: N802
        validation = validate_public_http_url(newurl)
        if not validation.ok:
            raise RuntimeError(validation.error or "Redirect target is blocked.")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def web_fetch_request(url: str) -> Request:
    return Request(
        url,
        headers={
            "Accept": "text/html,application/xhtml+xml,application/pdf,text/plain,text/markdown,application/json,application/xml,*/*;q=0.2",
            "Accept-Encoding": "identity",
            "User-Agent": "PaperNotesWebFetch/1.0",
        },
        method="GET",
    )
