from __future__ import annotations

import asyncio
import concurrent.futures
import inspect
import json
import logging
import threading
import time
from typing import Any

from tools.schema_sanitizer import sanitize_tool_schemas
from tools.types import ToolDefinition, ToolDispatchResult, ToolGroupDefinition, ToolHandler


logger = logging.getLogger(__name__)
_DEFAULT_AVAILABILITY_TTL_SECONDS = 30.0
_tool_loop: asyncio.AbstractEventLoop | None = None
_tool_loop_lock = threading.Lock()
_worker_thread_local = threading.local()


def _get_tool_loop() -> asyncio.AbstractEventLoop:
    global _tool_loop
    with _tool_loop_lock:
        if _tool_loop is None or _tool_loop.is_closed():
            _tool_loop = asyncio.new_event_loop()
        return _tool_loop


def _get_worker_loop() -> asyncio.AbstractEventLoop:
    loop = getattr(_worker_thread_local, "loop", None)
    if loop is None or loop.is_closed():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        _worker_thread_local.loop = loop
    return loop


def _run_async(awaitable: Any) -> Any:
    """Run an async tool result from the synchronous agent runtime."""
    try:
        running_loop = asyncio.get_running_loop()
    except RuntimeError:
        running_loop = None

    if running_loop and running_loop.is_running():
        def _run_in_worker() -> Any:
            loop = asyncio.new_event_loop()
            try:
                asyncio.set_event_loop(loop)
                return loop.run_until_complete(awaitable)
            finally:
                loop.close()

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(_run_in_worker).result()

    if threading.current_thread() is not threading.main_thread():
        return _get_worker_loop().run_until_complete(awaitable)
    return _get_tool_loop().run_until_complete(awaitable)


class ToolRegistry:
    """Small local tool registry inspired by Hermes' tools.registry.ToolRegistry."""

    def __init__(self, *, availability_ttl_seconds: float = _DEFAULT_AVAILABILITY_TTL_SECONDS) -> None:
        self._tools: dict[str, ToolDefinition] = {}
        self._groups: dict[str, ToolGroupDefinition] = {}
        self._toolset_aliases: dict[str, tuple[str, ...]] = {}
        self._availability_cache: dict[str, tuple[float, bool, dict[str, Any]]] = {}
        self._availability_ttl_seconds = max(0.0, float(availability_ttl_seconds))
        self._availability_generation = 0
        self._generation = 0
        self._lock = threading.RLock()

    @property
    def generation(self) -> int:
        with self._lock:
            return self._generation

    @property
    def availability_generation(self) -> int:
        with self._lock:
            return self._availability_generation

    @property
    def availability_ttl_seconds(self) -> float:
        return self._availability_ttl_seconds

    def register(self, definition: ToolDefinition) -> None:
        with self._lock:
            if definition.name in self._tools:
                raise ValueError(f"Tool already registered: {definition.name}")
            self._tools[definition.name] = definition
            self._generation += 1

    def register_group(self, group: ToolGroupDefinition) -> None:
        with self._lock:
            self._groups[group.name] = group
            self._toolset_aliases[group.name] = tuple(group.tools)
            self._generation += 1

    def register_toolset_alias(self, name: str, tools: list[str] | tuple[str, ...]) -> None:
        normalized = str(name or "").strip()
        if not normalized:
            raise ValueError("Toolset alias name is required.")
        with self._lock:
            self._toolset_aliases[normalized] = tuple(str(tool or "").strip() for tool in tools if str(tool or "").strip())
            self._generation += 1

    def deregister(self, name: str) -> None:
        normalized = str(name or "").strip()
        if not normalized:
            return
        with self._lock:
            definition = self._tools.pop(normalized, None)
            if definition is None:
                return
            self._availability_cache.pop(normalized, None)
            if not any(tool.toolset == definition.toolset for tool in self._tools.values()):
                self._toolset_aliases = {
                    alias: names
                    for alias, names in self._toolset_aliases.items()
                    if alias != definition.toolset
                }
            self._generation += 1

    def get(self, name: str) -> ToolDefinition | None:
        with self._lock:
            return self._tools.get(name)

    def get_group(self, name: str) -> ToolGroupDefinition | None:
        with self._lock:
            return self._groups.get(name)

    def names(self) -> list[str]:
        with self._lock:
            return sorted(self._tools)

    def snapshot_tools(self) -> list[ToolDefinition]:
        with self._lock:
            return [self._tools[name] for name in sorted(self._tools)]

    def tool_names_for_toolset(self, toolset: str) -> list[str]:
        with self._lock:
            alias = self._toolset_aliases.get(toolset)
            if alias is not None:
                return sorted(name for name in alias if name in self._tools)
            return sorted(
                definition.name
                for definition in self._tools.values()
                if definition.toolset == toolset
            )

    def toolsets(self) -> list[str]:
        with self._lock:
            return sorted({definition.toolset for definition in self._tools.values()} | set(self._toolset_aliases))

    def groups(self) -> list[ToolGroupDefinition]:
        with self._lock:
            return [self._groups[name] for name in sorted(self._groups)]

    def invalidate_availability_cache(self, tool_name: str | None = None) -> None:
        with self._lock:
            if tool_name is None:
                self._availability_cache.clear()
                self._availability_generation += 1
                return
            if self._availability_cache.pop(tool_name, None) is not None:
                self._availability_generation += 1

    def schemas(
        self,
        *,
        toolset: str | None = None,
        tool_names: set[str] | list[str] | tuple[str, ...] | None = None,
    ) -> list[dict[str, Any]]:
        with self._lock:
            definitions: list[ToolDefinition] = list(self._tools.values())
            if toolset is not None:
                aliases = set(self._toolset_aliases.get(toolset, ()))
                definitions = [
                    definition
                    for definition in definitions
                    if definition.toolset == toolset or definition.name in aliases
                ]
            if tool_names is not None:
                selected = {str(name) for name in tool_names}
                definitions = [definition for definition in definitions if definition.name in selected]
            names = {definition.name for definition in definitions}
        return self.get_definitions(names, quiet=True)

    def get_definitions(self, tool_names: set[str] | list[str] | tuple[str, ...], *, quiet: bool = True) -> list[dict[str, Any]]:
        names = sorted({str(name or "").strip() for name in tool_names if str(name or "").strip()})
        schemas: list[dict[str, Any]] = []
        for name in names:
            definition = self.get(name)
            if definition is None:
                continue
            if not self.is_available(name):
                if not quiet:
                    logger.debug("Tool %s unavailable.", name)
                continue
            schemas.append(self._schema_for_definition(definition))
        return sanitize_tool_schemas(schemas)

    def dispatch(self, name: str, arguments: dict[str, Any] | None = None) -> ToolDispatchResult:
        definition = self.get(name)
        if definition is None:
            return ToolDispatchResult(name=name, content=_json_error(f"Unknown tool: {name}"), is_error=True)
        if not self.is_available(name):
            _, details = self.availability(name)
            return ToolDispatchResult(
                name=name,
                content=json.dumps({
                    "success": False,
                    "error": "Tool is not available in this environment.",
                    "code": "tool_unavailable",
                    "availability": details,
                }, ensure_ascii=False),
                is_error=True,
            )

        try:
            result = definition.handler(arguments or {})
            if inspect.isawaitable(result):
                result = _run_async(result)
        except Exception as error:
            logger.exception("Tool dispatch failed for %s: %s", name, error)
            return ToolDispatchResult(
                name=name,
                content=_json_error(f"Tool execution failed: {type(error).__name__}: {error}"),
                is_error=True,
            )
        content = _stringify_tool_result(result)
        original_content = content
        if definition.result_max_chars and len(content) > definition.result_max_chars:
            content = _trim_tool_result_content(content, max_chars=definition.result_max_chars)
        return ToolDispatchResult(
            name=name,
            content=content,
            is_error=_is_error_result(result),
            original_content=original_content,
        )

    def check_toolset_requirements(self) -> dict[str, bool]:
        requirements: dict[str, bool] = {}
        for toolset in self.toolsets():
            names = self.tool_names_for_toolset(toolset)
            if not names:
                requirements[toolset] = False
                continue
            requirements[toolset] = all(self.is_available(name) for name in names)
        return requirements

    def get_available_toolsets(self) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        with self._lock:
            group_names = set(self._groups)
        for toolset in self.toolsets():
            names = self.tool_names_for_toolset(toolset)
            available_names: list[str] = []
            unavailable_names: list[str] = []
            for name in names:
                if self.is_available(name):
                    available_names.append(name)
                else:
                    unavailable_names.append(name)
            group = self.get_group(toolset)
            result[toolset] = {
                "available": bool(available_names) and not unavailable_names,
                "tools": names,
                "available_tools": available_names,
                "unavailable_tools": unavailable_names,
                "description": group.description if group is not None else "",
                "display_name": group.display_name if group is not None else toolset,
                "group": toolset in group_names,
            }
        return result

    def is_available(self, name: str) -> bool:
        available, _ = self.availability(name)
        return available

    def availability(self, name: str) -> tuple[bool, dict[str, Any]]:
        definition = self.get(name)
        if definition is None:
            return False, {"reason": "unknown_tool"}
        now = time.time()
        with self._lock:
            cached = self._availability_cache.get(name)
            if cached is not None and (self._availability_ttl_seconds == 0 or now - cached[0] <= self._availability_ttl_seconds):
                return cached[1], dict(cached[2])

        available = True
        details = dict(definition.availability)
        if definition.availability_check is not None:
            try:
                checked = definition.availability_check()
            except Exception as error:
                logger.debug("Tool availability check failed for %s: %s", name, error, exc_info=True)
                available = False
                details = {**details, "error": f"{type(error).__name__}: {error}"}
            else:
                if isinstance(checked, dict):
                    available = bool(checked.get("available", True))
                    details = {**details, **checked}
                else:
                    available = bool(checked)
        with self._lock:
            self._availability_cache[name] = (now, available, dict(details))
        return available, details

    def _schema_for_definition(self, definition: ToolDefinition) -> dict[str, Any]:
        try:
            return definition.openai_schema()
        except Exception as error:
            logger.warning(
                "Dynamic schema for tool %s failed; using static schema: %s",
                definition.name,
                error,
            )
            return {
                "type": "function",
                "function": {
                    "name": definition.name,
                    "description": definition.description,
                    "parameters": definition.parameters,
                },
            }


def _stringify_tool_result(result: Any) -> str:
    if isinstance(result, str):
        return result
    return json.dumps(result, ensure_ascii=False, indent=2)


def _json_error(message: str) -> str:
    return json.dumps({"error": message}, ensure_ascii=False)


def _is_error_result(result: Any) -> bool:
    return isinstance(result, dict) and (result.get("success") is False or bool(result.get("error")))


def _trim_tool_result_content(content: str, *, max_chars: int) -> str:
    limit = max(200, int(max_chars))
    preview = content[:limit].rstrip()
    return json.dumps({
        "success": True,
        "truncated": True,
        "original_chars": len(content),
        "preview": f"{preview}...[truncated]",
    }, ensure_ascii=False, indent=2)


__all__ = [
    "ToolDefinition",
    "ToolDispatchResult",
    "ToolGroupDefinition",
    "ToolHandler",
    "ToolRegistry",
]
