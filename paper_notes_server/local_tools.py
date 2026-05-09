from __future__ import annotations

import json
import re
import uuid
from datetime import datetime
from typing import Callable

from . import config
from .note_editor import MAX_NOTE_BODY_CHARS, extract_note_body_html, normalize_replacement_html
from .storage import is_within, normalize_text, project_path_from_href, read_library


LOCAL_TOOL_NAMES = {"read_current_note_html", "create_note_edit_draft"}
MAX_LOCAL_TOOL_ROUNDS = 4
LOCAL_NOTE_INTENT_PATTERNS = [
    r"\b(local|current|selected)\s+(html\s+)?note\b",
    r"\b(note|html)\b.*\b(read|inspect|summari[sz]e|translate|rewrite|reorganize|append|add|insert|update|edit|modify|delete|remove)\b",
    r"\b(read|inspect|summari[sz]e|translate|rewrite|reorganize|append|add|insert|update|edit|modify|delete|remove)\b.*\b(note|html)\b",
    r"(当前|本地|这份|这个|选中|html).{0,8}(笔记|note)",
    r"(笔记|note|html).{0,18}(读取|读一下|查看|总结|概括|翻译|整理|重写|改写|追加|添加|加入|加上|写入|写进|插入|更新|修改|删除|移除)",
    r"(读取|读一下|查看|总结|概括|翻译|整理|重写|改写|追加|添加|加入|加上|写入|写进|插入|更新|修改|删除|移除).{0,18}(笔记|note|html)",
    r"(笔记|note).{0,12}(开头|结尾|末尾|最后|前面|后面)",
]


def run_harness_with_local_tools(
    *,
    session_id: str,
    user_message: str,
    note_id: str,
    context_lines: list[str],
    invoke_model: Callable[..., dict],
    progress: Callable[[str, str], None] | None = None,
) -> dict:
    has_selected_note = bool(normalize_text(note_id) and note_id != "workspace")
    local_gate_active = has_selected_note and should_use_local_note_gate(user_message)
    prompt = (
        build_initial_prompt(user_message=user_message, note_id=note_id, context_lines=context_lines)
        if local_gate_active
        else build_general_prompt(user_message=user_message, context_lines=context_lines)
    )
    tools = build_local_gate_tools() if local_gate_active else build_agentcore_tools(note_id, include_local_note_tools=False)
    allowed_tools = build_allowed_tools(tools)
    all_sources: list[dict] = []
    latest_metadata = None
    note_edit = None
    last_answer = ""
    last_raw_answer = ""
    next_prompt: str | None = prompt
    next_messages: list[dict] | None = None
    sent_local_tool_results = False

    for _ in range(MAX_LOCAL_TOOL_ROUNDS):
        report_progress(progress, "agentcore", "Sending the request to AgentCore Harness.")
        result = (
            invoke_model(session_id, next_prompt or "", tools=tools, allowed_tools=allowed_tools)
            if next_messages is None
            else invoke_model(session_id, messages=next_messages, tools=tools, allowed_tools=allowed_tools)
        )
        latest_metadata = result.get("metadata")
        raw_answer = normalize_text(result.get("rawAnswer") or result.get("answer"))
        last_raw_answer = raw_answer
        last_answer = normalize_text(result.get("answer")) or raw_answer
        all_sources.extend(result.get("sources") if isinstance(result.get("sources"), list) else [])

        tool_calls = normalize_native_tool_uses(result.get("toolUses"))
        if not tool_calls:
            if local_gate_active and not sent_local_tool_results:
                report_progress(progress, "routing", "Agent did not request a local note tool; forcing a local note read.")
                tool_calls = [forced_read_current_note_tool_call()]
            else:
                report_progress(progress, "answer", "AgentCore returned the final answer.")
                return {
                    "answer": last_answer or "No answer returned.",
                    "rawAnswer": raw_answer,
                    "sources": dedupe_sources(all_sources),
                    "metadata": latest_metadata,
                    "noteEdit": note_edit,
                }

        tool_names = ", ".join(tool_call["name"] for tool_call in tool_calls)
        report_progress(progress, "tool-use", f"Agent requested local tool access: {tool_names}.")
        tool_results = []
        for tool_call in tool_calls[:4]:
            report_progress(progress, "local-tool", f"Running local tool: {tool_call['name']}.")
            tool_result = execute_local_tool(tool_call, note_id=note_id)
            tool_results.append(tool_result)
            if tool_result.get("ok") and isinstance(tool_result.get("noteEdit"), dict):
                note_edit = tool_result["noteEdit"]

        report_progress(progress, "tool-result", "Sending local tool results back to AgentCore.")
        next_prompt = None
        next_messages = build_tool_result_messages(tool_calls, tool_results)
        sent_local_tool_results = True

    if note_edit:
        last_answer = f"I prepared a local note edit draft: {note_edit['summary']}\n\nReview it below. It will not change your note until you click Apply to note."

    return {
        "answer": last_answer or "The agent did not finish after using local tools.",
        "rawAnswer": last_raw_answer,
        "sources": dedupe_sources(all_sources),
        "metadata": latest_metadata,
        "noteEdit": note_edit,
    }


def report_progress(progress: Callable[[str, str], None] | None, stage: str, detail: str) -> None:
    if progress:
        progress(stage, detail)


def forced_read_current_note_tool_call() -> dict:
    return {
        "id": f"forced-read-current-note-{uuid.uuid4()}",
        "name": "read_current_note_html",
        "arguments": {},
    }


def should_use_local_note_gate(user_message: object) -> bool:
    text = normalize_text(user_message).lower()
    if not text:
        return False
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in LOCAL_NOTE_INTENT_PATTERNS)


def build_initial_prompt(*, user_message: str, note_id: str, context_lines: list[str]) -> str:
    context = "\n".join(line for line in context_lines if line)
    context_block = f"{context}\n" if context else ""
    if normalize_text(note_id) and note_id != "workspace":
        return f"""You are Paper Notes Agent, deciding whether this Reader request needs local note tools.

This is a routing/tool-use turn. Do not answer the user directly in this turn.

Available actions:
- If the user is asking to read, summarize, inspect, translate, reorganize, add to, append to, update, delete from, or otherwise modify the selected local note in any language, call read_current_note_html.

Important:
- The user's wording may be Chinese, English, or any other language. Interpret intent semantically.
- If the request says to put/write/add/append something "to the note", "in the note", "at the end of the note", or equivalent in any language, it requires local note tools.
- For current time/date, use this local server time instead of web search: {current_local_time_label()}.
- Never answer with the time or content directly when the user asked to add it to the note.

{context_block}User request: {user_message}"""

    return build_general_prompt(user_message=user_message, context_lines=context_lines)


def build_general_prompt(*, user_message: str, context_lines: list[str]) -> str:
    context = "\n".join(line for line in context_lines if line)
    context_block = f"{context}\n" if context else ""
    return f"""You are Paper Notes Agent.

You can answer normally.

Rules:
- For paper questions, summaries, comparisons, citations, web search, or Knowledge Base retrieval, use any existing cloud/RAG tools available to you.
- Never claim the local file was changed. A draft is applied only after the user clicks Apply.

{context_block}User request: {user_message}"""


def build_agentcore_tools(note_id: str, *, include_local_note_tools: bool = False) -> list[dict]:
    tools: list[dict] = []
    gateway_tool = agentcore_gateway_tool()
    if gateway_tool:
        tools.append(gateway_tool)
    if include_local_note_tools and normalize_text(note_id) and note_id != "workspace":
        tools.extend(local_note_inline_tools())
    return tools


def build_local_gate_tools() -> list[dict]:
    return local_note_inline_tools()


def build_allowed_tools(tools: list[dict]) -> list[str]:
    allowed = []
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        name = normalize_tool_name(tool.get("name"))
        if not name:
            continue
        if tool.get("type") == "agentcore_gateway":
            allowed.append(f"@{name}")
        else:
            allowed.append(name)
    return allowed


def local_note_inline_tools() -> list[dict]:
    return [
        {
            "type": "inline_function",
            "name": "read_current_note_html",
            "config": {
                "inlineFunction": {
                    "description": "Read the selected Paper Notes local HTML note body. Use this before preparing local note edits.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {},
                    },
                }
            },
        },
        {
            "type": "inline_function",
            "name": "create_note_edit_draft",
            "config": {
                "inlineFunction": {
                    "description": "Create a local HTML note edit draft for the user to review. This does not write the file.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "summary": {
                                "type": "string",
                                "description": "One short sentence describing the proposed note change.",
                            },
                            "replacementHtml": {
                                "type": "string",
                                "description": "Full replacement inner HTML for the selected note's <section class='note-body'>.",
                            },
                        },
                        "required": ["summary", "replacementHtml"],
                    },
                }
            },
        },
    ]


def current_local_time_label() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def agentcore_gateway_tool() -> dict | None:
    gateway_arn = configured_value(config.AGENTCORE_GATEWAY_ARN) or derived_gateway_arn()
    if not gateway_arn:
        return None
    return {
        "type": "agentcore_gateway",
        "name": normalize_tool_name(config.GATEWAY_TARGET_NAME) or "paper-notes-gateway",
        "config": {"agentCoreGateway": {"gatewayArn": gateway_arn}},
    }


def derived_gateway_arn() -> str:
    gateway_id = configured_value(config.AGENTCORE_GATEWAY_ID)
    harness_arn = configured_value(config.HARNESS_ARN)
    if not gateway_id or not harness_arn:
        return ""
    if gateway_id.startswith("arn:"):
        return gateway_id
    match = re.match(r"^arn:([^:]+):bedrock-agentcore:([^:]+):([^:]+):harness/.+$", harness_arn)
    if not match:
        return ""
    partition, region, account_id = match.groups()
    return f"arn:{partition}:bedrock-agentcore:{region}:{account_id}:gateway/{gateway_id}"


def configured_value(value: object) -> str:
    text = normalize_text(value)
    if not text or text.startswith("your-") or "REGION" in text or "ACCOUNT_ID" in text:
        return ""
    return text


def normalize_tool_name(value: object) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]+", "-", normalize_text(value)).strip("-")


def build_tool_result_messages(tool_calls: list[dict], tool_results: list[dict]) -> list[dict]:
    tool_use_content = []
    for tool_call in tool_calls:
        tool_use_content.append(
            {
                "toolUse": {
                    "toolUseId": normalize_text(tool_call.get("id")),
                    "name": normalize_text(tool_call.get("name")),
                    "input": tool_call.get("arguments") if isinstance(tool_call.get("arguments"), dict) else {},
                }
            }
        )

    tool_result_content = []
    for tool_result in tool_results:
        tool_result_content.append(
            {
                "toolResult": {
                    "toolUseId": normalize_text(tool_result.get("toolCallId")),
                    "content": [{"text": json.dumps(tool_result, ensure_ascii=False)}],
                    "status": "success" if tool_result.get("ok") else "error",
                }
            }
        )
    messages = []
    if tool_use_content:
        messages.append({"role": "assistant", "content": tool_use_content})
    messages.append({"role": "user", "content": tool_result_content})
    return messages


def normalize_native_tool_uses(raw_tool_uses: object) -> list[dict]:
    if not isinstance(raw_tool_uses, list):
        return []
    tool_calls = []
    for index, raw_tool_use in enumerate(raw_tool_uses):
        if not isinstance(raw_tool_use, dict):
            continue
        name = normalize_text(raw_tool_use.get("name") or raw_tool_use.get("toolName") or raw_tool_use.get("tool"))
        if name not in LOCAL_TOOL_NAMES:
            continue
        arguments = raw_tool_use.get("input") or raw_tool_use.get("arguments") or {}
        if not isinstance(arguments, dict):
            arguments = {}
        tool_calls.append(
            {
                "id": normalize_text(raw_tool_use.get("toolUseId") or raw_tool_use.get("id")) or f"local-tool-{index + 1}",
                "name": name,
                "arguments": arguments,
            }
        )
    return tool_calls


def execute_local_tool(tool_call: dict, *, note_id: str) -> dict:
    name = normalize_text(tool_call.get("name"))
    try:
        if name == "read_current_note_html":
            payload = read_current_note_html(note_id)
        elif name == "create_note_edit_draft":
            payload = create_note_edit_draft(note_id, tool_call.get("arguments"))
        else:
            raise ValueError(f"Unknown local tool: {name}")
        return {
            "toolCallId": tool_call.get("id"),
            "name": name,
            "ok": True,
            **payload,
        }
    except Exception as error:
        return {
            "toolCallId": tool_call.get("id"),
            "name": name,
            "ok": False,
            "error": str(error),
        }


def read_current_note_html(note_id: str) -> dict:
    note, html_path = current_note_and_html_path(note_id)
    body_html = extract_note_body_html(html_path.read_text(encoding="utf-8"))
    if len(body_html) > MAX_NOTE_BODY_CHARS:
        raise ValueError("This note is too large for a single local tool read. Ask the user to narrow the edit to a section.")
    return {
        "note": {
            "id": normalize_text(note.get("id")),
            "title": normalize_text(note.get("title")),
            "date": normalize_text(note.get("date")),
            "htmlHref": normalize_text(note.get("htmlHref")),
        },
        "bodyHtml": body_html,
    }


def create_note_edit_draft(note_id: str, arguments: object) -> dict:
    note, _ = current_note_and_html_path(note_id)
    args = arguments if isinstance(arguments, dict) else {}
    replacement_html = normalize_replacement_html(
        args.get("replacementHtml") or args.get("noteBodyHtml") or args.get("html")
    )
    return {
        "noteEdit": {
            "id": f"note-edit-{uuid.uuid4()}",
            "noteId": normalize_text(note.get("id")),
            "summary": normalize_text(args.get("summary")) or "Prepared a note edit draft.",
            "replacementHtml": replacement_html,
        }
    }


def current_note_and_html_path(note_id: str):
    safe_note_id = normalize_text(note_id)
    if not safe_note_id or safe_note_id == "workspace":
        raise ValueError("No selected paper note is available for local note tools.")

    library = read_library()
    note = next((entry for entry in library.get("notes", []) if entry.get("id") == safe_note_id), None)
    if not note:
        raise ValueError("Selected note was not found.")

    html_path = project_path_from_href(normalize_text(note.get("htmlHref")))
    if not is_within(html_path, config.HTML_DIR) or not html_path.is_file():
        raise ValueError("Selected note HTML file was not found.")
    return note, html_path


def dedupe_sources(sources: list[dict]) -> list[dict]:
    deduped: list[dict] = []
    seen: set[tuple] = set()
    for source in sources:
        if not isinstance(source, dict):
            continue
        key = (source.get("uri"), source.get("page"), source.get("type"), source.get("label"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(source)
    return deduped[:12]
