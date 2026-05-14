from __future__ import annotations

import re
from typing import Any

from context_compression.estimator import content_text_for_contains
from model_providers.base import ModelProvider
from model_providers.types import ModelRequest


# Adapted from Nous Research Hermes Agent.
# Original source: hermes-agent/agent/context_compressor.py
# License: MIT Copyright (c) 2025 Nous Research


class LLMContextSummaryProvider:
    def __init__(
        self,
        model_provider: ModelProvider,
        *,
        model: str = "",
        request_options: dict[str, Any] | None = None,
        fallback_provider: ModelProvider | None = None,
        fallback_model: str = "",
    ) -> None:
        self.model_provider = model_provider
        self.model = model
        self.request_options = dict(request_options or {})
        self.fallback_provider = fallback_provider
        self.fallback_model = fallback_model
        self.last_fallback_error: str | None = None

    def __call__(
        self,
        turns: list[dict[str, Any]],
        focus_topic: str | None = None,
        *,
        previous_summary: str = "",
        max_output_tokens: int | None = None,
    ) -> str | None:
        prompt = build_context_summary_prompt(
            turns,
            focus_topic=focus_topic,
            previous_summary=previous_summary,
            target_tokens=max_output_tokens,
        )
        try:
            return self._generate(self.model_provider, self.model, prompt, max_output_tokens=max_output_tokens)
        except Exception as error:
            if self.fallback_provider is None:
                raise
            self.last_fallback_error = _short_error(error)
            return self._generate(
                self.fallback_provider,
                self.fallback_model,
                prompt,
                max_output_tokens=max_output_tokens,
            )

    def _generate(
        self,
        provider: ModelProvider,
        model: str,
        prompt: str,
        *,
        max_output_tokens: int | None,
    ) -> str | None:
        response = provider.generate(ModelRequest(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_output_tokens=max_output_tokens,
            request_options=dict(self.request_options),
        ))
        content = response.content if isinstance(response.content, str) else ""
        return redact_sensitive_text(content.strip()) or None


def build_context_summary_prompt(
    turns: list[dict[str, Any]],
    *,
    focus_topic: str | None = None,
    previous_summary: str = "",
    target_tokens: int | None = None,
) -> str:
    content_to_summarize = serialize_turns_for_summary(turns)
    summary_budget = target_tokens or 2_000
    preamble = (
        "You are a summarization agent creating a context checkpoint. "
        "Treat the conversation turns below as source material for a compact record of prior work. "
        "Produce only the structured summary; do not add a greeting, preamble, or prefix. "
        "Write the summary in the same language the user was using in the conversation. "
        "NEVER include API keys, tokens, passwords, secrets, credentials, or connection strings in the summary; "
        "replace any that appear with [REDACTED]."
    )
    template_sections = f"""## Active Task
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

Target ~{summary_budget} tokens. Be concrete. Write only the summary body."""

    if previous_summary:
        prompt = f"""{preamble}

You are updating a context compaction summary. A previous compaction produced the summary below. New conversation turns have occurred since then and need to be incorporated.

PREVIOUS SUMMARY:
{previous_summary}

NEW TURNS TO INCORPORATE:
{content_to_summarize}

Update the summary using this exact structure. Preserve relevant existing information. Add new completed actions. Move answered questions to "Resolved Questions". Update "## Active Task" to reflect the user's most recent unfulfilled request.

{template_sections}"""
    else:
        prompt = f"""{preamble}

Create a structured checkpoint summary for the conversation after earlier turns are compacted. The summary should preserve enough detail for continuity without re-reading the original turns.

TURNS TO SUMMARIZE:
{content_to_summarize}

Use this exact structure:

{template_sections}"""

    if focus_topic:
        prompt += f"""

FOCUS TOPIC: "{focus_topic}"
Prioritise preserving all information related to this focus topic. For related content, include full detail: exact values, file paths, command outputs, errors, and decisions. For unrelated content, summarize aggressively. Never preserve credentials; use [REDACTED]."""

    return prompt


def serialize_turns_for_summary(turns: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for message in turns:
        role = str(message.get("role") or "unknown")
        content = _truncate_for_summary(redact_sensitive_text(content_text_for_contains(message.get("content"))))
        if role == "assistant" and message.get("tool_calls"):
            calls = []
            for tool_call in message.get("tool_calls") or []:
                if not isinstance(tool_call, dict):
                    continue
                function = tool_call.get("function") or {}
                name = str(function.get("name") or tool_call.get("name") or "?")
                args = redact_sensitive_text(str(function.get("arguments") or tool_call.get("arguments") or ""))
                calls.append(f"  {name}({_truncate_tool_args(args)})")
            if calls:
                content = f"{content}\n[Tool calls:\n" + "\n".join(calls) + "\n]"
        if role == "tool":
            tool_id = str(message.get("tool_call_id") or "")
            parts.append(f"[TOOL RESULT {tool_id}]: {content}")
        else:
            parts.append(f"[{role.upper()}]: {content}")
    return "\n\n".join(parts)


def redact_sensitive_text(value: Any) -> str:
    text = str(value or "")
    replacements = [
        (r"sk-proj-[A-Za-z0-9_\-]{12,}", "sk-proj-[REDACTED]"),
        (r"sk-[A-Za-z0-9_\-]{12,}", "sk-[REDACTED]"),
        (r"(?i)\bBearer\s+[A-Za-z0-9._\-]+", "Bearer [REDACTED]"),
        (
            r"(?i)\b(api[_-]?key|access[_-]?token|refresh[_-]?token|password|secret|credential)s?\b\s*[:=]\s*['\"]?[^'\"\s,;]+",
            r"\1=[REDACTED]",
        ),
    ]
    for pattern, replacement in replacements:
        text = re.sub(pattern, replacement, text)
    return text


def _truncate_for_summary(content: str) -> str:
    if len(content) <= 6_000:
        return content
    return content[:4_000].rstrip() + "\n...[truncated]...\n" + content[-1_500:].lstrip()


def _truncate_tool_args(arguments: str) -> str:
    if len(arguments) <= 1_500:
        return arguments
    return arguments[:1_200].rstrip() + "..."


def _short_error(error: Exception) -> str:
    text = str(error).strip() or error.__class__.__name__
    return text[:220].rstrip()
