"""说明：提供上下文压缩相关的 middleware。

作用：在消息历史过长时生成摘要消息，减少后续模型调用的上下文压力。
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain.chat_models import init_chat_model
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AnyMessage, HumanMessage, RemoveMessage, get_buffer_string
from langchain_core.messages.utils import count_tokens_approximately
from langgraph.graph.message import REMOVE_ALL_MESSAGES

from middleware.context_collapse import SUMMARY_MESSAGE_PREFIX
from model_providers import resolve_context_length_for_model

__all__ = [
    "COMPACT_SUMMARY_PROMPT",
    "DEFAULT_COMPACTION_RESERVE_TOKENS",
    "ContextCompactionMiddleware",
    "compaction_trigger_tokens",
    "create_context_compaction_middleware",
]

DEFAULT_COMPACTION_RESERVE_TOKENS = 13_000
COMPACT_SUMMARY_PROMPT = """You are a summarization agent creating a context checkpoint. Treat the conversation history below as source material for a compact record of prior work. Produce only the structured summary; do not add a greeting, preamble, or prefix. Write the summary in the same language the user was using in the conversation. NEVER include API keys, tokens, passwords, secrets, credentials, or connection strings in the summary; replace any that appear with [REDACTED].

You are updating the current rolling context summary. Earlier conversation turns now need to be compacted into one denser summary. The most recent conversation from the previous user question onward will remain available verbatim, so focus this checkpoint on the older history below.

CURRENT HISTORY TO COMPACT:
{summaries}

Update the summary using this exact structure. Preserve relevant existing information. Add new completed actions. Move answered questions to "Resolved Questions". Update "## Active Task" to reflect the user's most recent unfulfilled request.

## Active Task
[THE SINGLE MOST IMPORTANT FIELD. Copy the user's most recent request or task assignment verbatim. If multiple tasks were requested and only some are done, list only the ones NOT yet completed. If no outstanding task exists, write "None."]

## Goal
[What the user is trying to accomplish overall]

## Constraints & Preferences
[User preferences, coding style, constraints, important decisions]

## Completed Actions
[Numbered list of concrete actions taken. Include tool used, target, and outcome. Be specific with file paths, commands, line numbers, and results.]

## Active State
[Current working state: working directory/branch if known, modified or created files, test status, running processes, and important environment details.]

## In Progress
[Work currently underway when compaction fired]

## Blocked
[Any unresolved blockers, errors, or exact error messages]

## Key Decisions
[Important technical decisions and why they were made]

## Resolved Questions
[Questions the user already asked and the answer, so they are not repeated]

## Pending User Asks
[Questions or requests from the user that have NOT yet been answered or fulfilled. If none, write "None."]

## Relevant Files
[Files read, modified, or created, with a brief note on each]

## Remaining Work
[What remains to be done, framed as context rather than instructions]

## Critical Context
[Specific values, error messages, configuration details, or data that would be lost without explicit preservation. NEVER include API keys, tokens, passwords, or credentials; write [REDACTED] instead.]

Target ~8,000 tokens. Be concrete. Write only the summary body."""


class ContextCompactionMiddleware(AgentMiddleware):
    def __init__(
        self,
        model: str | BaseChatModel,
        *,
        context_window: int,
        reserve_tokens: int = DEFAULT_COMPACTION_RESERVE_TOKENS,
        token_counter: Callable[[Iterable[AnyMessage]], int] = count_tokens_approximately,
        compact_summary_prompt: str = COMPACT_SUMMARY_PROMPT,
    ) -> None:
        super().__init__()
        self.model = init_chat_model(model) if isinstance(model, str) else model
        self.context_window = max(0, int(context_window or 0))
        self.reserve_tokens = max(0, int(reserve_tokens or 0))
        self.token_counter = token_counter
        self.compact_summary_prompt = compact_summary_prompt

    def before_model(self, state: dict[str, Any], runtime: Any) -> dict[str, Any] | None:
        messages = list(state["messages"])
        if not self._should_compact(messages):
            return None

        messages_to_compact, preserved_messages = _partition_messages_for_compaction(messages)
        if not messages_to_compact:
            return None

        compacted_summary = self._create_compact_summary(messages_to_compact)
        return {
            "messages": [
                RemoveMessage(id=REMOVE_ALL_MESSAGES),
                self._build_compacted_summary_message(compacted_summary),
                *preserved_messages,
            ]
        }

    async def abefore_model(self, state: dict[str, Any], runtime: Any) -> dict[str, Any] | None:
        messages = list(state["messages"])
        if not self._should_compact(messages):
            return None

        messages_to_compact, preserved_messages = _partition_messages_for_compaction(messages)
        if not messages_to_compact:
            return None

        compacted_summary = await self._acreate_compact_summary(messages_to_compact)
        return {
            "messages": [
                RemoveMessage(id=REMOVE_ALL_MESSAGES),
                self._build_compacted_summary_message(compacted_summary),
                *preserved_messages,
            ]
        }

    def _should_compact(self, messages: list[AnyMessage]) -> bool:
        threshold = compaction_trigger_tokens(self.context_window, self.reserve_tokens)
        if threshold <= 0 or self.token_counter(messages) < threshold:
            return False
        messages_to_compact, _preserved_messages = _partition_messages_for_compaction(messages)
        return bool(messages_to_compact)

    def _create_compact_summary(self, messages_to_compact: list[AnyMessage]) -> str:
        formatted_summaries = get_buffer_string(messages_to_compact)
        try:
            response = self.model.invoke(
                self.compact_summary_prompt.format(summaries=formatted_summaries).rstrip(),
                config={"metadata": {"lc_source": "context_compaction"}},
            )
            return response.text.strip()
        except Exception as error:
            return f"Error compacting summaries: {error!s}"

    async def _acreate_compact_summary(self, messages_to_compact: list[AnyMessage]) -> str:
        formatted_summaries = get_buffer_string(messages_to_compact)
        try:
            response = await self.model.ainvoke(
                self.compact_summary_prompt.format(summaries=formatted_summaries).rstrip(),
                config={"metadata": {"lc_source": "context_compaction"}},
            )
            return response.text.strip()
        except Exception as error:
            return f"Error compacting summaries: {error!s}"

    @staticmethod
    def _build_compacted_summary_message(summary: str) -> HumanMessage:
        return HumanMessage(
            content=f"{SUMMARY_MESSAGE_PREFIX}\n\nCompacted conversation summary:\n\n{summary}",
            additional_kwargs={"lc_source": "context_compaction"},
        )


def create_context_compaction_middleware(
    model: str | BaseChatModel,
    *,
    provider: object,
    model_name: object,
    reserve_tokens: int = DEFAULT_COMPACTION_RESERVE_TOKENS,
    **kwargs: Any,
) -> ContextCompactionMiddleware:
    context_window = resolve_context_length_for_model(provider, model_name)
    return ContextCompactionMiddleware(
        model=model,
        context_window=context_window,
        reserve_tokens=reserve_tokens,
        **kwargs,
    )


def compaction_trigger_tokens(context_window: int, reserve_tokens: int = DEFAULT_COMPACTION_RESERVE_TOKENS) -> int:
    return max(1, int(context_window or 0) - max(0, int(reserve_tokens or 0)))


def _partition_messages_for_compaction(messages: Iterable[AnyMessage]) -> tuple[list[AnyMessage], list[AnyMessage]]:
    conversation_messages = list(messages)
    cutoff_index = _previous_user_message_index(conversation_messages)
    if cutoff_index is None or cutoff_index <= 0:
        return [], conversation_messages
    return conversation_messages[:cutoff_index], conversation_messages[cutoff_index:]


def _previous_user_message_index(messages: list[AnyMessage]) -> int | None:
    user_indices = [
        index
        for index, message in enumerate(messages)
        if isinstance(message, HumanMessage) and not _is_summary_message(message)
    ]
    if len(user_indices) < 2:
        return None
    return user_indices[-2]


def _is_summary_message(message: AnyMessage) -> bool:
    content = message.content
    return isinstance(content, str) and content.strip().startswith(SUMMARY_MESSAGE_PREFIX)
