from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
from typing import Any

from langchain_core.messages import BaseMessage, HumanMessage

from app_config import AppConfig
from middleware import DEFAULT_COMPACTION_RESERVE_TOKENS, SUMMARY_MESSAGE_PREFIX


@dataclass(slots=True)
class AgentContextStatus:
    session_id: str
    provider: str
    model: str
    context_window: int
    estimated_tokens: int
    message_tokens: int
    tool_tokens: int
    actual_input_tokens: int
    actual_output_tokens: int
    actual_total_tokens: int
    actual_usage_available: bool
    usage_updated_at: str
    usage_request_id: str
    remaining_tokens: int
    reserve_tokens: int
    collapse_trigger_tokens: int
    collapse_trigger_messages: int
    compaction_trigger_tokens: int
    collapse_ready: bool
    compaction_ready: bool
    compaction_enabled: bool
    message_count: int

    @property
    def percent_full(self) -> int:
        if self.context_window <= 0:
            return 0
        return min(100, max(0, round((self.estimated_tokens / self.context_window) * 100)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "sessionId": self.session_id,
            "provider": self.provider,
            "model": self.model,
            "contextWindow": self.context_window,
            "estimatedTokens": self.estimated_tokens,
            "messageTokens": self.message_tokens,
            "toolTokens": self.tool_tokens,
            "actualInputTokens": self.actual_input_tokens,
            "actualOutputTokens": self.actual_output_tokens,
            "actualTotalTokens": self.actual_total_tokens,
            "actualUsageAvailable": self.actual_usage_available,
            "usageUpdatedAt": self.usage_updated_at,
            "usageRequestId": self.usage_request_id,
            "remainingTokens": self.remaining_tokens,
            "reserveTokens": self.reserve_tokens,
            "collapseTriggerTokens": self.collapse_trigger_tokens,
            "collapseTriggerMessages": self.collapse_trigger_messages,
            "compactionTriggerTokens": self.compaction_trigger_tokens,
            "collapseReady": self.collapse_ready,
            "compactionReady": self.compaction_ready,
            "compactionEnabled": self.compaction_enabled,
            "messageCount": self.message_count,
            "percentFull": self.percent_full,
        }


def latest_usage_from_transcript(messages: list[dict[str, Any]]) -> dict[str, Any]:
    for message in reversed(messages):
        if message.get("role") != "assistant":
            continue
        usage = _usage_from_transcript_message(message)
        if not usage.get("available"):
            continue
        run_trace = message.get("runTrace") if isinstance(message.get("runTrace"), dict) else {}
        usage["updated_at"] = str(run_trace.get("finishedAt") or "")
        usage["request_id"] = str(run_trace.get("requestId") or "")
        return usage
    return {
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "available": False,
        "updated_at": "",
        "request_id": "",
    }


def context_reserve_tokens(config: AppConfig) -> int:
    for key in ("context_compaction.reserve_tokens", "contextCompaction.reserveTokens"):
        value = config.get(key, None)
        if value is None:
            continue
        try:
            return max(0, int(value))
        except (TypeError, ValueError):
            continue
    return DEFAULT_COMPACTION_RESERVE_TOKENS


def context_collapse_trigger_messages(config: AppConfig) -> int:
    for key in ("context_collapse.trigger_messages", "contextCollapse.triggerMessages"):
        value = config.get(key, None)
        if value is None:
            continue
        try:
            return max(1, int(value))
        except (TypeError, ValueError):
            continue
    return 40


def context_collapse_trigger_tokens(config: AppConfig) -> int:
    for key in ("context_collapse.trigger_tokens", "contextCollapse.triggerTokens"):
        value = config.get(key, None)
        if value is None:
            continue
        try:
            return max(1, int(value))
        except (TypeError, ValueError):
            continue
    return 40_000


def has_compactable_history(messages: list[BaseMessage]) -> bool:
    user_indices = [
        index
        for index, message in enumerate(messages)
        if isinstance(message, HumanMessage)
        and not (isinstance(message.content, str) and message.content.strip().startswith(SUMMARY_MESSAGE_PREFIX))
    ]
    return len(user_indices) >= 2 and user_indices[-2] > 0


def manual_compaction_cutoff_index(messages: list[dict[str, Any]]) -> int | None:
    user_indices = [
        index
        for index, message in enumerate(messages)
        if _role_text(message.get("role"))
        == "user"
        and not _is_summary_transcript_message(message)
    ]
    if len(user_indices) < 2:
        return None
    cutoff = user_indices[-2]
    return cutoff if cutoff > 0 else None


def model_visible_transcript_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [message for message in messages if _role_text(message.get("role")) != "divider"]


def _usage_from_transcript_message(message: dict[str, Any]) -> dict[str, Any]:
    metadata = message.get("metadata") if isinstance(message.get("metadata"), dict) else {}
    response_metadata = metadata.get("response_metadata") if isinstance(metadata.get("response_metadata"), dict) else {}
    candidates = [
        metadata.get("usage"),
        response_metadata.get("usage"),
        response_metadata.get("usage_metadata"),
        response_metadata.get("usageMetadata"),
        response_metadata.get("token_usage"),
        response_metadata.get("tokenUsage"),
    ]
    for candidate in candidates:
        usage = _normalize_usage(candidate)
        if usage.get("available"):
            return usage
    return {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "available": False}


def _normalize_usage(value: Any) -> dict[str, Any]:
    if value is None:
        return {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "available": False}
    if is_dataclass(value) and not isinstance(value, type):
        value = asdict(value)
    elif hasattr(value, "model_dump"):
        try:
            value = value.model_dump(mode="json")
        except TypeError:
            value = value.model_dump()
    elif hasattr(value, "to_dict"):
        value = value.to_dict()
    if not isinstance(value, dict):
        return {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "available": False}
    input_tokens = _first_int(
        value,
        "input_tokens",
        "inputTokens",
        "prompt_tokens",
        "promptTokens",
        "input_token_count",
        "inputTokenCount",
    )
    output_tokens = _first_int(
        value,
        "output_tokens",
        "outputTokens",
        "completion_tokens",
        "completionTokens",
    )
    total_tokens = _first_int(value, "total_tokens", "totalTokens")
    if total_tokens <= 0 and (input_tokens or output_tokens):
        total_tokens = input_tokens + output_tokens
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "available": bool(input_tokens or output_tokens or total_tokens),
    }


def _first_int(mapping: dict[str, Any], *keys: str) -> int:
    for key in keys:
        value = mapping.get(key)
        try:
            number = int(value)
        except (TypeError, ValueError):
            continue
        if number > 0:
            return number
    return 0


def _role_text(value: Any) -> str:
    return str(value or "").strip().lower()


def _is_summary_transcript_message(message: dict[str, Any]) -> bool:
    role = _role_text(message.get("role"))
    if role == "summary":
        return True
    content = message.get("content", "")
    return isinstance(content, str) and content.strip().startswith(SUMMARY_MESSAGE_PREFIX)


__all__ = [
    "AgentContextStatus",
    "context_collapse_trigger_messages",
    "context_collapse_trigger_tokens",
    "context_reserve_tokens",
    "has_compactable_history",
    "latest_usage_from_transcript",
    "manual_compaction_cutoff_index",
    "model_visible_transcript_messages",
]
