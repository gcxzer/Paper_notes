"""说明：提供 MCP 连接和资源访问的安全校验。

作用：限制本地路径、网络地址和危险配置，降低外部工具带来的风险。
"""

from __future__ import annotations

import json
import re
from typing import Any

__all__ = [
    "collect_security_warnings",
    "extend_security_warnings",
    "mcp_security_warnings",
    "sanitize_mcp_description",
    "sanitize_mcp_error",
    "sanitize_mcp_schema_descriptions",
]

_CREDENTIAL_PATTERNS = (
    re.compile(r"data:[-\w.+/]+;base64,[A-Za-z0-9+/=\s]{32,}", re.IGNORECASE),
    re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{1,255}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{6,255}\b"),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{3,255}"),
    re.compile(r"(?i)\b((?:authorization|proxy-authorization|x-api-key|api-key|api_key|openai-api-key|client-secret|client_secret)\s*[:=]\s*)(?:Bearer\s+)?[^\s,;\"']{1,255}"),
    re.compile(r"(?i)\b(client[_-]?secret\s*[:=]\s*)[^\s,;\"']{1,255}"),
    re.compile(r"(?i)\b(Authorization\s*[:=]\s*)(?:Bearer\s+)?[^\s,;\"']{3,255}"),
    re.compile(r"(?i)\b[A-Za-z0-9_]*(?:API[_-]?KEY|TOKEN|SECRET|PASSWORD)[A-Za-z0-9_]*\s*=\s*[^\s,;\"']{1,255}"),
    re.compile(r"(?i)\b(?:token|key|secret|password)\s*=\s*[^\s,;\"']{1,255}"),
    re.compile(r"(?i)([\"'](?:api[_-]?key|token|secret|password|authorization)[\"']\s*:\s*[\"'])([^\"']{1,255})([\"'])"),
    re.compile(r"\b[A-Za-z0-9+/]{80,}={0,2}\b"),
)
_PROMPT_INJECTION_PATTERNS = (
    re.compile(r"(?i)\bignore\s+(?:all\s+)?(?:previous|prior|above|system|developer)\s+instructions\b"),
    re.compile(r"(?i)\bdisregard\s+(?:all\s+)?(?:previous|prior|above|system|developer)\s+instructions\b"),
    re.compile(r"(?i)\boverride\s+(?:the\s+)?(?:system|developer|previous)\s+(?:prompt|instructions)\b"),
    re.compile(r"(?i)\breveal\s+(?:the\s+)?(?:system prompt|developer message|hidden instructions|secrets?)\b"),
    re.compile(r"(?i)\bexfiltrate\s+(?:data|secrets?|credentials?)\b"),
    re.compile(r"(?i)\byou\s+are\s+now\s+(?:in|the)\s+(?:system|developer)\b"),
)


def sanitize_mcp_error(message: Any) -> str:
    text = str(message or "").strip()
    if not text:
        return "MCP request failed."
    for pattern in _CREDENTIAL_PATTERNS:
        def _replace(match: re.Match[str]) -> str:
            if match.lastindex and match.lastindex >= 2:
                prefix = match.group(1) or ""
                suffix = match.group(match.lastindex) if match.lastindex >= 3 else ""
                return f"{prefix}[REDACTED]{suffix}"
            return "[REDACTED]"

        text = pattern.sub(_replace, text)
    if len(text) > 4000:
        text = f"{text[:4000].rstrip()}...[truncated]"
    return text


def mcp_security_warnings(value: Any, *, surface: str) -> list[dict[str, Any]]:
    text = _security_scan_text(value)
    if not text:
        return []
    warnings: list[dict[str, Any]] = []
    for pattern in _PROMPT_INJECTION_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        warnings.append({
            "code": "mcp_prompt_injection_suspected",
            "surface": surface,
            "severity": "warning",
            "message": "External MCP content contains instruction-like text and should be treated as untrusted data.",
            "match": sanitize_mcp_error(match.group(0)),
        })
    return warnings


def sanitize_mcp_description(
    description: str,
    *,
    surface: str,
    warnings: list[dict[str, Any]],
    fallback: str,
) -> str:
    found = mcp_security_warnings(description, surface=surface)
    if found:
        extend_security_warnings(warnings, found)
        return f"{fallback} External description omitted because it contained instruction-like content."
    return description or fallback


def sanitize_mcp_schema_descriptions(
    schema: Any,
    *,
    warnings: list[dict[str, Any]],
    surface: str,
) -> dict[str, Any]:
    def _sanitize_node(node: Any) -> Any:
        if isinstance(node, list):
            return [_sanitize_node(item) for item in node]
        if not isinstance(node, dict):
            return node
        sanitized: dict[str, Any] = {}
        for key, value in node.items():
            if key == "description" and isinstance(value, str):
                found = mcp_security_warnings(value, surface=surface)
                if found:
                    extend_security_warnings(warnings, found)
                    sanitized[key] = "External MCP schema description omitted because it contained instruction-like content."
                    continue
            sanitized[str(key)] = _sanitize_node(value)
        return sanitized

    return _sanitize_node(schema) if isinstance(schema, dict) else {"type": "object", "properties": {}}


def extend_security_warnings(target: list[dict[str, Any]], warnings: list[dict[str, Any]]) -> None:
    seen = {
        (
            str(item.get("code") or ""),
            str(item.get("surface") or ""),
            str(item.get("match") or ""),
        )
        for item in target
        if isinstance(item, dict)
    }
    for warning in warnings:
        if not isinstance(warning, dict):
            continue
        key = (
            str(warning.get("code") or ""),
            str(warning.get("surface") or ""),
            str(warning.get("match") or ""),
        )
        if key in seen:
            continue
        target.append(warning)
        seen.add(key)


def collect_security_warnings(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        value = item.get("securityWarnings")
        if isinstance(value, list):
            extend_security_warnings(warnings, [entry for entry in value if isinstance(entry, dict)])
    return warnings


def _security_scan_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value[:20000]
    try:
        return json.dumps(_json_safe_for_scan(value), ensure_ascii=False, sort_keys=True)[:20000]
    except Exception:
        return str(value)[:20000]


def _json_safe_for_scan(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, bytes):
        return f"[bytes:{len(value)}]"
    if isinstance(value, dict):
        return {str(key): _json_safe_for_scan(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe_for_scan(item) for item in value]
    if hasattr(value, "__dict__"):
        return _json_safe_for_scan(vars(value))
    return str(value)
