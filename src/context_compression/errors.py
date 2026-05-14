from __future__ import annotations

from typing import Any


# Adapted from Nous Research Hermes Agent.
# Original source: hermes-agent/agent/error_classifier.py and hermes-agent/agent/bedrock_adapter.py
# License: MIT Copyright (c) 2025 Nous Research


CONTEXT_OVERFLOW_PATTERNS = (
    "context length",
    "context size",
    "maximum context",
    "token limit",
    "too many tokens",
    "reduce the length",
    "exceeds the limit",
    "context window",
    "prompt is too long",
    "prompt exceeds max length",
    "maximum number of tokens",
    "exceeds the max_model_len",
    "max_model_len",
    "prompt length",
    "input is too long",
    "maximum model length",
    "context length exceeded",
    "slot context",
    "n_ctx_slot",
    "超过最大长度",
    "上下文长度",
    "max input token",
    "input token",
    "exceeds the maximum number of input tokens",
)


def is_context_overflow_error(error: BaseException | object) -> bool:
    text = _error_text(error)
    if not text:
        return False
    status_code = getattr(error, "status_code", None)
    if status_code == 413:
        return True
    lowered = text.lower()
    return any(pattern in lowered for pattern in CONTEXT_OVERFLOW_PATTERNS)


def _error_text(error: Any) -> str:
    parts = [str(error or "")]
    body = getattr(error, "body", None)
    if body is not None:
        parts.append(str(body))
    provider_data = getattr(error, "provider_data", None)
    if provider_data:
        parts.append(str(provider_data))
    return "\n".join(part for part in parts if part)
