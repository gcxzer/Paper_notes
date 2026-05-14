from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from context_compression.estimator import CHARS_PER_TOKEN, content_length_for_budget


# Adapted from Nous Research Hermes Agent.
# Original source: hermes-agent/agent/context_compressor.py
# License: MIT Copyright (c) 2025 Nous Research


PRUNED_TOOL_PLACEHOLDER = "[Old tool output cleared to save context space]"


def truncate_tool_call_args_json(args: str, head_chars: int = 200) -> str:
    try:
        parsed = json.loads(args)
    except (TypeError, ValueError):
        return args

    def shrink(value: Any) -> Any:
        if isinstance(value, str):
            if len(value) > head_chars:
                return value[:head_chars] + "...[truncated]"
            return value
        if isinstance(value, dict):
            return {key: shrink(inner) for key, inner in value.items()}
        if isinstance(value, list):
            return [shrink(inner) for inner in value]
        return value

    return json.dumps(shrink(parsed), ensure_ascii=False)


def summarize_tool_result(tool_name: str, tool_args: str, tool_content: str) -> str:
    try:
        args = json.loads(tool_args) if tool_args else {}
    except (TypeError, ValueError):
        args = {}

    content = tool_content or ""
    content_len = len(content)
    line_count = content.count("\n") + 1 if content.strip() else 0

    if tool_name in {"paper_notes_search", "search_library", "paper_notes.search_library"}:
        query = args.get("query", "?")
        return f"[{tool_name}] query={query!r} ({content_len:,} chars result)"
    if tool_name in {"paper_notes_context", "get_note", "paper_notes.read_note"}:
        note_id = args.get("note_id") or args.get("id") or "?"
        return f"[{tool_name}] note context {note_id} ({content_len:,} chars)"
    if tool_name in {"paper_notes_read_paper", "read_paper_text", "search_paper_text"}:
        note_id = args.get("note_id") or "?"
        action = args.get("action") or ("search_text" if args.get("query") else "read_pages")
        return f"[{tool_name}] {action} for {note_id} ({content_len:,} chars)"
    if tool_name in {"paper_notes_edit", "write_note_section", "append_note_section", "replace_note_section"}:
        note_id = args.get("note_id") or "?"
        action = args.get("action") or tool_name
        return f"[{tool_name}] {action} for {note_id} ({content_len:,} chars)"
    if tool_name == "session_search":
        query = args.get("query", "?")
        return f"[{tool_name}] query={query!r} ({content_len:,} chars result)"
    if tool_name == "persistent_memory":
        action = args.get("action", "?")
        target = args.get("target", "?")
        return f"[{tool_name}] {action} on {target}"

    exit_match = re.search(r'"exit_code"\s*:\s*(-?\d+)', content)
    if exit_match:
        return f"[{tool_name}] exit {exit_match.group(1)}, {line_count} lines output"

    preview = ""
    for key, value in list(args.items())[:2]:
        rendered = str(value)[:40].replace("\n", " ")
        preview += f" {key}={rendered}"
    return f"[{tool_name}]{preview} ({content_len:,} chars result)"


def prune_old_tool_results(
    messages: list[dict[str, Any]],
    *,
    protect_tail_count: int,
    protect_tail_tokens: int | None = None,
    large_tool_result_chars: int = 2_000,
    tool_args_head_chars: int = 200,
) -> tuple[list[dict[str, Any]], int]:
    if not messages:
        return [], 0

    result = [message.copy() for message in messages]
    pruned = 0
    call_id_to_tool = _tool_call_index(result)
    prune_boundary = _prune_boundary(
        result,
        protect_tail_count=protect_tail_count,
        protect_tail_tokens=protect_tail_tokens,
    )

    seen_hashes: dict[str, tuple[int, str]] = {}
    for index in range(len(result) - 1, -1, -1):
        message = result[index]
        if message.get("role") != "tool":
            continue
        content = message.get("content") or ""
        if not isinstance(content, str) or len(content) < large_tool_result_chars:
            continue
        digest = hashlib.md5(content.encode("utf-8", errors="replace")).hexdigest()[:12]
        if digest in seen_hashes and index < prune_boundary:
            result[index] = {
                **message,
                "content": "[Duplicate tool output - same content as a more recent call]",
            }
            pruned += 1
        else:
            seen_hashes[digest] = (index, str(message.get("tool_call_id") or ""))

    for index in range(prune_boundary):
        message = result[index]
        if message.get("role") != "tool":
            continue
        content = message.get("content") or ""
        if not isinstance(content, str):
            continue
        if (
            not content
            or content == PRUNED_TOOL_PLACEHOLDER
            or content.startswith("[Duplicate tool output")
            or len(content) <= large_tool_result_chars
        ):
            continue
        call_id = str(message.get("tool_call_id") or "")
        tool_name, tool_args = call_id_to_tool.get(call_id, ("unknown", ""))
        result[index] = {**message, "content": summarize_tool_result(tool_name, tool_args, content)}
        pruned += 1

    for index in range(prune_boundary):
        message = result[index]
        if message.get("role") != "assistant" or not message.get("tool_calls"):
            continue
        new_tool_calls = []
        modified = False
        for tool_call in message["tool_calls"]:
            if not isinstance(tool_call, dict):
                new_tool_calls.append(tool_call)
                continue
            function = dict(tool_call.get("function") or {})
            args = str(function.get("arguments") or "")
            if len(args) > max(500, tool_args_head_chars):
                new_args = truncate_tool_call_args_json(args, head_chars=tool_args_head_chars)
                if new_args != args:
                    function["arguments"] = new_args
                    tool_call = {**tool_call, "function": function}
                    modified = True
            new_tool_calls.append(tool_call)
        if modified:
            result[index] = {**message, "tool_calls": new_tool_calls}

    return result, pruned


def _tool_call_index(messages: list[dict[str, Any]]) -> dict[str, tuple[str, str]]:
    call_id_to_tool: dict[str, tuple[str, str]] = {}
    for message in messages:
        if message.get("role") != "assistant":
            continue
        for tool_call in message.get("tool_calls") or []:
            if not isinstance(tool_call, dict):
                continue
            call_id = str(tool_call.get("call_id") or tool_call.get("id") or "")
            function = tool_call.get("function") or {}
            if call_id:
                call_id_to_tool[call_id] = (
                    str(function.get("name") or "unknown"),
                    str(function.get("arguments") or ""),
                )
    return call_id_to_tool


def _prune_boundary(
    messages: list[dict[str, Any]],
    *,
    protect_tail_count: int,
    protect_tail_tokens: int | None,
) -> int:
    if protect_tail_tokens is None or protect_tail_tokens <= 0:
        return max(0, len(messages) - max(0, protect_tail_count))

    accumulated = 0
    boundary = len(messages)
    min_protect = min(max(0, protect_tail_count), len(messages))
    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        message_tokens = content_length_for_budget(message.get("content") or "") // CHARS_PER_TOKEN + 10
        for tool_call in message.get("tool_calls") or []:
            if isinstance(tool_call, dict):
                message_tokens += len(str((tool_call.get("function") or {}).get("arguments") or "")) // CHARS_PER_TOKEN
        if accumulated + message_tokens > protect_tail_tokens and (len(messages) - index) >= min_protect:
            boundary = index
            break
        accumulated += message_tokens
        boundary = index

    budget_protect_count = len(messages) - boundary
    protected_count = max(budget_protect_count, min_protect)
    return max(0, len(messages) - protected_count)
