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
DEFAULT_CONTEXT_COLLAPSE_TRIGGER_MESSAGES = 60
DEFAULT_CONTEXT_COLLAPSE_TRIGGER_TOKENS = 40_000
DEFAULT_CONTEXT_COLLAPSE_KEEP = ("messages", 1)
DEFAULT_CONTEXT_COLLAPSE_KEEP_TO_PREVIOUS_USER_QUESTION = True


class ContextCollapseMiddleware(SummarizationMiddleware):
    def __init__(
        self,
        *args: Any,
        keep_to_previous_user_question: bool = False,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.keep_to_previous_user_question = keep_to_previous_user_question

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

    def _determine_cutoff_index(self, messages: list[AnyMessage]) -> int:
        if self.keep_to_previous_user_question:
            cutoff_index = _previous_user_question_index(messages)
            if cutoff_index is not None:
                return cutoff_index
            return 0
        return super()._determine_cutoff_index(messages)


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


def _previous_user_question_index(messages: list[AnyMessage]) -> int | None:
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


__all__ = [
    "ContextCollapseMiddleware",
    "DEFAULT_CONTEXT_COLLAPSE_KEEP",
    "DEFAULT_CONTEXT_COLLAPSE_KEEP_TO_PREVIOUS_USER_QUESTION",
    "DEFAULT_CONTEXT_COLLAPSE_TRIGGER_MESSAGES",
    "DEFAULT_CONTEXT_COLLAPSE_TRIGGER_TOKENS",
    "SUMMARY_MESSAGE_PREFIX",
    "SummarizationMiddleware",
    "create_context_collapse_middleware",
]
