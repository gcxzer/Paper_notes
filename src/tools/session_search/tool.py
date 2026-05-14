"""Session transcript recall inspired by Hermes' `tools/session_search_tool.py`.

Hermes uses SQLite FTS plus optional LLM summaries. Paper Notes currently stores
sessions as JSONL, so this version searches those transcripts directly and can
accept a provider-backed recap hook while keeping a local preview fallback.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from agent_sessions import AgentSession, AgentSessionMetadata, AgentSessionStore
from tools.registry import ToolDefinition, ToolRegistry
from tools.session_search.manifest import TOOL_GROUP


SESSION_SEARCH_TOOLSET = "session_search"
_BOOLEAN_TOKENS = {"OR", "AND", "NOT"}
SessionSearchRecapProvider = Callable[[str, list[dict[str, Any]]], str]


def register_session_search_tool(
    registry: ToolRegistry,
    *,
    session_store: AgentSessionStore,
    current_session_id_provider: Callable[[], str] | None = None,
    recap_provider: SessionSearchRecapProvider | None = None,
) -> None:
    registry.register_group(TOOL_GROUP)
    if registry.get("session_search") is not None:
        return
    registry.register(ToolDefinition(
        name="session_search",
        description=(
            "Search or browse past chat sessions. Use this for task history, prior decisions, "
            "previous fixes, and temporary progress that should not be stored in persistent memory. "
            "Call with no query to browse recent sessions; call with query to search transcript text."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Optional search query. Omit or leave empty to list recent sessions.",
                },
                "role_filter": {
                    "type": "string",
                    "description": "Optional comma-separated roles to search, such as 'user,assistant'.",
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 5,
                    "description": "Maximum sessions to return.",
                },
                "include_recap": {
                    "type": "boolean",
                    "description": "When true, include a focused local recap synthesized from the returned excerpts.",
                    "default": True,
                },
            },
            "required": [],
            "additionalProperties": False,
        },
        handler=lambda args: session_search(
            args,
            session_store=session_store,
            current_session_id=current_session_id_provider() if current_session_id_provider else "",
            recap_provider=recap_provider,
        ),
        toolset=SESSION_SEARCH_TOOLSET,
        read_only=True,
        risk="read",
        kind="search",
        result_max_chars=12_000,
        metadata={"durability": "cross_session", "mode": "local_match_with_focused_recap"},
    ))


def session_search(
    args: dict[str, Any],
    *,
    session_store: AgentSessionStore,
    current_session_id: str = "",
    recap_provider: SessionSearchRecapProvider | None = None,
) -> dict[str, Any]:
    query = str(args.get("query") or "").strip()
    role_filter = _role_filter(args.get("role_filter"))
    limit = _safe_limit(args.get("limit"), default=3, maximum=5)
    include_recap = bool(args.get("include_recap", True))

    if not query:
        return _recent_sessions(session_store, current_session_id=current_session_id, limit=limit)

    sessions = [
        session_store.require_session(metadata.session_id)
        for metadata in session_store.list_sessions()
        if metadata.session_id != current_session_id
    ]
    ranked = _rank_sessions(sessions, query=query, role_filter=role_filter)
    results = [_session_search_result(session, matches, query=query) for session, matches in ranked[:limit]]
    return {
        "success": True,
        "mode": "search",
        "query": query,
        "count": len(results),
        "recap": _recap(results, query=query, recap_provider=recap_provider) if include_recap else "",
        "results": results,
    }


def _recap(
    results: list[dict[str, Any]],
    *,
    query: str,
    recap_provider: SessionSearchRecapProvider | None,
) -> str:
    if recap_provider is not None:
        try:
            recap = _normalize_recap_text(recap_provider(query, results))
        except Exception:
            recap = ""
        if recap:
            return recap
    return _focused_recap(results, query=query)


def _normalize_recap_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _recent_sessions(
    session_store: AgentSessionStore,
    *,
    current_session_id: str,
    limit: int,
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for metadata in session_store.list_sessions():
        if metadata.session_id == current_session_id:
            continue
        session = session_store.require_session(metadata.session_id)
        results.append({
            "session_id": metadata.session_id,
            "title": metadata.title,
            "updated_at": metadata.updated_at,
            "note_id": metadata.note_id,
            "message_count": metadata.message_count,
            "preview": _session_preview(session),
        })
        if len(results) >= limit:
            break
    return {
        "success": True,
        "mode": "recent",
        "count": len(results),
        "results": results,
    }


def _rank_sessions(
    sessions: list[AgentSession],
    *,
    query: str,
    role_filter: set[str] | None,
) -> list[tuple[AgentSession, list[dict[str, Any]]]]:
    ranked: list[tuple[int, str, AgentSession, list[dict[str, Any]]]] = []
    terms = _query_terms(query)
    phrase = query.casefold()
    for session in sessions:
        matches: list[dict[str, Any]] = []
        score = 0
        for message in session.messages:
            role = str(message.get("role") or "")
            if role_filter and role not in role_filter:
                continue
            text = _message_text(message)
            if not text:
                continue
            message_score = _message_score(text, phrase=phrase, terms=terms)
            if message_score <= 0:
                continue
            score += message_score
            matches.append({
                "role": role,
                "created_at": message.get("created_at", ""),
                "excerpt": _excerpt(text, query=query, terms=terms),
            })
        if score > 0:
            ranked.append((score, session.metadata.updated_at, session, matches[:5]))

    ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [(session, matches) for _, _, session, matches in ranked]


def _session_search_result(
    session: AgentSession,
    matches: list[dict[str, Any]],
    *,
    query: str,
) -> dict[str, Any]:
    metadata = session.metadata
    return {
        "session_id": metadata.session_id,
        "title": metadata.title,
        "updated_at": metadata.updated_at,
        "note_id": metadata.note_id,
        "message_count": metadata.message_count,
        "query": query,
        "summary": _summary_from_matches(metadata, matches),
        "matches": matches,
    }


def _summary_from_matches(metadata: AgentSessionMetadata, matches: list[dict[str, Any]]) -> str:
    if not matches:
        return f"Matched session {metadata.title}."
    lead = matches[0]["excerpt"]
    return f"{metadata.title}: {lead}"


def _focused_recap(results: list[dict[str, Any]], *, query: str) -> str:
    if not results:
        return f"No past sessions matched {query!r}."
    lines = [f"Focused recap for {query!r}:"]
    for result in results[:3]:
        title = result.get("title") or result.get("session_id") or "Untitled session"
        summary = result.get("summary") or ""
        lines.append(f"- {title}: {summary}")
    return "\n".join(lines)


def _message_score(text: str, *, phrase: str, terms: list[str]) -> int:
    lowered = text.casefold()
    score = 0
    if phrase and phrase in lowered:
        score += 10
    for term in terms:
        if term and term in lowered:
            score += 2
    return score


def _excerpt(text: str, *, query: str, terms: list[str], radius: int = 180) -> str:
    lowered = text.casefold()
    anchors = [query.casefold(), *terms]
    positions = [lowered.find(anchor) for anchor in anchors if anchor and lowered.find(anchor) >= 0]
    position = min(positions) if positions else 0
    start = max(0, position - radius)
    end = min(len(text), position + radius)
    prefix = "... " if start > 0 else ""
    suffix = " ..." if end < len(text) else ""
    return prefix + text[start:end].strip() + suffix


def _session_preview(session: AgentSession) -> str:
    for message in session.messages:
        if message.get("role") == "user":
            return _message_text(message)[:300]
    return _message_text(session.messages[-1])[:300] if session.messages else ""


def _message_text(message: dict[str, Any]) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                parts.append(str(item.get("text") or item.get("content") or ""))
            else:
                parts.append(str(item))
        return "\n".join(part for part in parts if part)
    return "" if content is None else str(content)


def _query_terms(query: str) -> list[str]:
    terms = []
    for quoted, bare in re.findall(r'"([^"]+)"|(\S+)', query):
        token = quoted or bare
        if token.upper() in _BOOLEAN_TOKENS:
            continue
        if token.startswith("-"):
            continue
        terms.append(token.casefold().rstrip("*"))
    return terms


def _role_filter(value: Any) -> set[str] | None:
    if not value:
        return None
    roles = {part.strip() for part in str(value).split(",") if part.strip()}
    return roles or None


def _safe_limit(value: Any, *, default: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return min(max(parsed, 1), maximum)
