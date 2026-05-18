from __future__ import annotations

import json
import math
from typing import Any


# Adapted from Nous Research Hermes Agent.
# Original source: hermes-agent/agent/model_metadata.py and hermes-agent/agent/context_compressor.py
# License: MIT Copyright (c) 2025 Nous Research


CHARS_PER_TOKEN = 4
IMAGE_TOKEN_ESTIMATE = 1_600
IMAGE_CHAR_EQUIVALENT = IMAGE_TOKEN_ESTIMATE * CHARS_PER_TOKEN
ENCRYPTED_REASONING_ITEM_TOKEN_ESTIMATE = 64
ENCRYPTED_REASONING_ITEM_CHAR_EQUIVALENT = ENCRYPTED_REASONING_ITEM_TOKEN_ESTIMATE * CHARS_PER_TOKEN
REQUEST_TOKEN_ESTIMATE_MULTIPLIER = 1.06
_NON_MODEL_VISIBLE_MESSAGE_KEYS = {
    "artifacts",
    "created_at",
    "finish_reason",
    "metadata",
    "provider_data",
    "runTrace",
    "toolActivity",
    "workTrace",
}


def estimate_tokens_rough(text: Any) -> int:
    rendered = str(text or "")
    if not rendered:
        return 0
    char_equivalent = _text_char_equivalent(rendered)
    return (char_equivalent + CHARS_PER_TOKEN - 1) // CHARS_PER_TOKEN


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
    return max(0, math.ceil(total * REQUEST_TOKEN_ESTIMATE_MULTIPLIER))


def estimate_message_chars(message: dict[str, Any]) -> int:
    if not isinstance(message, dict):
        return len(str(message))

    shadow: dict[str, Any] = {}
    extra_char_budget = 0
    has_replayed_codex_message_items = _has_replayed_codex_message_items(message)
    for key, value in message.items():
        if key in _NON_MODEL_VISIBLE_MESSAGE_KEYS:
            continue
        if key == "_anthropic_content_blocks":
            continue
        if key == "content":
            if has_replayed_codex_message_items and str(message.get("role") or "") == "assistant":
                continue
            shadow[key] = _content_for_char_estimate(value)
        elif key == "attachments":
            shadow[key] = _attachments_for_char_estimate(value)
            extra_char_budget += _attachments_text_char_budget(value)
        elif key == "codex_reasoning_items":
            shadow[key] = _codex_reasoning_items_for_char_estimate(value)
            extra_char_budget += _encrypted_reasoning_items_char_budget(value)
        elif key == "codex_message_items":
            shadow[key] = _codex_message_items_for_char_estimate(value)
        else:
            shadow[key] = value
    return _text_char_equivalent(str(shadow)) + extra_char_budget


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
        count += sum(1 for attachment in attachments if _is_image_attachment(attachment))

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


def _attachments_for_char_estimate(attachments: Any) -> list[dict[str, Any]]:
    if not isinstance(attachments, list):
        return []

    cleaned: list[dict[str, Any]] = []
    for attachment in attachments:
        if not isinstance(attachment, dict):
            cleaned.append({"attachment": str(attachment)})
            continue
        metadata = attachment.get("metadata") if isinstance(attachment.get("metadata"), dict) else {}
        extracted_chars = _safe_int(metadata.get("extractedTextChars") or metadata.get("extracted_text_chars"))
        file_name = str(attachment.get("fileName") or attachment.get("file_name") or attachment.get("id") or "attachment")
        mime_type = str(attachment.get("mimeType") or attachment.get("mime_type") or "")
        if _is_image_attachment(attachment):
            cleaned.append({
                "file_name": file_name,
                "mime_type": mime_type,
                "image": "[attached]",
            })
            continue
        cleaned.append({
            "file_name": file_name,
            "mime_type": mime_type,
            "text": "[attached text]",
            "text_chars": max(0, extracted_chars),
        })
    return cleaned


def _attachments_text_char_budget(attachments: Any) -> int:
    if not isinstance(attachments, list):
        return 0

    total = 0
    for attachment in attachments:
        if not isinstance(attachment, dict) or _is_image_attachment(attachment):
            continue
        metadata = attachment.get("metadata") if isinstance(attachment.get("metadata"), dict) else {}
        extracted_chars = _safe_int(metadata.get("extractedTextChars") or metadata.get("extracted_text_chars"))
        if extracted_chars <= 0:
            continue
        file_name = str(attachment.get("fileName") or attachment.get("file_name") or attachment.get("id") or "attachment")
        total += extracted_chars + len("Attachment: \n\n") + len(file_name)
    return total


def _codex_reasoning_items_for_char_estimate(items: Any) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []

    cleaned: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        summary = _reasoning_summary_for_char_estimate(item.get("summary"))
        if not isinstance(item.get("encrypted_content"), str) or not item.get("encrypted_content"):
            if summary:
                cleaned.append({"type": "reasoning", "summary": summary})
            continue
        cleaned.append({
            "type": "reasoning",
            "encrypted_content": "[encrypted]",
            "summary": summary,
        })
    return cleaned


def _encrypted_reasoning_items_char_budget(items: Any) -> int:
    if not isinstance(items, list):
        return 0
    return sum(
        ENCRYPTED_REASONING_ITEM_CHAR_EQUIVALENT
        for item in items
        if isinstance(item, dict) and isinstance(item.get("encrypted_content"), str) and item.get("encrypted_content")
    )


def _reasoning_summary_for_char_estimate(summary: Any) -> list[dict[str, str]]:
    if not isinstance(summary, list):
        return []
    cleaned: list[dict[str, str]] = []
    for part in summary:
        if not isinstance(part, dict):
            continue
        text = str(part.get("text") or "")
        if text:
            cleaned.append({"type": str(part.get("type") or "summary_text"), "text": text})
    return cleaned


def _codex_message_items_for_char_estimate(items: Any) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []
    cleaned = []
    for item in items:
        normalized = _normalize_codex_message_item_for_char_estimate(item)
        if normalized is not None:
            cleaned.append(normalized)
    return cleaned


def _has_replayed_codex_message_items(message: dict[str, Any]) -> bool:
    if not isinstance(message, dict):
        return False
    return bool(_codex_message_items_for_char_estimate(message.get("codex_message_items")))


def _normalize_codex_message_item_for_char_estimate(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    if item.get("type") != "message" or item.get("role") != "assistant":
        return None
    content = item.get("content")
    if not isinstance(content, list):
        return None
    normalized_content: list[dict[str, str]] = []
    for part in content:
        if not isinstance(part, dict):
            continue
        part_type = str(part.get("type") or "").strip()
        if part_type not in {"output_text", "text"}:
            continue
        text = str(part.get("text") or "")
        normalized_content.append({"type": "output_text", "text": text})
    if not normalized_content:
        return None
    return {
        "type": "message",
        "role": "assistant",
        "content": normalized_content,
    }


def _is_image_part(part: Any) -> bool:
    return isinstance(part, dict) and part.get("type") in {"image", "image_url", "input_image"}


def _text_char_equivalent(text: str) -> int:
    total = 0
    for char in text:
        total += CHARS_PER_TOKEN if _is_cjk_char(char) else 1
    return total


def _is_cjk_char(char: str) -> bool:
    code = ord(char)
    return (
        0x3400 <= code <= 0x4DBF
        or 0x4E00 <= code <= 0x9FFF
        or 0xF900 <= code <= 0xFAFF
        or 0x20000 <= code <= 0x2A6DF
        or 0x2A700 <= code <= 0x2B73F
        or 0x2B740 <= code <= 0x2B81F
        or 0x2B820 <= code <= 0x2CEAF
        or 0x3040 <= code <= 0x30FF
        or 0xAC00 <= code <= 0xD7AF
    )


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _is_image_attachment(attachment: Any) -> bool:
    if not isinstance(attachment, dict):
        return False
    kind = str(attachment.get("kind") or "").strip().lower()
    mime_type = str(attachment.get("mimeType") or attachment.get("mime_type") or "").strip().lower()
    return kind == "image" or mime_type.startswith("image/")
