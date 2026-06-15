from __future__ import annotations

import base64
import binascii
import re
from dataclasses import dataclass
from typing import Any


_DATA_URL_RE = re.compile(r"^data:(?P<mime>[-\w.]+/[-\w.+]+);base64,(?P<data>.*)$", re.IGNORECASE | re.DOTALL)


@dataclass(frozen=True, slots=True)
class Base64PayloadErrors:
    empty: str
    invalid: str
    too_large: str


_GENERIC_BASE64_ERRORS = Base64PayloadErrors(
    empty="Base64 data is required.",
    invalid="Data must be valid base64.",
    too_large="Base64 payload is too large.",
)


def parse_base64_payload(
    value: str,
    *,
    max_bytes: int,
    errors: Base64PayloadErrors,
    error_type: type[ValueError] = ValueError,
) -> tuple[bytes, str]:
    text = str(value or "").strip()
    if not text:
        raise error_type(errors.empty)
    declared_mime = ""
    match = _DATA_URL_RE.match(text)
    if match:
        declared_mime = match.group("mime").lower()
        text = match.group("data")
    try:
        data = base64.b64decode(text, validate=True)
    except (binascii.Error, ValueError) as error:
        raise error_type(errors.invalid) from error
    if len(data) > max_bytes:
        raise error_type(errors.too_large)
    return data, declared_mime


def base64_payload_text(value: Any) -> str:
    if isinstance(value, bytes):
        return base64.b64encode(value).decode("ascii")
    return str(value or "")


def decoded_base64_payload_size(
    value: Any,
    *,
    max_bytes: int,
    errors: Base64PayloadErrors | None = None,
) -> int:
    if isinstance(value, bytes):
        return len(value)
    text = str(value or "").strip()
    try:
        data, _declared_mime = parse_base64_payload(
            text,
            max_bytes=max_bytes,
            errors=errors or _GENERIC_BASE64_ERRORS,
            error_type=ValueError,
        )
    except Exception:
        return len(text)
    return len(data)


__all__ = [
    "Base64PayloadErrors",
    "base64_payload_text",
    "decoded_base64_payload_size",
    "parse_base64_payload",
]
