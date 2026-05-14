from __future__ import annotations

import json
from typing import Any


# Adapted from Nous Research Hermes Agent.
# Original source: hermes-agent/agent/model_metadata.py and hermes-agent/agent/context_compressor.py
# License: MIT Copyright (c) 2025 Nous Research


CHARS_PER_TOKEN = 4
IMAGE_TOKEN_ESTIMATE = 1_600
IMAGE_CHAR_EQUIVALENT = IMAGE_TOKEN_ESTIMATE * CHARS_PER_TOKEN


def estimate_tokens_rough(text: Any) -> int:
    rendered = str(text or "")
    if not rendered:
        return 0
    return (len(rendered) + CHARS_PER_TOKEN - 1) // CHARS_PER_TOKEN


def estimate_messages_tokens_rough(messages: list[dict[str, Any]]) -> int:
    total_chars = 0
    image_tokens = 0
    for message in messages:
        total_chars += estimate_message_chars(message)
        image_tokens += count_image_tokens(message, IMAGE_TOKEN_ESTIMATE)
    return ((total_chars + CHARS_PER_TOKEN - 1) // CHARS_PER_TOKEN) + image_tokens


def estimate_request_tokens_rough(
    messages: list[dict[str, Any]],
    *,
    instructions: str | None = None,
    tools: list[dict[str, Any]] | None = None,
) -> int:
    total = estimate_messages_tokens_rough(messages)
    total += estimate_tokens_rough(instructions or "")
    if tools:
        try:
            rendered_tools = json.dumps(tools, ensure_ascii=False, sort_keys=True)
        except (TypeError, ValueError):
            rendered_tools = str(tools)
        total += estimate_tokens_rough(rendered_tools)
    return total


def estimate_message_chars(message: dict[str, Any]) -> int:
    if not isinstance(message, dict):
        return len(str(message))

    shadow: dict[str, Any] = {}
    for key, value in message.items():
        if key == "_anthropic_content_blocks":
            continue
        if key == "content":
            shadow[key] = _content_for_char_estimate(value)
        else:
            shadow[key] = value
    return len(str(shadow))


def count_image_tokens(message: dict[str, Any], cost_per_image: int) -> int:
    if not isinstance(message, dict):
        return 0

    count = 0
    content = message.get("content")
    if isinstance(content, list):
        count += sum(1 for part in content if _is_image_part(part))

    stashed = message.get("_anthropic_content_blocks")
    if isinstance(stashed, list):
        count += sum(1 for part in stashed if isinstance(part, dict) and part.get("type") == "image")

    if isinstance(content, dict) and content.get("_multimodal"):
        inner = content.get("content")
        if isinstance(inner, list):
            count += sum(1 for part in inner if _is_image_part(part))

    attachments = message.get("attachments")
    if isinstance(attachments, list):
        count += sum(1 for attachment in attachments if isinstance(attachment, dict))

    return count * cost_per_image


def content_length_for_budget(raw_content: Any) -> int:
    if isinstance(raw_content, str):
        return len(raw_content)
    if not isinstance(raw_content, list):
        return len(str(raw_content or ""))

    total = 0
    for part in raw_content:
        if isinstance(part, str):
            total += len(part)
            continue
        if not isinstance(part, dict):
            total += len(str(part))
            continue
        if _is_image_part(part):
            total += IMAGE_CHAR_EQUIVALENT
        else:
            total += len(str(part.get("text") or ""))
    return total


def content_text_for_contains(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(part for part in parts if part)
    return str(content)


def append_text_to_content(content: Any, text: str, *, prepend: bool = False) -> Any:
    if content is None:
        return text
    if isinstance(content, str):
        return text + content if prepend else content + text
    if isinstance(content, list):
        text_block = {"type": "text", "text": text}
        return [text_block, *content] if prepend else [*content, text_block]
    rendered = str(content)
    return text + rendered if prepend else rendered + text


def _content_for_char_estimate(content: Any) -> Any:
    if isinstance(content, list):
        cleaned = []
        for part in content:
            if _is_image_part(part):
                cleaned.append({"type": part.get("type"), "image": "[stripped]"})
            else:
                cleaned.append(part)
        return cleaned
    if isinstance(content, dict) and content.get("_multimodal"):
        return content.get("text_summary", "")
    return content


def _is_image_part(part: Any) -> bool:
    return isinstance(part, dict) and part.get("type") in {"image", "image_url", "input_image"}
