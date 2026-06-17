from __future__ import annotations

from typing import Any, Callable

from app_infra.artifact_generation import (
    file_generation_request_options,
    image_generation_request_options,
    request_model_options,
)
from app_infra.content import content_text as message_content_text
from app_infra.formatting import normalize_text
from middleware import SUMMARY_MESSAGE_PREFIX
from tools.generated_artifacts.payloads import (
    latest_assistant_artifacts,
    message_artifacts,
)

__all__ = [
    "bool_value",
    "chat_result_payload",
    "context_payload",
    "empty_context_payload",
    "file_generation_options",
    "image_generation_options",
    "is_image_artifact",
    "last_compaction_marker_message",
    "message_artifacts",
    "model_options_from_body",
    "optional_int",
    "optional_text",
    "optional_text_list",
    "public_chat_message",
    "query_value",
    "request_message",
    "request_metadata",
    "session_title",
    "user_message_request_metadata",
    "visible_annotations",
]

def chat_result_payload(
    result: Any,
    *,
    request_id: str = "",
    session_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    response_text = message_content_text(result.response)
    messages = [public_chat_message(message) for message in result.messages]
    messages = [message for message in messages if message is not None]
    artifacts = latest_assistant_artifacts(messages)
    assistant_message: dict[str, Any] = {
        "role": "assistant",
        "content": response_text,
        "text": response_text,
        "error": bool(result.error),
    }
    if artifacts:
        assistant_message["artifacts"] = artifacts
    if getattr(result, "run_trace", None):
        assistant_message["runTrace"] = result.run_trace
    return {
        "success": True,
        "requestId": request_id,
        "sessionId": result.session_id,
        "session": dict(session_payload or {}),
        "createdSession": bool(result.created_session),
        "completed": bool(result.completed),
        "cancelled": False,
        "response": response_text,
        "message": assistant_message,
        "messages": messages,
        "events": list(getattr(result, "events", []) or []),
        "runTrace": getattr(result, "run_trace", None),
        "turns": 1,
        "pendingToolCalls": [],
        "artifacts": artifacts,
        "error": result.error,
    }


def public_chat_message(message: dict[str, Any]) -> dict[str, Any] | None:
    role = optional_text(message.get("role"))
    if is_summary_message(message):
        return None
    if role == "tool":
        return None
    if role == "assistant" and message.get("tool_calls"):
        return None
    if role not in {"user", "assistant", "divider"}:
        return None
    payload = dict(message)
    payload["text"] = message_content_text(payload.get("text") or payload.get("content"))
    artifacts = message_artifacts(payload)
    if artifacts:
        payload["artifacts"] = artifacts
    if role == "divider":
        metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
        payload["markerType"] = optional_text(metadata.get("type"))
        payload["focus"] = optional_text(metadata.get("focus"))
        payload["warning"] = optional_text(metadata.get("warning"))
    return payload


def empty_context_payload(query: Any) -> dict[str, Any]:
    provider = optional_text(query_value(query, "provider"))
    model = optional_text(query_value(query, "model"))
    return {
        "sessionId": "",
        "provider": provider,
        "model": model,
        "contextLength": 0,
        "tokensUsed": 0,
        "estimatedRequestTokens": 0,
        "messageTokens": 0,
        "toolSchemaTokens": 0,
        "actualInputTokens": 0,
        "actualOutputTokens": 0,
        "actualTotalTokens": 0,
        "actualUsageAvailable": False,
        "usageUpdatedAt": "",
        "usageRequestId": "",
        "remainingTokens": 0,
        "thresholdTokens": 0,
        "percentFull": 0,
        "thresholdPercent": 0,
        "messageCount": 0,
        "compactionEnabled": False,
        "compactionReady": False,
        "summaryAvailable": False,
        "compressionCount": 0,
        "lastCompressedAt": "",
        "lastCompressionError": "",
        "fallbackUsed": False,
    }


def context_payload(status: dict[str, Any], messages: list[dict[str, Any]]) -> dict[str, Any]:
    context_window = int(status.get("contextWindow") or status.get("contextLength") or 0)
    estimated_tokens = int(status.get("estimatedTokens") or status.get("tokensUsed") or 0)
    actual_input_tokens = int(status.get("actualInputTokens") or 0)
    actual_usage_available = bool(status.get("actualUsageAvailable") or actual_input_tokens > 0)
    display_tokens = actual_input_tokens if actual_usage_available and actual_input_tokens > 0 else estimated_tokens
    threshold_tokens = int(status.get("compactionTriggerTokens") or status.get("thresholdTokens") or 0)
    compression_count = compaction_marker_count(messages)
    summary_available = has_summary_message(messages)
    threshold_percent = round((threshold_tokens / context_window) * 100) if context_window > 0 and threshold_tokens > 0 else 0
    percent_full = round((display_tokens / context_window) * 100) if context_window > 0 and display_tokens > 0 else 0
    return {
        **status,
        "contextLength": context_window,
        "tokensUsed": display_tokens,
        "requestTokens": display_tokens,
        "estimatedRequestTokens": estimated_tokens,
        "actualInputTokens": actual_input_tokens,
        "actualOutputTokens": int(status.get("actualOutputTokens") or 0),
        "actualTotalTokens": int(status.get("actualTotalTokens") or 0),
        "actualUsageAvailable": actual_usage_available,
        "usageUpdatedAt": optional_text(status.get("usageUpdatedAt")),
        "usageRequestId": optional_text(status.get("usageRequestId")),
        "messageTokens": int(status.get("messageTokens") or 0),
        "instructionTokens": int(status.get("instructionTokens") or 0),
        "toolSchemaTokens": int(status.get("toolTokens") or status.get("toolSchemaTokens") or 0),
        "thresholdTokens": threshold_tokens,
        "percentFull": min(100, max(0, int(percent_full))),
        "thresholdPercent": threshold_percent,
        "messageCount": int(status.get("messageCount") or len(messages)),
        "compactionEnabled": bool(status.get("compactionEnabled", True)),
        "summaryAvailable": summary_available,
        "compressionCount": compression_count,
        "lastCompressedAt": last_compaction_marker_time(messages),
        "lastCompressionError": "",
        "fallbackUsed": False,
    }


def has_summary_message(messages: list[dict[str, Any]]) -> bool:
    return any(is_summary_message(message) for message in messages)


def is_summary_message(message: dict[str, Any]) -> bool:
    role = optional_text(message.get("role"))
    if role == "summary":
        return True
    content = message.get("content")
    return role == "user" and isinstance(content, str) and content.strip().startswith(SUMMARY_MESSAGE_PREFIX)


def compaction_marker_count(messages: list[dict[str, Any]]) -> int:
    return sum(1 for message in messages if is_compaction_marker(message))


def last_compaction_marker_time(messages: list[dict[str, Any]]) -> str:
    for message in reversed(messages):
        if is_compaction_marker(message):
            return optional_text(message.get("created_at") or message.get("createdAt"))
    return ""


def last_compaction_marker_message(messages: list[dict[str, Any]]) -> dict[str, Any] | None:
    for message in reversed(messages):
        if is_compaction_marker(message):
            return message
    return None


def is_compaction_marker(message: dict[str, Any]) -> bool:
    metadata = message.get("metadata")
    return message.get("role") == "divider" and isinstance(metadata, dict) and metadata.get("type") == "context_compaction_marker"


def user_message_request_metadata(body: dict[str, Any]) -> dict[str, Any]:
    metadata = dict(body.get("metadata")) if isinstance(body.get("metadata"), dict) else {}
    generation = request_generation_metadata(body)
    if generation:
        existing_generation = metadata.get("generation") if isinstance(metadata.get("generation"), dict) else {}
        metadata["generation"] = {**existing_generation, **generation}

    selected_text_context = body.get("selectedTextContext")
    if isinstance(selected_text_context, dict):
        metadata.setdefault("selectedTextContext", selected_text_context)
    if not isinstance(metadata.get("selectedTextContext"), dict):
        selection_text = optional_text(body.get("selectionText"))
        if selection_text:
            context: dict[str, Any] = {"type": "selected_text", "text": selection_text}
            current_page = optional_text(body.get("currentPage"))
            if current_page:
                context["page"] = current_page
            metadata["selectedTextContext"] = context
    return metadata


def request_generation_metadata(body: dict[str, Any]) -> dict[str, Any]:
    generation: dict[str, Any] = {}
    image_generation = image_generation_options(body)
    if image_generation:
        generation["imageGeneration"] = image_generation
    file_generation = file_generation_options(body)
    if file_generation:
        generation["fileGeneration"] = file_generation
    return generation


def request_message(body: dict[str, Any]) -> str:
    return optional_text(body.get("message") if "message" in body else body.get("text"))


def request_metadata(body: dict[str, Any]) -> dict[str, Any]:
    metadata = dict(body.get("metadata")) if isinstance(body.get("metadata"), dict) else {}
    note_id = optional_text(body.get("noteId"))
    note_title = optional_text(body.get("noteTitle"))
    if note_id:
        metadata.setdefault("originNoteId", note_id)
        metadata.setdefault("currentNoteId", note_id)
    if note_title:
        metadata.setdefault("originNoteTitle", note_title)
        metadata.setdefault("currentNoteTitle", note_title)
    request_id = optional_text(body.get("requestId"))
    if request_id:
        metadata.setdefault("requestId", request_id)
    return metadata


def model_options_from_body(body: dict[str, Any]) -> dict[str, Any]:
    return request_model_options(body)


def image_generation_options(body: dict[str, Any]) -> dict[str, Any]:
    return image_generation_request_options(body)


def file_generation_options(body: dict[str, Any]) -> dict[str, Any]:
    return file_generation_request_options(body)


def optional_text_list(value: Any) -> list[str]:
    if isinstance(value, str):
        candidates: list[Any] = value.split(",")
    elif isinstance(value, list):
        candidates = value
    else:
        return []
    return [text for item in candidates if (text := optional_text(item))]


def session_title(body: dict[str, Any], message: str) -> str:
    explicit = optional_text(body.get("title") or body.get("sessionTitle"))
    if explicit:
        return explicit[:80]
    text = normalize_text(message).splitlines()[0] if message else "Attachment chat"
    return text[:80] or "New chat"


def optional_int(value: Any) -> int | None:
    text = optional_text(value)
    if not text:
        return None
    try:
        return int(text)
    except (TypeError, ValueError):
        return None


def visible_annotations(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def is_image_artifact(artifact: dict[str, Any]) -> bool:
    return optional_text(artifact.get("kind")) == "image" or optional_text(artifact.get("mimeType")).startswith("image/")


def query_value(query: Any, *keys: str) -> Any:
    for key in keys:
        if hasattr(query, "get"):
            value = query.get(key)
            if value is not None:
                return value
    return None


def bool_value(value: Any, *, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def optional_text(value: Any) -> str:
    return str(value or "").strip()


def public_chat_messages(
    messages: list[dict[str, Any]],
    *,
    mapper: Callable[[dict[str, Any]], dict[str, Any] | None] = public_chat_message,
) -> list[dict[str, Any]]:
    return [message for raw in messages if (message := mapper(raw)) is not None]

