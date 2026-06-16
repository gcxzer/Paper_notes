from __future__ import annotations

import asyncio
import threading
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage
from langgraph.types import Command


DEFAULT_SERIALIZED_RAG_TOOLS = ("query_paper_content",)


@dataclass(slots=True)
class RagToolSerializationMiddleware(AgentMiddleware):
    tool_names: Sequence[str] = DEFAULT_SERIALIZED_RAG_TOOLS
    _sync_locks: dict[str, threading.Lock] = field(default_factory=dict, init=False, repr=False)
    _async_locks: dict[str, asyncio.Lock] = field(default_factory=dict, init=False, repr=False)
    _registry_lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    def __post_init__(self) -> None:
        self.tool_names = tuple(_text(name) for name in self.tool_names if _text(name))

    def wrap_tool_call(
        self,
        request: Any,
        handler: Callable[[Any], ToolMessage | Command[Any]],
    ) -> ToolMessage | Command[Any]:
        lock_key = self._lock_key(request)
        if not lock_key:
            return handler(request)
        with self._sync_lock_for(lock_key):
            return handler(request)

    async def awrap_tool_call(
        self,
        request: Any,
        handler: Callable[[Any], Awaitable[ToolMessage | Command[Any]]],
    ) -> ToolMessage | Command[Any]:
        lock_key = self._lock_key(request)
        if not lock_key:
            return await handler(request)
        async with self._async_lock_for(lock_key):
            return await handler(request)

    def _lock_key(self, request: Any) -> str:
        tool_name = _tool_name(request)
        if tool_name not in set(self.tool_names):
            return ""
        note_id = _note_id(request)
        return f"note:{note_id}" if note_id else f"tool:{tool_name}"

    def _sync_lock_for(self, key: str) -> threading.Lock:
        with self._registry_lock:
            lock = self._sync_locks.get(key)
            if lock is None:
                lock = threading.Lock()
                self._sync_locks[key] = lock
            return lock

    def _async_lock_for(self, key: str) -> asyncio.Lock:
        with self._registry_lock:
            lock = self._async_locks.get(key)
            if lock is None:
                lock = asyncio.Lock()
                self._async_locks[key] = lock
            return lock


def create_rag_tool_serialization_middleware(
    *,
    tool_names: Sequence[str] | None = None,
) -> RagToolSerializationMiddleware:
    return RagToolSerializationMiddleware(tool_names=tuple(tool_names or DEFAULT_SERIALIZED_RAG_TOOLS))


def _tool_name(request: Any) -> str:
    tool = getattr(request, "tool", None)
    name = _text(getattr(tool, "name", ""))
    if name:
        return name
    tool_call = getattr(request, "tool_call", None)
    if isinstance(tool_call, dict):
        return _text(tool_call.get("name"))
    return ""


def _note_id(request: Any) -> str:
    args = _tool_args(request)
    if not isinstance(args, dict):
        return ""
    return _text(args.get("note_id") or args.get("noteId"))


def _tool_args(request: Any) -> Any:
    tool_call = getattr(request, "tool_call", None)
    if isinstance(tool_call, dict):
        return tool_call.get("args")
    return None


def _text(value: Any) -> str:
    return str(value or "").strip()


__all__ = [
    "DEFAULT_SERIALIZED_RAG_TOOLS",
    "RagToolSerializationMiddleware",
    "create_rag_tool_serialization_middleware",
]
