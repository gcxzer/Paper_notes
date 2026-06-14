from __future__ import annotations

import base64
from typing import Any

from tools.mcp.errors import mcp_error_payload
from tools.mcp.security import extend_security_warnings, mcp_security_warnings, sanitize_mcp_error
from tools.mcp.utils import first_field, format_exception


_MAX_MCP_FILE_BYTES = 30 * 1024 * 1024
_MCP_FILE_PREVIEW_CHARS = 4000
_SAFE_MCP_FILE_MIME_TYPES = frozenset({
    "text/plain",
    "text/markdown",
    "application/json",
    "text/csv",
    "text/html",
})
_SAFE_MCP_PDF_MIME_TYPE = "application/pdf"


def tool_result_payload(result: Any, *, server_id: str, media_store: Any = None, tool_name: str = "") -> dict[str, Any]:
    if bool(getattr(result, "isError", False)):
        error_text = content_blocks_text(getattr(result, "content", None)) or "MCP tool returned an error."
        payload = mcp_error_payload(
            error_text,
            server_id=server_id,
            default_code="mcp_tool_error",
            details=first_field(result, "structuredContent", "structured_content"),
        )
        attach_mcp_security_payload(payload, mcp_security_warnings(error_text, surface="tool_result"))
        return payload
    rendered = render_mcp_content_blocks(
        getattr(result, "content", None),
        server_id=server_id,
        media_store=media_store,
        tool_name=tool_name,
    )
    text = rendered["text"]
    structured = getattr(result, "structuredContent", None)
    payload: dict[str, Any] = {"success": True, "server_id": server_id}
    if text:
        payload["result"] = text
    if structured is not None:
        payload["structuredContent"] = structured
        if not text:
            payload["result"] = structured
    if "result" not in payload:
        payload["result"] = ""
    attach_mcp_media_payload(payload, rendered["artifacts"], rendered["mediaErrors"])
    attach_mcp_security_payload(payload, mcp_security_warnings(payload, surface="tool_result"))
    return payload


def content_blocks_text(content: Any) -> str:
    return render_mcp_content_blocks(content)["text"]


def render_mcp_content_blocks(
    content: Any,
    *,
    server_id: str = "",
    media_store: Any = None,
    tool_name: str = "",
    resource_uri: str = "",
) -> dict[str, Any]:
    blocks = content if isinstance(content, list) else ([] if content is None else [content])
    parts: list[str] = []
    artifacts: list[dict[str, Any]] = []
    media_errors: list[dict[str, Any]] = []
    for block in blocks:
        text = first_field(block, "text")
        if text:
            parts.append(str(text))
            continue
        data = first_field(block, "data")
        mime_type = str(first_field(block, "mimeType", "mime_type") or "")
        if data is not None and mime_type.lower().startswith("image/"):
            parts.append(mcp_image_summary(
                data,
                mime_type,
                server_id=server_id,
                media_store=media_store,
                tool_name=tool_name,
                resource_uri=resource_uri,
                file_name=str(first_field(block, "fileName", "file_name", "name") or ""),
                artifacts=artifacts,
                media_errors=media_errors,
            ))
            continue
        if data is not None and is_safe_mcp_pdf_mime(mime_type):
            parts.append(mcp_pdf_summary(
                data,
                mime_type,
                server_id=server_id,
                media_store=media_store,
                tool_name=tool_name,
                resource_uri=resource_uri,
                file_name=str(first_field(block, "fileName", "file_name", "name") or ""),
                artifacts=artifacts,
                media_errors=media_errors,
            ))
            continue
        if data is not None and is_safe_mcp_file_mime(mime_type):
            parts.append(mcp_file_summary(
                data,
                mime_type,
                encoded=True,
                server_id=server_id,
                media_store=media_store,
                tool_name=tool_name,
                resource_uri=resource_uri,
                file_name=str(first_field(block, "fileName", "file_name", "name") or ""),
                artifacts=artifacts,
                media_errors=media_errors,
            ))
    return {"text": "\n".join(parts), "artifacts": artifacts, "mediaErrors": media_errors}


def attach_mcp_media_payload(
    payload: dict[str, Any],
    artifacts: list[dict[str, Any]],
    media_errors: list[dict[str, Any]],
) -> None:
    if artifacts:
        payload["artifact"] = artifacts[0]
        payload["artifacts"] = artifacts
    if media_errors:
        payload["mediaErrors"] = media_errors


def attach_mcp_security_payload(payload: dict[str, Any], warnings: list[dict[str, Any]]) -> None:
    if not warnings:
        return
    existing = payload.get("securityWarnings")
    combined: list[dict[str, Any]] = list(existing) if isinstance(existing, list) else []
    extend_security_warnings(combined, warnings)
    payload["securityWarnings"] = combined


def mcp_media_artifact_payload(artifact: Any) -> dict[str, Any]:
    return artifact.to_dict() if hasattr(artifact, "to_dict") else dict(artifact)


def append_mcp_media_error(
    media_errors: list[dict[str, Any]] | None,
    *,
    mime_type: str,
    error: Exception,
) -> None:
    if media_errors is None:
        return
    media_errors.append({
        "code": "mcp_media_artifact_failed",
        "mimeType": mime_type,
        "error": sanitize_mcp_error(format_exception(error)),
    })


def mcp_image_summary(
    data: Any,
    mime_type: str,
    *,
    server_id: str = "",
    media_store: Any = None,
    tool_name: str = "",
    resource_uri: str = "",
    file_name: str = "",
    artifacts: list[dict[str, Any]] | None = None,
    media_errors: list[dict[str, Any]] | None = None,
) -> str:
    normalized_mime = str(mime_type or "").lower()
    size = decoded_media_size(data)
    if media_store is None:
        return f"[MCP image content: {normalized_mime}, {size} bytes]"
    create_mcp_image = getattr(media_store, "create_mcp_image", None)
    if not callable(create_mcp_image):
        return f"[MCP image content: {normalized_mime}, {size} bytes]"
    try:
        artifact = create_mcp_image(
            mcp_image_data_value(data),
            mime_type=normalized_mime,
            server_id=server_id,
            tool_name=tool_name,
            resource_uri=resource_uri,
            file_name=file_name,
        )
    except Exception as error:
        append_mcp_media_error(media_errors, mime_type=normalized_mime, error=error)
        return f"[MCP image content: {normalized_mime}, {size} bytes]"
    payload = mcp_media_artifact_payload(artifact)
    if artifacts is not None:
        artifacts.append(payload)
    return (
        f"[MCP image artifact: {payload.get('fileName') or 'image'}, "
        f"{payload.get('mimeType') or normalized_mime}, {payload.get('size') or size} bytes]"
    )


def mcp_image_data_value(data: Any) -> str:
    if isinstance(data, bytes):
        return base64.b64encode(data).decode("ascii")
    return str(data or "")


def mcp_file_summary(
    data: Any,
    mime_type: str,
    *,
    encoded: bool,
    server_id: str = "",
    media_store: Any = None,
    tool_name: str = "",
    resource_uri: str = "",
    file_name: str = "",
    artifacts: list[dict[str, Any]] | None = None,
    media_errors: list[dict[str, Any]] | None = None,
) -> str:
    normalized_mime = str(mime_type or "").lower()
    try:
        text = decode_mcp_file_content(data) if encoded else ("" if data is None else str(data))
    except Exception as error:
        append_mcp_media_error(media_errors, mime_type=normalized_mime, error=error)
        return f"[MCP file content: {normalized_mime}, {decoded_media_size(data)} bytes]"

    preview = mcp_file_preview(text)
    if media_store is None:
        return preview
    create_mcp_file = getattr(media_store, "create_mcp_file", None)
    if not callable(create_mcp_file):
        return preview
    try:
        artifact = create_mcp_file(
            text,
            mime_type=normalized_mime,
            server_id=server_id,
            tool_name=tool_name,
            resource_uri=resource_uri,
            file_name=file_name,
        )
    except Exception as error:
        append_mcp_media_error(media_errors, mime_type=normalized_mime, error=error)
        return preview
    payload = mcp_media_artifact_payload(artifact)
    if artifacts is not None:
        artifacts.append(payload)
    summary = (
        f"[MCP file artifact: {payload.get('fileName') or 'file'}, "
        f"{payload.get('mimeType') or normalized_mime}, {payload.get('size') or len(text.encode('utf-8'))} bytes]"
    )
    return "\n".join(part for part in (summary, preview) if part)


def mcp_pdf_summary(
    data: Any,
    mime_type: str,
    *,
    server_id: str = "",
    media_store: Any = None,
    tool_name: str = "",
    resource_uri: str = "",
    file_name: str = "",
    artifacts: list[dict[str, Any]] | None = None,
    media_errors: list[dict[str, Any]] | None = None,
) -> str:
    normalized_mime = str(mime_type or "").lower()
    size = decoded_media_size(data)
    fallback = f"[MCP PDF content: {normalized_mime}, {size} bytes]"
    if media_store is None:
        return fallback
    create_mcp_pdf = getattr(media_store, "create_mcp_pdf", None)
    if not callable(create_mcp_pdf):
        return fallback
    try:
        artifact = create_mcp_pdf(
            data,
            mime_type=normalized_mime,
            server_id=server_id,
            tool_name=tool_name,
            resource_uri=resource_uri,
            file_name=file_name,
        )
    except Exception as error:
        append_mcp_media_error(media_errors, mime_type=normalized_mime, error=error)
        return fallback
    payload = mcp_media_artifact_payload(artifact)
    if artifacts is not None:
        artifacts.append(payload)
    return (
        f"[MCP PDF artifact: {payload.get('fileName') or 'document.pdf'}, "
        f"{payload.get('mimeType') or normalized_mime}, {payload.get('size') or size} bytes]"
    )


def decode_mcp_file_content(data: Any) -> str:
    if isinstance(data, bytes):
        raw = data
    else:
        text = str(data or "").strip()
        if text.startswith("data:") and "," in text:
            text = text.split(",", 1)[1]
        raw = base64.b64decode(text, validate=True)
    if len(raw) > _MAX_MCP_FILE_BYTES:
        raise ValueError("MCP file payload is too large.")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError("MCP file content must be UTF-8 text.") from error


def mcp_file_preview(text: str) -> str:
    value = str(text or "")
    if len(value) <= _MCP_FILE_PREVIEW_CHARS:
        return value
    preview = value[:_MCP_FILE_PREVIEW_CHARS].rstrip()
    return f"{preview}...[truncated {len(value) - len(preview)} chars]"


def is_safe_mcp_file_mime(mime_type: str) -> bool:
    return str(mime_type or "").lower() in _SAFE_MCP_FILE_MIME_TYPES


def is_safe_mcp_pdf_mime(mime_type: str) -> bool:
    return str(mime_type or "").lower() == _SAFE_MCP_PDF_MIME_TYPE


def decoded_media_size(data: Any) -> int:
    if isinstance(data, bytes):
        return len(data)
    text = str(data or "").strip()
    if text.startswith("data:") and "," in text:
        text = text.split(",", 1)[1]
    try:
        return len(base64.b64decode(text, validate=True))
    except Exception:
        return len(text)


def file_name_from_resource_uri(uri: str) -> str:
    value = str(uri or "").split("?", 1)[0].rstrip("/")
    if not value:
        return ""
    return value.rsplit("/", 1)[-1]


def summarize_blob(blob: Any) -> str:
    if isinstance(blob, bytes):
        return f"[binary content: {len(blob)} bytes]"
    text = str(blob)
    try:
        decoded_size = len(base64.b64decode(text, validate=True))
    except Exception:
        decoded_size = len(text)
    return f"[binary content: {decoded_size} bytes]"


def summarize_media(data: Any, mime_type: str) -> str:
    if isinstance(data, bytes):
        size = len(data)
    else:
        text = str(data)
        try:
            size = len(base64.b64decode(text, validate=True))
        except Exception:
            size = len(text)
    return f"[MCP media content: {mime_type}, {size} bytes]"


__all__ = [
    "attach_mcp_media_payload",
    "attach_mcp_security_payload",
    "content_blocks_text",
    "decoded_media_size",
    "decode_mcp_file_content",
    "file_name_from_resource_uri",
    "is_safe_mcp_file_mime",
    "is_safe_mcp_pdf_mime",
    "mcp_file_preview",
    "mcp_file_summary",
    "mcp_image_summary",
    "mcp_pdf_summary",
    "render_mcp_content_blocks",
    "summarize_blob",
    "summarize_media",
    "tool_result_payload",
]
