"""说明：处理 LangChain 消息和会话 transcript 的互转。

作用：统一保存、恢复、比较消息，并提供 JSON 安全转换和最后回复提取能力。
"""

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

from app_infra.formatting import content_text
from middleware import SUMMARY_MESSAGE_PREFIX

__all__ = [
    "ATTACHMENT_ONLY_MESSAGE",
    "content_text",
    "json_safe",
    "last_assistant_text",
    "last_assistant_transcript_text",
    "merge_existing_transcript_fields",
    "messages_from_final_chunk",
    "messages_from_transcript",
    "messages_to_transcript",
    "request_message_content",
]

ATTACHMENT_ONLY_MESSAGE = "Please read and summarize the attached file."


# 请求输入
def request_message_content(request: Any) -> Any:
    """返回本轮用户消息；只有附件没有文本时使用固定占位提示。"""
    if request.message:
        return request.message
    return ATTACHMENT_ONLY_MESSAGE


# Transcript 转 LangChain 消息
def messages_from_transcript(messages: list[dict[str, Any]]) -> list[BaseMessage]:
    """把会话持久化 transcript 转成 LangChain 可执行的消息列表。"""
    converted: list[BaseMessage] = []
    for message in messages:
        role = str(message.get("role") or "").strip().lower()
        content = copy.deepcopy(message.get("content", ""))
        name = message.get("name")
        if _is_summary_transcript_message(message):
            converted.append(SystemMessage(content=content, name=name))
        elif role == "user":
            converted.append(HumanMessage(content=content, name=name))
        elif role == "assistant":
            converted.append(AIMessage(content=content, name=name, tool_calls=copy.deepcopy(message.get("tool_calls") or [])))
        elif role == "tool":
            converted.append(ToolMessage(
                content=content,
                name=name,
                tool_call_id=str(message.get("tool_call_id") or message.get("id") or "tool-call"),
            ))
        elif role == "system":
            converted.append(SystemMessage(content=content, name=name))
        elif role:
            converted.append(ChatMessage(role=role, content=content, name=name))
    return converted


# LangChain 结果提取
def messages_from_final_chunk(chunks: list[Any]) -> list[BaseMessage]:
    """从 LangChain stream 的最后 chunk 中提取完整消息列表。"""
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


# LangChain 消息转 transcript
def messages_to_transcript(messages: list[BaseMessage]) -> list[dict[str, Any]]:
    """把 LangChain 消息列表转换成可保存的 transcript payload。"""
    transcript: list[dict[str, Any]] = []
    for message in messages:
        if isinstance(message, RemoveMessage):
            continue
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
        transcript.append(payload)
    return transcript


def role_for_message(message: BaseMessage) -> str:
    """把 LangChain message 类型映射成 transcript role。"""
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
    """判断 LangChain 消息是否是上下文压缩 summary。"""
    if not isinstance(message, HumanMessage | SystemMessage):
        return False
    content = getattr(message, "content", "")
    return isinstance(content, str) and content.strip().startswith(SUMMARY_MESSAGE_PREFIX)


def _is_summary_transcript_message(message: dict[str, Any]) -> bool:
    """判断 transcript 消息是否是上下文压缩 summary。"""
    role = str(message.get("role") or "").strip().lower()
    content = message.get("content", "")
    if role == "summary":
        return True
    return role == "user" and isinstance(content, str) and content.strip().startswith(SUMMARY_MESSAGE_PREFIX)

# Transcript 查询
def last_assistant_text(messages: list[BaseMessage]) -> str | None:
    """从 LangChain 消息列表里倒序读取最后一条 assistant 文本。"""
    for message in reversed(messages):
        if isinstance(message, AIMessage):
            return content_text(message.content)
    return None


def last_assistant_transcript_text(messages: list[dict[str, Any]]) -> str | None:
    """从 transcript 里倒序读取最后一条非工具调用 assistant 文本。"""
    for message in reversed(messages):
        if message.get("role") != "assistant" or message.get("tool_calls"):
            continue
        return content_text(message.get("content"))
    return None


# Transcript 字段合并
def merge_existing_transcript_fields(
    messages: list[dict[str, Any]],
    existing_messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """把旧 transcript 中已有的 metadata/runTrace 等字段合并到新 transcript。"""
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
    """合并单条 transcript 消息，保留旧消息里新消息没有的字段。"""
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
    """判断两条 transcript 是否指向同一条对话消息，供字段合并时对齐。"""
    existing_role = str(existing.get("role") or "").strip().lower()
    message_role = str(message.get("role") or "").strip().lower()
    if existing_role != message_role:
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


# Metadata 和 JSON 安全转换
def message_metadata(message: BaseMessage) -> dict[str, Any]:
    """提取可公开保存的 message metadata，过滤隐藏 reasoning 字段。"""
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
    """过滤 provider additional_kwargs 中不应写进 transcript 的隐藏 reasoning 内容。"""
    if not isinstance(additional_kwargs, dict):
        return {}
    hidden_keys = {"reasoning_content", "reasoning_details", "reasoning"}
    return {key: copy.deepcopy(value) for key, value in additional_kwargs.items() if key not in hidden_keys}


def json_safe(value: Any) -> Any:
    """把任意值递归转换成可 JSON 序列化的结构。"""
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, Enum):
        return json_safe(value.value)
    if isinstance(value, BaseMessage):
        return json_safe({
            "type": value.type,
            "content": value.content,
            "name": value.name,
        })
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