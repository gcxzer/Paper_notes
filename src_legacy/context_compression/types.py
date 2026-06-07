from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol
from typing import Any


class ContextSummaryProvider(Protocol):
    def __call__(
        self,
        turns: list[dict[str, Any]],
        focus_topic: str | None = None,
        *,
        current_summary: str = "",
        max_output_tokens: int | None = None,
    ) -> str | None:
        """Generate a structured handoff summary for compacted turns."""


DEFAULT_FALLBACK_CONTEXT_LENGTH = 256_000
MINIMUM_CONTEXT_LENGTH = 64_000


@dataclass(slots=True)
class ContextCompressionConfig:
    enabled: bool = True
    context_length: int = DEFAULT_FALLBACK_CONTEXT_LENGTH
    threshold_percent: float = 0.80
    target_ratio: float = 0.20
    protect_first_n: int = 3
    protect_last_n: int = 3
    minimum_context_length: int = MINIMUM_CONTEXT_LENGTH
    min_messages: int | None = None
    max_estimated_tokens: int | None = None
    tail_token_budget: int | None = None
    large_tool_result_chars: int = 200
    max_summary_chars: int | None = None
    summary_min_tokens: int = 2_000
    summary_tokens_ceiling: int = 12_000
    summary_failure_cooldown_seconds: int = 600
    summary_provider_name: str | None = None
    summary_model: str | None = None
    max_preflight_passes: int = 3
    max_overflow_retries: int = 3

    def resolved_threshold_tokens(self, *, context_length: int | None = None) -> int:
        if self.max_estimated_tokens is not None:
            return self.max_estimated_tokens
        resolved_context = context_length if context_length is not None and context_length > 0 else self.context_length
        return max(int(resolved_context * self.threshold_percent), self.minimum_context_length)

    def resolved_tail_token_budget(self, *, context_length: int | None = None) -> int:
        if self.tail_token_budget is not None:
            return self.tail_token_budget
        return int(self.resolved_threshold_tokens(context_length=context_length) * self.target_ratio)

    def resolved_min_messages(self) -> int:
        if self.min_messages is not None:
            return self.min_messages
        return self.protect_first_n + 3 + 1

    def resolved_max_summary_tokens(self, *, context_length: int | None = None) -> int:
        resolved_context = context_length if context_length is not None and context_length > 0 else self.context_length
        return min(int(resolved_context * 0.05), self.summary_tokens_ceiling)

    def resolved_summary_budget_tokens(
        self,
        messages: list[dict[str, Any]],
        *,
        estimated_tokens: int | None = None,
        context_length: int | None = None,
    ) -> int:
        content_tokens = estimated_tokens if estimated_tokens is not None else 0
        budget = int(content_tokens * self.target_ratio)
        return max(self.summary_min_tokens, min(budget, self.resolved_max_summary_tokens(context_length=context_length)))

    def resolved_max_summary_chars(self, *, context_length: int | None = None) -> int:
        if self.max_summary_chars is not None:
            return self.max_summary_chars
        return self.resolved_max_summary_tokens(context_length=context_length) * 4


@dataclass(slots=True)
class ContextCompressionStats:
    compressed: bool = False
    before_message_count: int = 0
    after_message_count: int = 0
    before_estimated_tokens: int = 0
    after_estimated_tokens: int = 0
    pruned_tool_results: int = 0
    summarized_message_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ContextCompressionResult:
    messages: list[dict[str, Any]]
    stats: ContextCompressionStats
    summary: str | None = None


@dataclass(slots=True)
class ContextCompressionCheckpoint:
    session_id: str
    current_summary: str = ""
    compressed_until_message_index: int = 0
    source_message_count: int = 0
    compression_count: int = 0
    last_error: str | None = None
    fallback_used: bool = False
    last_savings_pct: float = 0.0
    updated_at: str = ""

    @property
    def summary_available(self) -> bool:
        return bool(self.current_summary.strip())

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": 1,
            "session_id": self.session_id,
            "current_summary": self.current_summary,
            "compressed_until_message_index": self.compressed_until_message_index,
            "source_message_count": self.source_message_count,
            "compression_count": self.compression_count,
            "last_error": self.last_error,
            "fallback_used": self.fallback_used,
            "last_savings_pct": self.last_savings_pct,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ContextCompressionCheckpoint":
        return cls(
            session_id=str(data.get("session_id") or data.get("sessionId") or ""),
            current_summary=str(data.get("current_summary") or ""),
            compressed_until_message_index=int(
                data.get("compressed_until_message_index")
                or data.get("compressedUntilMessageIndex")
                or 0
            ),
            source_message_count=int(data.get("source_message_count") or data.get("sourceMessageCount") or 0),
            compression_count=int(data.get("compression_count") or data.get("compressionCount") or 0),
            last_error=data.get("last_error") or data.get("lastError"),
            fallback_used=bool(data.get("fallback_used") or data.get("fallbackUsed")),
            last_savings_pct=float(data.get("last_savings_pct") or data.get("lastSavingsPct") or 0.0),
            updated_at=str(data.get("updated_at") or data.get("updatedAt") or ""),
        )
