from __future__ import annotations

import copy
from dataclasses import asdict, is_dataclass
from enum import Enum
from typing import Any

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    ChatMessage,
    HumanMessage,
    RemoveMessage,
    SystemMessage,
    ToolMessage,
)

from app_infra.content import content_text
from middleware import SUMMARY_MESSAGE_PREFIX


ATTACHMENT_ONLY_MESSAGE = "Please read and summarize the attached file."


def request_message_content(request: Any) -> Any:
    if request.message:
        return request.message
    return ATTACHMENT_ONLY_MESSAGE


def messages_from_transcript(messages: list[dict[str, Any]]) -> list[BaseMessage]:
    converted: list[BaseMessage] = []
    for message in messages:
        converted_message = message_from_transcript(message)
        if converted_message is not None:
            converted.append(converted_message)
    return converted


def message_from_transcript(message: dict[str, Any]) -> BaseMessage | None:
    role = str(message.get("role") or "").strip().lower()
    content = copy.deepcopy(message.get("content", ""))
    name = message.get("name")
    if _is_summary_transcript_message(message):
        return SystemMessage(content=content, name=name)
    if role == "user":
        return HumanMessage(content=content, name=name)
    if role == "assistant":
        return AIMessage(content=content, name=name, tool_calls=copy.deepcopy(message.get("tool_calls") or []))
    if role == "tool":
        return ToolMessage(
            content=content,
            name=name,
            tool_call_id=str(message.get("tool_call_id") or message.get("id") or "tool-call"),
        )
    if role == "system":
        return SystemMessage(content=content, name=name)
    if role:
        return ChatMessage(role=role, content=content, name=name)
    return None


def messages_from_final_chunk(chunks: list[Any]) -> list[BaseMessage]:
    for chunk in reversed(chunks):
        if not isinstance(chunk, dict):
            continue
        data = chunk.get("data") if chunk.get("type") == "values" else chunk
        if isinstance(data, dict) and isinstance(data.get("messages"), list):
            return [message for message in data["messages"] if isinstance(message, BaseMessage)]
        if chunk.get("type") == "updates" and isinstance(chunk.get("data"), dict):
            for update in reversed(list(chunk["data"].values())):
                if isinstance(update, dict) and isinstance(update.get("messages"), list):
                    messages = [message for message in update["messages"] if isinstance(message, BaseMessage)]
                    if messages:
                        return messages
    return []


def messages_to_transcript(messages: list[BaseMessage]) -> list[dict[str, Any]]:
    return [payload for message in messages if (payload := message_to_transcript(message)) is not None]


def message_to_transcript(message: BaseMessage) -> dict[str, Any] | None:
    if isinstance(message, RemoveMessage):
        return None
    payload: dict[str, Any] = {"role": role_for_message(message), "content": copy.deepcopy(message.content)}
    if message.name:
        payload["name"] = message.name
    if isinstance(message, AIMessage) and message.tool_calls:
        payload["tool_calls"] = copy.deepcopy(message.tool_calls)
    if isinstance(message, ToolMessage):
        payload["tool_call_id"] = message.tool_call_id
    metadata = message_metadata(message)
    if metadata:
        payload["metadata"] = metadata
    return payload


def role_for_message(message: BaseMessage) -> str:
    if _is_summary_message(message):
        return "summary"
    if isinstance(message, HumanMessage):
        return "user"
    if isinstance(message, AIMessage):
        return "assistant"
    if isinstance(message, ToolMessage):
        return "tool"
    if isinstance(message, SystemMessage):
        return "system"
    return str(getattr(message, "role", "") or message.type or "message")


def _is_summary_message(message: BaseMessage) -> bool:
    if not isinstance(message, HumanMessage | SystemMessage):
        return False
    content = getattr(message, "content", "")
    return isinstance(content, str) and content.strip().startswith(SUMMARY_MESSAGE_PREFIX)


def _is_summary_transcript_message(message: dict[str, Any]) -> bool:
    role = str(message.get("role") or "").strip().lower()
    content = message.get("content", "")
    if role == "summary":
        return True
    return role == "user" and isinstance(content, str) and content.strip().startswith(SUMMARY_MESSAGE_PREFIX)


def message_metadata(message: BaseMessage) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    if additional_kwargs := public_additional_kwargs(getattr(message, "additional_kwargs", None)):
        metadata["additional_kwargs"] = json_safe(additional_kwargs)
    if getattr(message, "response_metadata", None):
        metadata["response_metadata"] = json_safe(message.response_metadata)
    usage = getattr(message, "usage_metadata", None)
    if usage:
        metadata["usage"] = json_safe(usage)
    return metadata


def public_additional_kwargs(additional_kwargs: Any) -> dict[str, Any]:
    if not isinstance(additional_kwargs, dict):
        return {}
    hidden_keys = {"reasoning_content", "reasoning_details", "reasoning"}
    return {key: copy.deepcopy(value) for key, value in additional_kwargs.items() if key not in hidden_keys}


def json_safe(value: Any) -> Any:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, Enum):
        return json_safe(value.value)
    if isinstance(value, dict):
        return {str(json_safe(key)): json_safe(item) for key, item in value.items()}
    if isinstance(value, list | tuple | set):
        return [json_safe(item) for item in value]
    if is_dataclass(value) and not isinstance(value, type):
        return json_safe(asdict(value))
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        try:
            return json_safe(model_dump(mode="json"))
        except TypeError:
            return json_safe(model_dump())
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return json_safe(to_dict())
    return str(value)


def last_assistant_text(messages: list[BaseMessage]) -> str | None:
    for message in reversed(messages):
        if isinstance(message, AIMessage):
            return content_text(message.content)
    return None


def last_assistant_transcript_text(messages: list[dict[str, Any]]) -> str | None:
    for message in reversed(messages):
        if message.get("role") != "assistant" or message.get("tool_calls"):
            continue
        return content_text(message.get("content"))
    return None


def merge_existing_transcript_fields(
    messages: list[dict[str, Any]],
    existing_messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not messages or not existing_messages:
        return messages
    merged: list[dict[str, Any]] = []
    for index, message in enumerate(messages):
        if index < len(existing_messages) and transcript_messages_match(existing_messages[index], message):
            merged.append(merge_transcript_message_fields(message, existing_messages[index]))
        else:
            merged.append(message)
    return merged


def merge_transcript_message_fields(message: dict[str, Any], existing: dict[str, Any]) -> dict[str, Any]:
    merged = dict(message)
    for key, value in existing.items():
        if key == "metadata":
            existing_metadata = value if isinstance(value, dict) else {}
            message_metadata_value = merged.get("metadata") if isinstance(merged.get("metadata"), dict) else {}
            metadata = {**copy.deepcopy(existing_metadata), **copy.deepcopy(message_metadata_value)}
            if metadata:
                merged["metadata"] = metadata
            continue
        if key not in merged:
            merged[key] = copy.deepcopy(value)
    return merged


def transcript_messages_match(existing: dict[str, Any], message: dict[str, Any]) -> bool:
    if role_text(existing.get("role")) != role_text(message.get("role")):
        return False
    existing_tool_call_id = str(existing.get("tool_call_id") or "")
    message_tool_call_id = str(message.get("tool_call_id") or "")
    if existing_tool_call_id or message_tool_call_id:
        return existing_tool_call_id == message_tool_call_id
    existing_tool_calls = existing.get("tool_calls") or []
    message_tool_calls = message.get("tool_calls") or []
    if existing_tool_calls or message_tool_calls:
        return existing_tool_calls == message_tool_calls
    return content_text(existing.get("content")) == content_text(message.get("content"))


def role_text(value: Any) -> str:
    return str(value or "").strip().lower()


__all__ = [
    "ATTACHMENT_ONLY_MESSAGE",
    "content_text",
    "json_safe",
    "last_assistant_text",
    "last_assistant_transcript_text",
    "merge_existing_transcript_fields",
    "message_from_transcript",
    "message_metadata",
    "message_to_transcript",
    "messages_from_final_chunk",
    "messages_from_transcript",
    "messages_to_transcript",
    "public_additional_kwargs",
    "request_message_content",
    "role_for_message",
    "role_text",
    "transcript_messages_match",
]
