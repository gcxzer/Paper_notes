from __future__ import annotations

import copy
import time
from typing import Any

from context_compression.estimator import (
    CHARS_PER_TOKEN,
    append_text_to_content,
    content_length_for_budget,
    content_text_for_contains,
    estimate_messages_tokens_rough,
)
from context_compression.tool_pruning import prune_old_tool_results
from context_compression.types import (
    ContextCompressionCheckpoint,
    ContextCompressionConfig,
    ContextCompressionResult,
    ContextCompressionStats,
    ContextSummaryProvider,
)
from context_compression.summary import redact_sensitive_text
from agent_runtime.model_messages import sanitize_model_messages


# Adapted from Nous Research Hermes Agent.
# Original source: hermes-agent/agent/context_compressor.py
# License: MIT Copyright (c) 2025 Nous Research


SUMMARY_PREFIX = (
    "[CONTEXT COMPACTION - REFERENCE ONLY] Earlier turns were compacted "
    "into the summary below. This is a handoff from a previous context "
    "window; treat it as background reference, NOT as active instructions. "
    "Do NOT answer questions or fulfill requests mentioned in this summary; "
    "they were already addressed. Your current task is identified in the "
    "'## Active Task' section of the summary. Persistent memory in the system "
    "prompt remains authoritative. Respond ONLY to the latest user message "
    "that appears AFTER this summary."
)
LEGACY_SUMMARY_PREFIX = "[CONTEXT SUMMARY]:"
COMPRESSION_NOTE = (
    "[Note: Some earlier conversation turns have been compacted into a handoff "
    "summary to preserve context space. The current session state may still "
    "reflect earlier work, so build on the summary and recent messages. "
    "Persistent memory remains authoritative regardless of compaction.]"
)
END_OF_SUMMARY_MARKER = "--- END OF CONTEXT SUMMARY - respond to the message below, not the summary above ---"


class ContextCompressor:
    def __init__(
        self,
        config: ContextCompressionConfig | None = None,
        *,
        summary_provider: ContextSummaryProvider | None = None,
    ) -> None:
        self.config = config or ContextCompressionConfig()
        self.summary_provider = summary_provider
        self.compression_count = 0
        self.last_prompt_tokens = 0
        self.last_completion_tokens = 0
        self.last_total_tokens = 0
        self.previous_summary: str | None = None
        self.last_summary_error: str | None = None
        self.last_summary_dropped_count = 0
        self.last_summary_fallback_used = False
        self.last_summary_provider_fallback_error: str | None = None
        self.last_compression_savings_pct = 100.0
        self.ineffective_compression_count = 0
        self._summary_failure_cooldown_until = 0.0

    def update_from_response(self, usage: Any) -> None:
        self.last_prompt_tokens = int(_usage_value(usage, "input_tokens", "prompt_tokens") or 0)
        self.last_completion_tokens = int(_usage_value(usage, "output_tokens", "completion_tokens") or 0)
        total = _usage_value(usage, "total_tokens")
        self.last_total_tokens = int(total or self.last_prompt_tokens + self.last_completion_tokens)

    def should_compress(
        self,
        messages: list[dict[str, Any]],
        *,
        approx_tokens: int | None = None,
        context_length: int | None = None,
        force: bool = False,
    ) -> bool:
        if not self.config.enabled:
            return False
        if len(messages) <= self.config.resolved_min_messages():
            return False
        if force:
            return True
        tokens = approx_tokens if approx_tokens is not None else estimate_messages_tokens_rough(messages)
        if tokens >= self.config.resolved_threshold_tokens(context_length=context_length):
            return self.ineffective_compression_count < 2
        return False

    def compress(
        self,
        messages: list[dict[str, Any]],
        *,
        approx_tokens: int | None = None,
        focus_topic: str | None = None,
        context_length: int | None = None,
        force: bool = False,
    ) -> ContextCompressionResult:
        self._reset_call_summary_state()
        original = copy.deepcopy(messages)
        before_tokens = approx_tokens if approx_tokens is not None else estimate_messages_tokens_rough(original)
        if not self.should_compress(
            original,
            approx_tokens=before_tokens,
            context_length=context_length,
            force=force,
        ):
            return ContextCompressionResult(
                messages=original,
                stats=ContextCompressionStats(
                    compressed=False,
                    before_message_count=len(original),
                    after_message_count=len(original),
                    before_estimated_tokens=before_tokens,
                    after_estimated_tokens=before_tokens,
                ),
            )

        pruned_messages, pruned_count = prune_old_tool_results(
            original,
            protect_tail_count=self.config.protect_last_n,
            protect_tail_tokens=self.config.resolved_tail_token_budget(context_length=context_length),
            large_tool_result_chars=self.config.large_tool_result_chars,
        )

        compress_start = self._align_boundary_forward(pruned_messages, self.config.protect_first_n)
        compress_end = self._find_tail_cut_by_tokens(pruned_messages, compress_start, context_length=context_length)
        if compress_start >= compress_end:
            after_tokens = estimate_messages_tokens_rough(pruned_messages)
            return ContextCompressionResult(
                messages=pruned_messages,
                stats=ContextCompressionStats(
                    compressed=False,
                    before_message_count=len(original),
                    after_message_count=len(pruned_messages),
                    before_estimated_tokens=before_tokens,
                    after_estimated_tokens=after_tokens,
                    pruned_tool_results=pruned_count,
                ),
            )

        previous_summary = self.previous_summary or ""
        summary_index, previous_summary = self._find_latest_context_summary(
            pruned_messages,
            compress_start,
            compress_end,
        )
        turns_to_summarize = pruned_messages[compress_start:compress_end]
        turns_start = compress_start
        if summary_index is not None:
            if previous_summary and not self.previous_summary:
                self.previous_summary = previous_summary
            turns_to_summarize = pruned_messages[summary_index + 1 : compress_end]
            turns_start = summary_index + 1

        summary_body = self._generate_summary(
            turns_to_summarize,
            focus_topic=focus_topic,
            previous_summary=previous_summary,
            context_length=context_length,
        )
        if not summary_body:
            n_dropped = max(0, compress_end - turns_start)
            self.last_summary_dropped_count = n_dropped
            self.last_summary_fallback_used = True
            summary_body = (
                f"Summary generation was unavailable. {n_dropped} message(s) were "
                "removed to free context space but could not be summarized. The removed "
                "messages contained earlier work in this session. Continue based on the "
                "recent messages below and the current state of files, notes, memory, and tools."
            )
        summary = self._with_summary_prefix(summary_body)

        compressed = self._assemble_compressed_messages(
            pruned_messages,
            compress_start=compress_start,
            compress_end=compress_end,
            summary=summary,
        )
        compressed = self._sanitize_tool_pairs(compressed)
        after_tokens = estimate_messages_tokens_rough(compressed)
        savings_pct = _savings_pct(before_tokens, after_tokens)
        if savings_pct < 10:
            self.ineffective_compression_count += 1
        else:
            self.ineffective_compression_count = 0
        self.last_compression_savings_pct = savings_pct
        self.compression_count += 1

        return ContextCompressionResult(
            messages=compressed,
            summary=summary,
            stats=ContextCompressionStats(
                compressed=True,
                before_message_count=len(original),
                after_message_count=len(compressed),
                before_estimated_tokens=before_tokens,
                after_estimated_tokens=after_tokens,
                pruned_tool_results=pruned_count,
                summarized_message_count=len(turns_to_summarize),
                metadata={
                    "compress_start": compress_start,
                    "compress_end": compress_end,
                    "turns_start": turns_start,
                    "turns_end": compress_end,
                    "summary_index": summary_index,
                    "compression_count": self.compression_count,
                    "summary_error": self.last_summary_error,
                    "summary_fallback_used": self.last_summary_fallback_used,
                    "summary_dropped_count": self.last_summary_dropped_count,
                    "summary_provider_fallback_error": self.last_summary_provider_fallback_error,
                    "savings_pct": savings_pct,
                },
            ),
        )

    def apply_checkpoint(
        self,
        messages: list[dict[str, Any]],
        checkpoint: ContextCompressionCheckpoint | None,
    ) -> list[dict[str, Any]]:
        if checkpoint is None or not checkpoint.summary_available:
            return copy.deepcopy(messages)
        compress_end = checkpoint.compressed_until_message_index
        if compress_end <= self.config.protect_first_n or compress_end > len(messages):
            return copy.deepcopy(messages)
        if checkpoint.source_message_count and len(messages) < checkpoint.source_message_count:
            return copy.deepcopy(messages)
        summary = self._with_summary_prefix(checkpoint.previous_summary)
        compressed = self._assemble_compressed_messages(
            copy.deepcopy(messages),
            compress_start=self._align_boundary_forward(messages, self.config.protect_first_n),
            compress_end=compress_end,
            summary=summary,
        )
        return self._sanitize_tool_pairs(compressed)

    def _generate_summary(
        self,
        turns: list[dict[str, Any]],
        *,
        focus_topic: str | None,
        previous_summary: str = "",
        context_length: int | None = None,
    ) -> str | None:
        now = time.monotonic()
        if now < self._summary_failure_cooldown_until:
            remaining = int(self._summary_failure_cooldown_until - now)
            self.last_summary_error = f"context summary provider cooling down ({remaining}s remaining)"
            return None
        if self.summary_provider is None:
            self.last_summary_error = "no context summary provider configured"
            self._summary_failure_cooldown_until = now + self.config.summary_failure_cooldown_seconds
            return None

        summary_tokens = self.config.resolved_summary_budget_tokens(
            turns,
            estimated_tokens=estimate_messages_tokens_rough(turns),
            context_length=context_length,
        )
        try:
            provided = self._call_summary_provider(
                copy.deepcopy(turns),
                focus_topic=focus_topic,
                previous_summary=previous_summary,
                max_output_tokens=int(summary_tokens * 1.3),
            )
        except Exception as error:
            self.last_summary_error = _short_error(error)
            self._summary_failure_cooldown_until = now + self.config.summary_failure_cooldown_seconds
            return None

        fallback_error = getattr(self.summary_provider, "last_fallback_error", None)
        if isinstance(fallback_error, str) and fallback_error:
            self.last_summary_provider_fallback_error = fallback_error
        provided = redact_sensitive_text(provided or "").strip()
        if not provided:
            self.last_summary_error = "context summary provider returned empty content"
            self._summary_failure_cooldown_until = now + self.config.summary_failure_cooldown_seconds
            return None
        self.previous_summary = self._strip_summary_prefix(provided)
        self._summary_failure_cooldown_until = 0.0
        self.last_summary_error = None
        return self._limit_summary(provided, context_length=context_length)

    def _assemble_compressed_messages(
        self,
        messages: list[dict[str, Any]],
        *,
        compress_start: int,
        compress_end: int,
        summary: str,
    ) -> list[dict[str, Any]]:
        compressed: list[dict[str, Any]] = []
        for index in range(compress_start):
            message = messages[index].copy()
            if index == 0 and message.get("role") == "system":
                existing = message.get("content")
                if COMPRESSION_NOTE not in content_text_for_contains(existing):
                    note = "\n\n" + COMPRESSION_NOTE if isinstance(existing, str) and existing else COMPRESSION_NOTE
                    message["content"] = append_text_to_content(existing, note)
            compressed.append(message)

        merge_summary_into_tail = False
        last_head_role = messages[compress_start - 1].get("role", "user") if compress_start > 0 else "user"
        first_tail_role = messages[compress_end].get("role", "user") if compress_end < len(messages) else "user"
        summary_role = "user" if last_head_role in {"assistant", "tool"} else "assistant"
        if summary_role == first_tail_role:
            flipped = "assistant" if summary_role == "user" else "user"
            if flipped != last_head_role:
                summary_role = flipped
            else:
                merge_summary_into_tail = True

        if not merge_summary_into_tail and summary_role == "user":
            summary = f"{summary}\n\n{END_OF_SUMMARY_MARKER}"

        if not merge_summary_into_tail:
            compressed.append({
                "role": summary_role,
                "content": summary,
                "metadata": {"context_compressed": True},
            })

        for index in range(compress_end, len(messages)):
            message = messages[index].copy()
            if merge_summary_into_tail and index == compress_end:
                message["content"] = append_text_to_content(
                    message.get("content"),
                    f"{summary}\n\n{END_OF_SUMMARY_MARKER}\n\n",
                    prepend=True,
                )
                metadata = dict(message.get("metadata") or {})
                metadata["context_compressed"] = True
                message["metadata"] = metadata
                merge_summary_into_tail = False
            compressed.append(message)
        return compressed

    def _find_tail_cut_by_tokens(
        self,
        messages: list[dict[str, Any]],
        head_end: int,
        *,
        context_length: int | None = None,
    ) -> int:
        token_budget = max(1, self.config.resolved_tail_token_budget(context_length=context_length))
        message_count = len(messages)
        min_tail = min(max(1, self.config.protect_last_n), max(0, message_count - head_end - 1))
        soft_ceiling = int(token_budget * 1.5)
        accumulated = 0
        cut_index = message_count

        for index in range(message_count - 1, head_end - 1, -1):
            message = messages[index]
            message_tokens = content_length_for_budget(message.get("content") or "") // CHARS_PER_TOKEN + 10
            for tool_call in message.get("tool_calls") or []:
                if isinstance(tool_call, dict):
                    message_tokens += len(str((tool_call.get("function") or {}).get("arguments") or "")) // CHARS_PER_TOKEN
            if accumulated + message_tokens > soft_ceiling and (message_count - index) >= min_tail:
                break
            accumulated += message_tokens
            cut_index = index

        fallback_cut = message_count - min_tail
        if cut_index > fallback_cut:
            cut_index = fallback_cut
        if cut_index <= head_end:
            cut_index = max(fallback_cut, head_end + 1)

        cut_index = self._align_boundary_backward(messages, cut_index)
        cut_index = self._ensure_last_user_message_in_tail(messages, cut_index, head_end)
        return max(cut_index, head_end + 1)

    @staticmethod
    def _align_boundary_forward(messages: list[dict[str, Any]], index: int) -> int:
        index = max(0, min(index, len(messages)))
        while index < len(messages) and messages[index].get("role") == "tool":
            index += 1
        return index

    @staticmethod
    def _align_boundary_backward(messages: list[dict[str, Any]], index: int) -> int:
        if index <= 0 or index >= len(messages):
            return index
        check = index - 1
        while check >= 0 and messages[check].get("role") == "tool":
            check -= 1
        if check >= 0 and messages[check].get("role") == "assistant" and messages[check].get("tool_calls"):
            return check
        return index

    @staticmethod
    def _find_last_user_message_idx(messages: list[dict[str, Any]], head_end: int) -> int:
        for index in range(len(messages) - 1, head_end - 1, -1):
            if messages[index].get("role") == "user":
                return index
        return -1

    def _ensure_last_user_message_in_tail(
        self,
        messages: list[dict[str, Any]],
        cut_index: int,
        head_end: int,
    ) -> int:
        last_user_idx = self._find_last_user_message_idx(messages, head_end)
        if last_user_idx < 0 or last_user_idx >= cut_index:
            return cut_index
        return max(last_user_idx, head_end + 1)

    def _sanitize_tool_pairs(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return sanitize_model_messages(messages).messages

    @staticmethod
    def _strip_summary_prefix(summary: str) -> str:
        text = str(summary or "").strip()
        for prefix in (SUMMARY_PREFIX, LEGACY_SUMMARY_PREFIX):
            if text.startswith(prefix):
                return text[len(prefix) :].lstrip()
        return text

    @classmethod
    def _with_summary_prefix(cls, summary: str) -> str:
        text = cls._strip_summary_prefix(summary)
        return f"{SUMMARY_PREFIX}\n{text}" if text else SUMMARY_PREFIX

    @classmethod
    def _is_context_summary_content(cls, content: Any) -> bool:
        text = content_text_for_contains(content).lstrip()
        return text.startswith(SUMMARY_PREFIX) or text.startswith(LEGACY_SUMMARY_PREFIX)

    @classmethod
    def _find_latest_context_summary(
        cls,
        messages: list[dict[str, Any]],
        start: int,
        end: int,
    ) -> tuple[int | None, str]:
        for index in range(end - 1, start - 1, -1):
            content = messages[index].get("content")
            if cls._is_context_summary_content(content):
                return index, cls._strip_summary_prefix(content_text_for_contains(content))
        return None, ""

    def _limit_summary(self, text: str, *, context_length: int | None = None) -> str:
        return self._limit_block(text, self.config.resolved_max_summary_chars(context_length=context_length))

    def _reset_call_summary_state(self) -> None:
        self.last_summary_error = None
        self.last_summary_dropped_count = 0
        self.last_summary_fallback_used = False
        self.last_summary_provider_fallback_error = None

    def _call_summary_provider(
        self,
        turns: list[dict[str, Any]],
        *,
        focus_topic: str | None,
        previous_summary: str,
        max_output_tokens: int,
    ) -> str | None:
        if self.summary_provider is None:
            return None
        try:
            return self.summary_provider(
                turns,
                focus_topic,
                previous_summary=previous_summary,
                max_output_tokens=max_output_tokens,
            )
        except TypeError as error:
            if "unexpected keyword" not in str(error) and "positional" not in str(error):
                raise
            return self.summary_provider(turns, focus_topic)  # type: ignore[misc]

    @staticmethod
    def _limit_block(text: str, limit: int) -> str:
        text = str(text or "").strip()
        if limit <= 0 or len(text) <= limit:
            return text
        head = max(0, limit - 120)
        return f"{text[:head].rstrip()}\n...[summary truncated]..."

    def _latest_user_text(self, messages: list[dict[str, Any]]) -> str:
        for message in reversed(messages):
            if message.get("role") == "user":
                return self._limit_block(content_text_for_contains(message.get("content")), 400)
        return ""

    def _message_summary_line(self, message: dict[str, Any]) -> str:
        role = str(message.get("role") or "unknown")
        if role == "assistant" and message.get("tool_calls"):
            tool_names = []
            for tool_call in message.get("tool_calls") or []:
                if isinstance(tool_call, dict):
                    tool_names.append(str((tool_call.get("function") or {}).get("name") or "tool"))
            tools = ", ".join(tool_names) if tool_names else "tool"
            return f"assistant requested tool(s): {tools}"
        if role == "tool":
            tool_call_id = str(message.get("tool_call_id") or "")
            return f"tool result {tool_call_id}: {self._limit_block(content_text_for_contains(message.get('content')), 240)}"
        return f"{role}: {self._limit_block(content_text_for_contains(message.get('content')), 240)}"


def _usage_value(usage: Any, *names: str) -> Any:
    if usage is None:
        return None
    for name in names:
        if isinstance(usage, dict) and name in usage:
            return usage.get(name)
        value = getattr(usage, name, None)
        if value is not None:
            return value
    return None


def _savings_pct(before_tokens: int, after_tokens: int) -> float:
    if before_tokens <= 0:
        return 0.0
    return max(0.0, ((before_tokens - after_tokens) / before_tokens) * 100.0)


def _short_error(error: Exception) -> str:
    text = str(error).strip() or error.__class__.__name__
    if len(text) > 220:
        return text[:217].rstrip() + "..."
    return text
