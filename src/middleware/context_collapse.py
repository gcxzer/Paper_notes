"""Context collapse middleware for Paper Notes.

This module keeps LangChain's official ``SummarizationMiddleware`` behavior and
only changes the treatment of generated summary messages: new summaries are
prefixed with ``[summary]``, and existing ``[summary]`` messages are preserved
instead of being summarized again. Constructor arguments are passed through to
LangChain, so omitted options such as ``summary_prompt`` use official defaults.
"""

from __future__ import annotations

from typing import Any

from langchain.agents.middleware import SummarizationMiddleware
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AnyMessage, HumanMessage, RemoveMessage
from langgraph.graph.message import REMOVE_ALL_MESSAGES


SUMMARY_MESSAGE_PREFIX = "[summary]"


class ContextCollapseMiddleware(SummarizationMiddleware):
    def before_model(self, state: dict[str, Any], runtime: Any) -> dict[str, Any] | None:
        messages = state["messages"]
        self._ensure_message_ids(messages)

        total_tokens = self.token_counter(messages)
        if not self._should_summarize(messages, total_tokens):
            return None

        cutoff_index = self._determine_cutoff_index(messages)
        if cutoff_index <= 0:
            return None

        messages_to_summarize, preserved_summaries, preserved_messages = _partition_preserving_summaries(
            messages,
            cutoff_index,
        )
        if not messages_to_summarize:
            return None

        summary = self._create_summary(messages_to_summarize)

        return {
            "messages": [
                RemoveMessage(id=REMOVE_ALL_MESSAGES),
                *preserved_summaries,
                *self._build_new_messages(summary),
                *preserved_messages,
            ]
        }

    async def abefore_model(self, state: dict[str, Any], runtime: Any) -> dict[str, Any] | None:
        messages = state["messages"]
        self._ensure_message_ids(messages)

        total_tokens = self.token_counter(messages)
        if not self._should_summarize(messages, total_tokens):
            return None

        cutoff_index = self._determine_cutoff_index(messages)
        if cutoff_index <= 0:
            return None

        messages_to_summarize, preserved_summaries, preserved_messages = _partition_preserving_summaries(
            messages,
            cutoff_index,
        )
        if not messages_to_summarize:
            return None

        summary = await self._acreate_summary(messages_to_summarize)

        return {
            "messages": [
                RemoveMessage(id=REMOVE_ALL_MESSAGES),
                *preserved_summaries,
                *self._build_new_messages(summary),
                *preserved_messages,
            ]
        }

    @staticmethod
    def _build_new_messages(summary: str) -> list[HumanMessage]:
        return [
            HumanMessage(
                content=f"{SUMMARY_MESSAGE_PREFIX}\n\nHere is a summary of the conversation to date:\n\n{summary}",
                additional_kwargs={"lc_source": "context_collapse"},
            )
        ]


def create_context_collapse_middleware(
    model: str | BaseChatModel,
    **kwargs: Any,
) -> ContextCollapseMiddleware:
    return ContextCollapseMiddleware(model=model, **kwargs)


def _partition_preserving_summaries(
    conversation_messages: list[AnyMessage],
    cutoff_index: int,
) -> tuple[list[AnyMessage], list[AnyMessage], list[AnyMessage]]:
    messages_to_summarize: list[AnyMessage] = []
    preserved_summaries: list[AnyMessage] = []

    for message in conversation_messages[:cutoff_index]:
        if _is_summary_message(message):
            preserved_summaries.append(message)
        else:
            messages_to_summarize.append(message)

    return messages_to_summarize, preserved_summaries, conversation_messages[cutoff_index:]


def _is_summary_message(message: AnyMessage) -> bool:
    content = message.content
    return isinstance(content, str) and content.strip().startswith(SUMMARY_MESSAGE_PREFIX)


__all__ = [
    "ContextCollapseMiddleware",
    "SUMMARY_MESSAGE_PREFIX",
    "SummarizationMiddleware",
    "create_context_collapse_middleware",
]
