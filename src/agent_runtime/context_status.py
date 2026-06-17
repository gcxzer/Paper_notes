from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
from typing import Any

from langchain_core.messages import BaseMessage, HumanMessage

from app_config import AppConfig
from middleware import DEFAULT_COMPACTION_RESERVE_TOKENS, SUMMARY_MESSAGE_PREFIX

__all__ = [
    "AgentContextStatus",
    "context_collapse_trigger_messages",
    "context_collapse_trigger_tokens",
    "context_reserve_tokens",
    "has_compactable_history",
    "latest_usage_from_transcript",
    "manual_compaction_cutoff_index",
]


# 前端上下文状态
@dataclass(slots=True)
class AgentContextStatus:
    """描述一个会话当前的上下文占用、实际用量和压缩可用状态。"""

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
        """返回估算 token 占上下文窗口的百分比，供前端进度条显示。"""
        if self.context_window <= 0:
            return 0
        return min(100, max(0, round((self.estimated_tokens / self.context_window) * 100)))

    def to_dict(self) -> dict[str, Any]:
        """转换成前端 API 使用的 camelCase payload。"""
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


# 用量读取
def latest_usage_from_transcript(messages: list[dict[str, Any]]) -> dict[str, Any]:
    """从 transcript 里倒序读取最近一次 assistant 消息的 token usage。"""
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


def _usage_from_transcript_message(message: dict[str, Any]) -> dict[str, Any]:
    """从单条 transcript assistant 消息的 metadata 中提取 usage 候选。"""
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
    """把不同 provider 或 LangChain 对象里的 usage 规整成统一 token 字段。"""
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
    """按候选 key 顺序读取第一个正整数 token 数。"""
    for key in keys:
        value = mapping.get(key)
        try:
            number = int(value)
        except (TypeError, ValueError):
            continue
        if number > 0:
            return number
    return 0


# 压缩阈值配置
def context_reserve_tokens(config: AppConfig) -> int:
    """读取上下文压缩预留 token 数，配置缺失时使用 middleware 默认值。"""
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
    """读取触发 collapse 提醒的消息数量阈值。"""
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
    """读取触发 collapse 提醒的 token 阈值。"""
    for key in ("context_collapse.trigger_tokens", "contextCollapse.triggerTokens"):
        value = config.get(key, None)
        if value is None:
            continue
        try:
            return max(1, int(value))
        except (TypeError, ValueError):
            continue
    return 40_000


# 压缩候选消息
def has_compactable_history(messages: list[BaseMessage]) -> bool:
    """判断 LangChain 消息历史里是否有足够旧的用户轮次可以压缩。"""
    user_indices = [
        index
        for index, message in enumerate(messages)
        if isinstance(message, HumanMessage)
        and not (isinstance(message.content, str) and message.content.strip().startswith(SUMMARY_MESSAGE_PREFIX))
    ]
    return len(user_indices) >= 2 and user_indices[-2] > 0


def manual_compaction_cutoff_index(messages: list[dict[str, Any]]) -> int | None:
    """返回手动压缩时应截断到的 transcript 下标，保留最近两个用户轮次。"""
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


# Transcript 判断
def _role_text(value: Any) -> str:
    """把 transcript role 规整成小写文本。"""
    return str(value or "").strip().lower()


def _is_summary_transcript_message(message: dict[str, Any]) -> bool:
    """判断 transcript 消息是否是上下文压缩产生的 summary。"""
    role = _role_text(message.get("role"))
    if role == "summary":
        return True
    content = message.get("content", "")
    return isinstance(content, str) and content.strip().startswith(SUMMARY_MESSAGE_PREFIX)
