from __future__ import annotations

import asyncio
import base64
import concurrent.futures
import inspect
import json
import logging
import os
import re
import shutil
import sys
import threading
import time
from contextlib import asynccontextmanager, contextmanager
from copy import deepcopy
from fnmatch import fnmatchcase
from typing import Any
from urllib.parse import urlsplit

from app_config.secrets import LOCAL_STATE_DIR
from tools.mcp.manifest import TOOLSET
from tools.mcp.security import (
    collect_security_warnings as _collect_security_warnings,
    extend_security_warnings as _extend_security_warnings,
    mcp_security_warnings as _mcp_security_warnings,
    sanitize_mcp_description as _sanitize_mcp_description,
    sanitize_mcp_error,
    sanitize_mcp_schema_descriptions as _sanitize_mcp_schema_descriptions,
)
from tools.mcp.settings import mcp_runtime_config, normalize_mcp_server_config, read_mcp_settings
from tools.registry import ToolRegistry
from tools.types import ToolDefinition


logger = logging.getLogger(__name__)

_DEFAULT_PROTOCOL_VERSION = "2025-03-26"
_KEEPALIVE_INTERVAL_SECONDS = 180
_KEEPALIVE_TIMEOUT_SECONDS = 30
_MAX_INITIAL_CONNECT_RETRIES = 3
_MAX_RECONNECT_RETRIES = 5
_MAX_BACKOFF_SECONDS = 16
_CIRCUIT_OPEN_COOLDOWN_SECONDS = 60
_MAX_MCP_FILE_BYTES = 30 * 1024 * 1024
_MCP_FILE_PREVIEW_CHARS = 4000
_SAFE_MCP_FILE_MIME_TYPES = frozenset({
    "text/plain",
    "text/markdown",
    "application/json",
    "text/csv",
    "text/html",
})
_SAFE_MCP_PDF_MIME_TYPE = "application/pdf"
_SAFE_ENV_KEYS = frozenset({"PATH", "HOME", "USER", "LANG", "LC_ALL", "TERM", "SHELL", "TMPDIR"})
_CROSS_ORIGIN_STRIPPED_HEADER_NAMES = frozenset({
    "authorization",
    "proxy-authorization",
    "cookie",
    "x-api-key",
    "api-key",
    "openai-api-key",
    "anthropic-api-key",
    "x-auth-token",
    "x-access-token",
    "mcp-session-id",
})
_SESSION_EXPIRED_MARKERS = (
    "invalid or expired session",
    "expired session",
    "session expired",
    "session not found",
    "unknown session",
    "session terminated",
    "closedresourceerror",
    "closed resource",
    "transport is closed",
    "connection closed",
    "broken pipe",
    "end of file",
)

_mcp_loop: asyncio.AbstractEventLoop | None = None
_mcp_thread: threading.Thread | None = None
_mcp_loop_lock = threading.Lock()


def sanitize_mcp_name_component(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_]", "_", str(value or "").strip())
    return cleaned or "server"


def mcp_tool_name(server_name: str, tool_name: str) -> str:
    return f"mcp_{sanitize_mcp_name_component(server_name)}_{sanitize_mcp_name_component(tool_name)}"


def _default_http_port(scheme: str) -> int | None:
    scheme = str(scheme or "").lower()
    if scheme == "http":
        return 80
    if scheme == "https":
        return 443
    return None


def _http_origin(url: Any) -> tuple[str, str, int | None]:
    parsed = urlsplit(str(url or ""))
    return (
        parsed.scheme.lower(),
        (parsed.hostname or "").lower(),
        parsed.port or _default_http_port(parsed.scheme),
    )


def _configured_header_names(headers: dict[str, Any] | None) -> set[str]:
    if not isinstance(headers, dict):
        return set()
    return {
        normalized
        for name in headers
        if (normalized := str(name).strip().lower()) and normalized != "mcp-protocol-version"
    }


def _drop_request_header(headers: Any, name: str) -> None:
    try:
        del headers[name]
    except KeyError:
        pass


def _mcp_http_request_hook(initial_url: str, configured_headers: dict[str, Any]):
    initial_origin = _http_origin(initial_url)
    stripped_names = _configured_header_names(configured_headers) | set(_CROSS_ORIGIN_STRIPPED_HEADER_NAMES)

    async def _strip_cross_origin_headers(request: Any) -> None:
        if _http_origin(request.url) == initial_origin:
            return
        for name in stripped_names:
            _drop_request_header(request.headers, name)

    return _strip_cross_origin_headers


def _ensure_mcp_loop() -> asyncio.AbstractEventLoop:
    global _mcp_loop, _mcp_thread
    with _mcp_loop_lock:
        if _mcp_loop is not None and _mcp_loop.is_running() and not _mcp_loop.is_closed():
            return _mcp_loop
        loop = asyncio.new_event_loop()

        def _run() -> None:
            asyncio.set_event_loop(loop)
            loop.run_forever()

        thread = threading.Thread(target=_run, name="paper-notes-mcp", daemon=True)
        thread.start()
        _mcp_loop = loop
        _mcp_thread = thread
        return loop


def _run_on_mcp_loop(awaitable: Any, *, timeout: float | None = 30) -> Any:
    loop = _ensure_mcp_loop()
    future = asyncio.run_coroutine_threadsafe(awaitable, loop)
    try:
        return future.result(timeout=timeout)
    except concurrent.futures.TimeoutError:
        future.cancel()
        raise TimeoutError(f"MCP call timed out after {timeout}s") from None


class MCPServerTask:
    def __init__(self, server: dict[str, Any], *, refresh_callback: Any = None) -> None:
        self.server = server
        self.id = str(server.get("id") or "")
        self.name = str(server.get("name") or self.id)
        self.session: Any = None
        self.tools: list[Any] = []
        self.initialize_result: Any = None
        self.error: str = ""
        self.state: str = "idle"
        self.failure_count: int = 0
        self.next_retry_at: float = 0.0
        self.registered_tool_names: list[str] = []
        self._task: asyncio.Task | None = None
        self._ready = asyncio.Event()
        self._shutdown = asyncio.Event()
        self._reconnect = asyncio.Event()
        self._rpc_lock = asyncio.Lock()
        self._refresh_lock = asyncio.Lock()
        self._pending_refresh_tasks: set[asyncio.Task] = set()
        self._refresh_callback = refresh_callback
        self._stdio_processes: set[Any] = set()

    @property
    def circuit_open(self) -> bool:
        return self.state == "circuit_open" and self.next_retry_at > time.time()

    def status_details(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "failureCount": int(self.failure_count),
            "nextRetryAt": self.next_retry_at if self.next_retry_at > 0 else None,
            "circuitOpen": self.circuit_open,
        }

    async def start(self) -> None:
        self._task = asyncio.create_task(self.run())
        connect_timeout = float(self.server.get("connectTimeoutSeconds") or 10)
        try:
            await asyncio.wait_for(self._ready.wait(), timeout=connect_timeout)
        except asyncio.TimeoutError:
            self.error = f"MCP server '{self.name}' connection timed out after {connect_timeout:g}s"
            await self.shutdown()
            raise TimeoutError(self.error) from None
        if self.error:
            raise RuntimeError(self.error)

    async def run(self) -> None:
        config = mcp_runtime_config(self.server)
        initial_failures = 0
        reconnect_failures = 0
        backoff = 1.0

        while not self._shutdown.is_set():
            try:
                self.state = "connecting" if not self._ready.is_set() else "reconnecting"
                if self.server.get("transport") == "http":
                    reason = await self._run_http(config)
                else:
                    reason = await self._run_stdio(config)
                self.session = None
                if self._shutdown.is_set() or reason == "shutdown":
                    break
                reconnect_failures = 0
                backoff = 1.0
                continue
            except asyncio.CancelledError:
                self.session = None
                self.state = "cancelled"
                await self._cleanup_stdio_processes()
                raise
            except Exception as error:
                self.session = None
                self.error = sanitize_mcp_error(_format_exception(error))
                if not self._ready.is_set():
                    initial_failures += 1
                    self.failure_count = initial_failures
                    if initial_failures >= _MAX_INITIAL_CONNECT_RETRIES:
                        self.state = "error"
                        self.next_retry_at = 0.0
                        logger.warning(
                            "MCP server '%s' failed initial connection after %d attempts: %s",
                            self.name,
                            initial_failures,
                            self.error,
                        )
                        self._ready.set()
                        return
                    self.state = "connecting"
                    self.next_retry_at = time.time() + backoff
                    logger.warning(
                        "MCP server '%s' initial connection failed (attempt %d/%d), retrying in %.0fs: %s",
                        self.name,
                        initial_failures,
                        _MAX_INITIAL_CONNECT_RETRIES,
                        backoff,
                        self.error,
                    )
                else:
                    reconnect_failures += 1
                    self.failure_count = reconnect_failures
                    if reconnect_failures >= _MAX_RECONNECT_RETRIES:
                        self.state = "circuit_open"
                        self.next_retry_at = time.time() + _CIRCUIT_OPEN_COOLDOWN_SECONDS
                        logger.warning(
                            "MCP server '%s' opened circuit after %d reconnect attempts: %s",
                            self.name,
                            reconnect_failures,
                            self.error,
                        )
                        await self._wait_for_retry_delay(_CIRCUIT_OPEN_COOLDOWN_SECONDS)
                        if self._shutdown.is_set():
                            break
                        reconnect_failures = 0
                        backoff = 1.0
                        self.state = "reconnecting"
                        self.next_retry_at = 0.0
                        continue
                    self.state = "reconnecting"
                    self.next_retry_at = time.time() + backoff
                    logger.warning(
                        "MCP server '%s' reconnect failed (attempt %d/%d), retrying in %.0fs: %s",
                        self.name,
                        reconnect_failures,
                        _MAX_RECONNECT_RETRIES,
                        backoff,
                        self.error,
                    )
                await self._wait_for_retry_delay(backoff)
                backoff = min(backoff * 2, _MAX_BACKOFF_SECONDS)
        self.session = None
        if self.state not in {"cancelled", "error"}:
            self.state = "shutdown" if self._shutdown.is_set() else "disconnected"
        self.next_retry_at = 0.0
        await self._cleanup_stdio_processes()

    async def shutdown(self) -> None:
        self._shutdown.set()
        self._reconnect.set()
        if self._task and not self._task.done():
            try:
                await asyncio.wait_for(self._task, timeout=10)
            except asyncio.TimeoutError:
                self._task.cancel()
                try:
                    await self._task
                except asyncio.CancelledError:
                    pass
        if self._pending_refresh_tasks:
            for task in list(self._pending_refresh_tasks):
                task.cancel()
            await asyncio.gather(*self._pending_refresh_tasks, return_exceptions=True)
            self._pending_refresh_tasks.clear()
        self.session = None
        await self._cleanup_stdio_processes()

    async def call_tool(self, tool_name: str, arguments: dict[str, Any], *, timeout: float) -> Any:
        if self.session is None:
            raise RuntimeError(f"MCP server '{self.name}' is not connected")
        async with self._rpc_lock:
            return await asyncio.wait_for(
                self.session.call_tool(tool_name, arguments=arguments or {}),
                timeout=timeout,
            )

    async def list_resources(self) -> Any:
        if self.session is None:
            raise RuntimeError(f"MCP server '{self.name}' is not connected")
        async with self._rpc_lock:
            return await self.session.list_resources()

    async def read_resource(self, uri: str) -> Any:
        if self.session is None:
            raise RuntimeError(f"MCP server '{self.name}' is not connected")
        async with self._rpc_lock:
            return await self.session.read_resource(uri)

    async def list_prompts(self) -> Any:
        if self.session is None:
            raise RuntimeError(f"MCP server '{self.name}' is not connected")
        async with self._rpc_lock:
            return await self.session.list_prompts()

    async def get_prompt(self, name: str, arguments: dict[str, Any]) -> Any:
        if self.session is None:
            raise RuntimeError(f"MCP server '{self.name}' is not connected")
        async with self._rpc_lock:
            return await self.session.get_prompt(name, arguments=arguments or {})

    async def reconnect_and_wait(self, *, timeout: float = 15) -> bool:
        previous_session = self.session
        self._reconnect.set()
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            if self._shutdown.is_set():
                return False
            if self.session is not None and self.session is not previous_session:
                return True
            await asyncio.sleep(0.1)
        return self.session is not None and self.session is not previous_session

    async def _run_stdio(self, config: dict[str, Any]) -> str:
        from mcp import ClientSession, StdioServerParameters

        command = str(config.get("command") or "").strip()
        if not command:
            raise ValueError(f"MCP server '{self.name}' has no command")
        env = _resolve_stdio_env(config.get("env"))
        command, env = _resolve_stdio_command(command, env)
        params = StdioServerParameters(
            command=command,
            args=[str(arg) for arg in config.get("args") or []],
            env=env if env else None,
        )
        with _mcp_stderr_log(self.name) as errlog:
            async with _tracked_stdio_client(
                params,
                errlog=errlog,
                track_process=self._track_stdio_process,
                untrack_process=self._untrack_stdio_process,
            ) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream, **self._client_session_kwargs(ClientSession)) as session:
                    await self._initialize_session(session)
                    return await self._wait_for_lifecycle_event()

    async def _run_http(self, config: dict[str, Any]) -> str:
        import httpx
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client

        url = str(config.get("url") or "").strip()
        if not url:
            raise ValueError(f"MCP server '{self.name}' has no URL")
        configured_headers = dict(config.get("headers") or {})
        headers = dict(configured_headers)
        headers.setdefault("mcp-protocol-version", _latest_protocol_version())
        timeout = float(config.get("connect_timeout") or 10)
        async with httpx.AsyncClient(
            follow_redirects=True,
            headers=headers or None,
            timeout=httpx.Timeout(timeout, read=300.0),
            event_hooks={"request": [_mcp_http_request_hook(url, configured_headers)]},
        ) as http_client:
            async with streamable_http_client(url, http_client=http_client) as (read_stream, write_stream, _session_id):
                async with ClientSession(read_stream, write_stream, **self._client_session_kwargs(ClientSession)) as session:
                    await self._initialize_session(session)
                    return await self._wait_for_lifecycle_event()

    async def _initialize_session(self, session: Any) -> None:
        self.session = session
        self.initialize_result = await session.initialize()
        async with self._rpc_lock:
            tools_result = await session.list_tools()
        self.tools = list(tools_result.tools if hasattr(tools_result, "tools") else [])
        self.error = ""
        self.state = "connected"
        self.failure_count = 0
        self.next_retry_at = 0.0
        self._ready.set()
        if self.registered_tool_names and self._refresh_callback is not None:
            await self._refresh_callback(self)

    async def _wait_for_lifecycle_event(self) -> str:
        while True:
            if self._shutdown.is_set():
                return "shutdown"
            if self._reconnect.is_set():
                self._reconnect.clear()
                return "reconnect"
            try:
                await asyncio.wait_for(self._wait_for_shutdown_or_reconnect(), timeout=_KEEPALIVE_INTERVAL_SECONDS)
            except asyncio.TimeoutError:
                if self.session is None:
                    continue
                try:
                    async with self._rpc_lock:
                        await asyncio.wait_for(self.session.list_tools(), timeout=_KEEPALIVE_TIMEOUT_SECONDS)
                except Exception as error:
                    self.error = sanitize_mcp_error(_format_exception(error))
                    logger.warning("MCP server '%s' keepalive failed: %s", self.name, self.error)
                    self._reconnect.set()
                continue

    async def _wait_for_shutdown_or_reconnect(self) -> None:
        shutdown_task = asyncio.create_task(self._shutdown.wait())
        reconnect_task = asyncio.create_task(self._reconnect.wait())
        try:
            await asyncio.wait({shutdown_task, reconnect_task}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in (shutdown_task, reconnect_task):
                if not task.done():
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass

    async def _wait_for_retry_delay(self, delay_seconds: float) -> None:
        try:
            await asyncio.wait_for(self._wait_for_shutdown_or_reconnect(), timeout=max(0.0, delay_seconds))
        except asyncio.TimeoutError:
            return
        if self._reconnect.is_set() and not self._shutdown.is_set():
            self._reconnect.clear()

    def _client_session_kwargs(self, client_session_cls: Any) -> dict[str, Any]:
        if not _client_session_supports_message_handler(client_session_cls):
            return {}
        return {"message_handler": self._make_message_handler()}

    def _make_message_handler(self):
        async def _handler(message: Any) -> None:
            if isinstance(message, Exception):
                logger.debug("MCP message handler for '%s' received exception: %s", self.name, message)
                return
            try:
                from mcp.types import (
                    PromptListChangedNotification,
                    ResourceListChangedNotification,
                    ServerNotification,
                    ToolListChangedNotification,
                )
            except Exception:
                return
            root = getattr(message, "root", message)
            if isinstance(message, ServerNotification):
                root = message.root
            if isinstance(root, ToolListChangedNotification):
                logger.info("MCP server '%s' reported tools/list_changed; refreshing tools.", self.name)
                self._schedule_tools_refresh()
                await asyncio.sleep(0)
            elif isinstance(root, PromptListChangedNotification):
                logger.debug("MCP server '%s' reported prompts/list_changed.", self.name)
            elif isinstance(root, ResourceListChangedNotification):
                logger.debug("MCP server '%s' reported resources/list_changed.", self.name)

        return _handler

    def _schedule_tools_refresh(self) -> asyncio.Task:
        task = asyncio.create_task(self._refresh_tools_task())
        self._pending_refresh_tasks.add(task)
        task.add_done_callback(self._pending_refresh_tasks.discard)
        return task

    async def _refresh_tools_task(self) -> None:
        try:
            await self.refresh_tools()
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self.error = sanitize_mcp_error(_format_exception(error))
            logger.warning("MCP server '%s' dynamic tool refresh failed: %s", self.name, self.error)

    async def refresh_tools(self) -> None:
        if self.session is None:
            raise RuntimeError(f"MCP server '{self.name}' is not connected")
        async with self._refresh_lock:
            async with self._rpc_lock:
                tools_result = await self.session.list_tools()
            self.tools = list(tools_result.tools if hasattr(tools_result, "tools") else [])
            if self._refresh_callback is not None:
                await self._refresh_callback(self)

    def _track_stdio_process(self, process: Any) -> None:
        if process is not None:
            self._stdio_processes.add(process)

    def _untrack_stdio_process(self, process: Any) -> None:
        self._stdio_processes.discard(process)

    async def _cleanup_stdio_processes(self) -> None:
        processes = list(self._stdio_processes)
        if not processes:
            return
        await asyncio.gather(*(_cleanup_stdio_process(process) for process in processes), return_exceptions=True)
        for process in processes:
            self._untrack_stdio_process(process)


class MCPManager:
    def __init__(self, registry: ToolRegistry, *, media_store: Any = None) -> None:
        self.registry = registry
        self.media_store = media_store
        self._servers: dict[str, MCPServerTask] = {}
        self._statuses: dict[str, dict[str, Any]] = {}
        self._lock = threading.RLock()

    def discover_from_settings(self) -> list[str]:
        settings = read_mcp_settings()
        return self.register_servers(settings.get("servers") or [])

    def register_servers(self, servers: list[dict[str, Any]]) -> list[str]:
        enabled_servers = [server for server in servers if server.get("enabled") is not False]
        if not enabled_servers:
            return []

        async def _register_all() -> list[str]:
            results = await asyncio.gather(
                *(self._connect_and_register(server) for server in enabled_servers),
                return_exceptions=True,
            )
            registered: list[str] = []
            for server, result in zip(enabled_servers, results):
                if isinstance(result, Exception):
                    server_id = str(server.get("id") or "")
                    self._statuses[server_id] = {
                        "connected": False,
                        "error": sanitize_mcp_error(_format_exception(result)),
                        "tools": [],
                        "toolCount": 0,
                        "state": "error",
                        "failureCount": _MAX_INITIAL_CONNECT_RETRIES,
                        "nextRetryAt": None,
                        "circuitOpen": False,
                    }
                    continue
                registered.extend(result)
            return registered

        try:
            return _run_on_mcp_loop(_register_all(), timeout=120)
        except Exception as error:
            logger.warning("MCP discovery failed: %s", error)
            return []

    def statuses(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            statuses = deepcopy(self._statuses)
            for server_id, server in self._servers.items():
                status = statuses.setdefault(server_id, {})
                status.update(_server_status_details(server))
                if status.get("connected") and server.session is None:
                    status["connected"] = False
                    status["error"] = server.error or "MCP server disconnected."
            return statuses

    def reconnect_server(self, server_id: str) -> dict[str, Any]:
        server_id = str(server_id or "").strip()
        if not server_id:
            raise ValueError("MCP server id is required.")

        async def _request_reconnect() -> dict[str, Any]:
            with self._lock:
                server = self._servers.get(server_id)
            if server is None:
                return {"success": False, "serverId": server_id, "error": "MCP server is not running.", "code": "mcp_server_not_running"}
            server.failure_count = 0
            server.next_retry_at = 0.0
            server.state = "reconnecting"
            server._reconnect.set()
            status = _server_status_details(server)
            with self._lock:
                current = self._statuses.setdefault(server.id, {})
                current.update(status)
            return {"success": True, "serverId": server.id, "status": status}

        return _run_on_mcp_loop(_request_reconnect(), timeout=5)

    def reset_server_circuit(self, server_id: str) -> dict[str, Any]:
        server_id = str(server_id or "").strip()
        if not server_id:
            raise ValueError("MCP server id is required.")

        async def _reset_circuit() -> dict[str, Any]:
            with self._lock:
                server = self._servers.get(server_id)
            if server is None:
                return {"success": False, "serverId": server_id, "error": "MCP server is not running.", "code": "mcp_server_not_running"}
            server.failure_count = 0
            server.next_retry_at = 0.0
            server.state = "reconnecting"
            server._reconnect.set()
            status = _server_status_details(server)
            with self._lock:
                current = self._statuses.setdefault(server.id, {})
                current.update(status)
            return {"success": True, "serverId": server.id, "status": status}

        return _run_on_mcp_loop(_reset_circuit(), timeout=5)

    def shutdown(self) -> None:
        with self._lock:
            servers = list(self._servers.values())
            registered_names = [name for server in servers for name in server.registered_tool_names]
            self._servers.clear()
            self._statuses.clear()
        for name in registered_names:
            self.registry.deregister(name)

        async def _shutdown_all() -> None:
            await asyncio.gather(*(server.shutdown() for server in servers), return_exceptions=True)

        if servers:
            try:
                _run_on_mcp_loop(_shutdown_all(), timeout=10)
            except Exception as error:
                logger.debug("MCP shutdown failed: %s", error)

    async def _connect_and_register(self, server_config: dict[str, Any]) -> list[str]:
        server = MCPServerTask(server_config, refresh_callback=self._refresh_server_tools)
        await server.start()
        with self._lock:
            self._servers[server.id] = server
        registered = self._register_server_tools(server)
        return registered

    def _register_server_tools(self, server: MCPServerTask) -> list[str]:
        return self._sync_server_tools(server)

    async def _refresh_server_tools(self, server: MCPServerTask) -> list[str]:
        return self._sync_server_tools(server)

    def _sync_server_tools(self, server: MCPServerTask) -> list[str]:
        definitions: list[ToolDefinition] = []
        seen: set[str] = set()
        for mcp_tool in server.tools:
            original_name = str(getattr(mcp_tool, "name", "") or "").strip()
            if not original_name:
                continue
            if not _server_tool_filter_allows(server, original_name):
                continue
            tool_name = mcp_tool_name(server.id, original_name)
            existing = self.registry.get(tool_name)
            if tool_name in seen or (existing is not None and not existing.metadata.get("mcp")):
                logger.warning("MCP tool collision skipped: %s", tool_name)
                continue
            seen.add(tool_name)
            definitions.append(self._tool_definition_for_mcp_tool(server, mcp_tool, original_name, tool_name))

        for definition in self._utility_tool_definitions(server):
            if definition.name in seen:
                logger.warning("MCP utility collision skipped: %s", definition.name)
                continue
            existing = self.registry.get(definition.name)
            if existing is not None and not existing.metadata.get("mcp"):
                logger.warning("MCP utility collision skipped: %s", definition.name)
                continue
            seen.add(definition.name)
            definitions.append(definition)

        registered = [definition.name for definition in definitions]
        previous = set(server.registered_tool_names)
        for definition in definitions:
            self.registry.upsert(definition)
        for stale_name in sorted(previous - set(registered)):
            self.registry.deregister(stale_name)

        server.registered_tool_names = list(registered)
        all_mcp_tools = set(self.registry.tool_names_for_toolset(TOOLSET)) | set(registered)
        if all_mcp_tools:
            self.registry.register_toolset_alias(TOOLSET, tuple(sorted(all_mcp_tools)))

        summaries = [_tool_summary_from_definition(definition) for definition in definitions]
        status_warnings = _collect_security_warnings(summaries)
        with self._lock:
            status = {
                "connected": bool(server.session),
                "error": "" if server.session else str(server.error or "MCP server disconnected."),
                "tools": summaries,
                "toolCount": len(registered),
                **_server_status_details(server),
            }
            if status_warnings:
                status["securityWarnings"] = status_warnings
            self._statuses[server.id] = status
        return registered

    def _tool_definition_for_mcp_tool(
        self,
        server: MCPServerTask,
        mcp_tool: Any,
        original_name: str,
        tool_name: str,
    ) -> ToolDefinition:
        warnings: list[dict[str, Any]] = []
        raw_description = str(getattr(mcp_tool, "description", "") or f"MCP tool {original_name} from {server.name}")
        description = _sanitize_mcp_description(
            raw_description,
            surface="tool_description",
            warnings=warnings,
            fallback=f"MCP tool {original_name} from {server.name}.",
        )
        parameters = _sanitize_mcp_schema_descriptions(
            _normalize_mcp_input_schema(getattr(mcp_tool, "inputSchema", None)),
            warnings=warnings,
            surface="tool_schema",
        )
        annotations = _mcp_tool_annotations(mcp_tool)
        output_schema = _mcp_tool_output_schema(mcp_tool, warnings=warnings)
        read_only = _mcp_tool_read_only(mcp_tool)
        risk = _mcp_tool_risk(annotations, read_only=read_only)
        return ToolDefinition(
            name=tool_name,
            description=description,
            parameters=parameters,
            handler=self._make_tool_handler(server.id, original_name, float(server.server.get("timeoutSeconds") or 120)),
            toolset=TOOLSET,
            read_only=read_only,
            mutating=not read_only,
            risk=risk,
            kind="external",
            result_max_chars=100_000,
            availability_check=self._make_availability_check(server.id),
            output_schema=output_schema,
            metadata={
                "mcp": True,
                "serverId": server.id,
                "serverName": server.name,
                "originalToolName": original_name,
                "mcpAnnotations": annotations,
                "mcpTitle": annotations.get("title", ""),
                "mcpHasOutputSchema": output_schema is not None,
                "securityWarnings": warnings,
            },
        )

    def _utility_tool_definitions(self, server: MCPServerTask) -> list[ToolDefinition]:
        timeout = float(server.server.get("timeoutSeconds") or 120)
        definitions: list[ToolDefinition] = []

        def _add_utility(utility_name: str, description: str, parameters: dict[str, Any], handler: Any) -> None:
            if not _server_tool_filter_allows(server, utility_name):
                return
            definitions.append(ToolDefinition(
                name=mcp_tool_name(server.id, utility_name),
                description=description,
                parameters=parameters,
                handler=handler,
                toolset=TOOLSET,
                read_only=True,
                mutating=False,
                risk="read",
                kind="external",
                result_max_chars=100_000,
                availability_check=self._make_availability_check(server.id),
                metadata=_mcp_utility_metadata(server, utility_name),
            ))

        if _server_supports_capability(server, "resources"):
            _add_utility(
                "list_resources",
                f"List resources exposed by MCP server '{server.name}'.",
                {"type": "object", "properties": {}},
                self._make_list_resources_handler(server.id, timeout),
            )
            _add_utility(
                "read_resource",
                f"Read a resource from MCP server '{server.name}' by URI.",
                {
                    "type": "object",
                    "properties": {"uri": {"type": "string", "description": "Resource URI to read."}},
                    "required": ["uri"],
                },
                self._make_read_resource_handler(server.id, timeout),
            )
        if _server_supports_capability(server, "prompts"):
            _add_utility(
                "list_prompts",
                f"List prompts exposed by MCP server '{server.name}'.",
                {"type": "object", "properties": {}},
                self._make_list_prompts_handler(server.id, timeout),
            )
            _add_utility(
                "get_prompt",
                f"Get a prompt from MCP server '{server.name}' by name.",
                {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Prompt name."},
                        "arguments": {
                            "type": "object",
                            "description": "Optional prompt arguments.",
                            "properties": {},
                            "additionalProperties": True,
                        },
                    },
                    "required": ["name"],
                },
                self._make_get_prompt_handler(server.id, timeout),
            )
        return definitions

    def _make_availability_check(self, server_id: str):
        def _check() -> dict[str, Any]:
            with self._lock:
                server = self._servers.get(server_id)
                status = self._statuses.get(server_id, {})
            details = _server_status_details(server) if server is not None else {}
            circuit_open = bool(details.get("circuitOpen"))
            error = str(status.get("error") or "")
            if circuit_open:
                error = "MCP server circuit is open; retry after cooldown."
            status_connected = status.get("connected")
            return {
                "available": bool(server and server.session and not circuit_open and status_connected is not False),
                "serverId": server_id,
                "error": error,
                "code": "mcp_circuit_open" if circuit_open else "",
                "state": str(details.get("state") or status.get("state") or ""),
                "failureCount": int(details.get("failureCount") or status.get("failureCount") or 0),
                "nextRetryAt": details.get("nextRetryAt") if details.get("nextRetryAt") is not None else status.get("nextRetryAt"),
                "circuitOpen": circuit_open,
            }

        return _check

    def _make_tool_handler(self, server_id: str, original_tool_name: str, timeout: float):
        def _handler(arguments: dict[str, Any]) -> dict[str, Any]:
            ok, result = self._call_server_operation(
                server_id,
                timeout,
                f"tools/call {original_tool_name}",
                lambda server: server.call_tool(original_tool_name, arguments or {}, timeout=timeout),
            )
            if not ok:
                return result
            return _tool_result_payload(
                result,
                server_id=server_id,
                media_store=self.media_store,
                tool_name=original_tool_name,
            )

        return _handler

    def _make_list_resources_handler(self, server_id: str, timeout: float):
        def _handler(arguments: dict[str, Any]) -> dict[str, Any]:
            ok, result = self._call_server_operation(
                server_id,
                timeout,
                "resources/list",
                lambda server: server.list_resources(),
            )
            if not ok:
                return result
            resources = [_resource_summary(resource) for resource in getattr(result, "resources", []) or []]
            payload = {"success": True, "server_id": server_id, "resources": resources, "count": len(resources)}
            _attach_mcp_security_payload(payload, _mcp_security_warnings(resources, surface="resource_result"))
            return payload

        return _handler

    def _make_read_resource_handler(self, server_id: str, timeout: float):
        def _handler(arguments: dict[str, Any]) -> dict[str, Any]:
            uri = str((arguments or {}).get("uri") or "").strip()
            if not uri:
                return {"success": False, "error": "Missing required parameter: uri", "code": "missing_uri", "server_id": server_id}
            ok, result = self._call_server_operation(
                server_id,
                timeout,
                "resources/read",
                lambda server: server.read_resource(uri),
            )
            if not ok:
                return result
            artifacts: list[dict[str, Any]] = []
            media_errors: list[dict[str, Any]] = []
            contents = [
                _resource_content_summary(
                    content,
                    server_id=server_id,
                    media_store=self.media_store,
                    tool_name="read_resource",
                    resource_uri=uri,
                    artifacts=artifacts,
                    media_errors=media_errors,
                )
                for content in getattr(result, "contents", []) or []
            ]
            text = "\n".join(item.get("text") or item.get("blob", "") for item in contents if item.get("text") or item.get("blob"))
            payload: dict[str, Any] = {"success": True, "server_id": server_id, "uri": uri, "contents": contents, "result": text}
            _attach_mcp_media_payload(payload, artifacts, media_errors)
            _attach_mcp_security_payload(payload, _mcp_security_warnings(payload, surface="resource_result"))
            return payload

        return _handler

    def _make_list_prompts_handler(self, server_id: str, timeout: float):
        def _handler(arguments: dict[str, Any]) -> dict[str, Any]:
            ok, result = self._call_server_operation(
                server_id,
                timeout,
                "prompts/list",
                lambda server: server.list_prompts(),
            )
            if not ok:
                return result
            prompts = [_prompt_summary(prompt) for prompt in getattr(result, "prompts", []) or []]
            payload = {"success": True, "server_id": server_id, "prompts": prompts, "count": len(prompts)}
            _attach_mcp_security_payload(payload, _mcp_security_warnings(prompts, surface="prompt_result"))
            return payload

        return _handler

    def _make_get_prompt_handler(self, server_id: str, timeout: float):
        def _handler(arguments: dict[str, Any]) -> dict[str, Any]:
            name = str((arguments or {}).get("name") or "").strip()
            if not name:
                return {"success": False, "error": "Missing required parameter: name", "code": "missing_name", "server_id": server_id}
            prompt_arguments = (arguments or {}).get("arguments")
            if not isinstance(prompt_arguments, dict):
                prompt_arguments = {}
            ok, result = self._call_server_operation(
                server_id,
                timeout,
                "prompts/get",
                lambda server: server.get_prompt(name, prompt_arguments),
            )
            if not ok:
                return result
            artifacts: list[dict[str, Any]] = []
            media_errors: list[dict[str, Any]] = []
            messages = [
                _prompt_message_summary(
                    message,
                    server_id=server_id,
                    media_store=self.media_store,
                    tool_name="get_prompt",
                    artifacts=artifacts,
                    media_errors=media_errors,
                )
                for message in getattr(result, "messages", []) or []
            ]
            payload: dict[str, Any] = {"success": True, "server_id": server_id, "name": name, "messages": messages}
            description = getattr(result, "description", None)
            if description:
                payload["description"] = str(description)
            _attach_mcp_media_payload(payload, artifacts, media_errors)
            _attach_mcp_security_payload(payload, _mcp_security_warnings(payload, surface="prompt_result"))
            return payload

        return _handler

    def _call_server_operation(self, server_id: str, timeout: float, description: str, call_factory: Any) -> tuple[bool, Any]:
        with self._lock:
            server = self._servers.get(server_id)
        if server is not None and bool(_server_status_details(server).get("circuitOpen")):
            return False, {
                "success": False,
                "error": "MCP server circuit is open; retry after cooldown.",
                "code": "mcp_circuit_open",
                "server_id": server_id,
                **_server_status_details(server),
            }
        if server is None or server.session is None:
            return False, {
                "success": False,
                "error": "MCP server is not connected.",
                "code": "mcp_server_disconnected",
                "server_id": server_id,
            }

        async def _call() -> Any:
            return await call_factory(server)

        try:
            return True, _run_on_mcp_loop(_call(), timeout=timeout + 1)
        except TimeoutError as error:
            error_text = sanitize_mcp_error(str(error))
            self._mark_server_disconnected(server_id, error_text)
            if server is not None:
                reconnect_event = getattr(server, "_reconnect", None)
                set_reconnect = getattr(reconnect_event, "set", None)
                if callable(set_reconnect):
                    set_reconnect()
            return False, {
                "success": False,
                "error": error_text,
                "code": "mcp_timeout",
                "server_id": server_id,
            }
        except Exception as error:
            if _is_session_expired_error(error):
                try:
                    return True, self._retry_after_reconnect(server, timeout, call_factory)
                except Exception as retry_error:
                    error_text = sanitize_mcp_error(
                        f"MCP reconnect retry failed during {description}: {type(retry_error).__name__}: {_format_exception(retry_error)}"
                    )
                    self._mark_server_disconnected(server_id, error_text)
                    return False, {
                        "success": False,
                        "error": error_text,
                        "code": "mcp_reconnect_failed",
                        "server_id": server_id,
                    }
            error_text = sanitize_mcp_error(f"MCP call failed: {type(error).__name__}: {_format_exception(error)}")
            self._mark_server_disconnected(server_id, error_text)
            return False, {
                "success": False,
                "error": error_text,
                "code": "mcp_call_failed",
                "server_id": server_id,
            }

    def _retry_after_reconnect(self, server: MCPServerTask, timeout: float, call_factory: Any) -> Any:
        async def _retry() -> Any:
            reconnected = await server.reconnect_and_wait(timeout=15)
            if not reconnected:
                raise TimeoutError("MCP session reconnect timed out after 15s")
            return await call_factory(server)

        return _run_on_mcp_loop(_retry(), timeout=timeout + 16)

    def _mark_server_disconnected(self, server_id: str, error_text: str) -> None:
        with self._lock:
            status = self._statuses.setdefault(server_id, {})
            status["connected"] = False
            status["error"] = error_text
            server = self._servers.get(server_id)
            if server is not None:
                status.update(_server_status_details(server))


def probe_mcp_server(server_config: dict[str, Any]) -> dict[str, Any]:
    server = normalize_mcp_server_config(server_config, strict=True)

    async def _probe() -> dict[str, Any]:
        task = MCPServerTask(server)
        try:
            await task.start()
            tools = _server_tool_summaries(task)
            return {"success": True, "tools": tools, "toolCount": len(tools), "error": ""}
        finally:
            await task.shutdown()

    try:
        return _run_on_mcp_loop(_probe(), timeout=float(server.get("connectTimeoutSeconds") or 10) + 10)
    except Exception as error:
        return {
            "success": False,
            "tools": [],
            "toolCount": 0,
            "error": sanitize_mcp_error(_format_exception(error)),
        }


def _normalize_mcp_input_schema(schema: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(schema, dict) or not schema:
        return {"type": "object", "properties": {}}

    def _rewrite_local_refs(node: Any) -> Any:
        if isinstance(node, list):
            return [_rewrite_local_refs(item) for item in node]
        if not isinstance(node, dict):
            return node
        rewritten: dict[str, Any] = {}
        for key, value in node.items():
            out_key = "$defs" if key == "definitions" else key
            rewritten[out_key] = _rewrite_local_refs(value)
        ref = rewritten.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/definitions/"):
            rewritten["$ref"] = "#/$defs/" + ref[len("#/definitions/"):]
        return rewritten

    def _strip_nullable(node: Any) -> Any:
        if isinstance(node, list):
            return [_strip_nullable(item) for item in node]
        if not isinstance(node, dict):
            return node
        cleaned = {key: _strip_nullable(value) for key, value in node.items()}
        for combiner in ("anyOf", "oneOf"):
            value = cleaned.get(combiner)
            if not isinstance(value, list):
                continue
            non_null = [item for item in value if not (isinstance(item, dict) and item.get("type") == "null")]
            if len(non_null) == 1 and len(non_null) != len(value):
                merged = dict(non_null[0])
                for key, original_value in cleaned.items():
                    if key not in {combiner, "type"} and key not in merged:
                        merged[key] = original_value
                merged["nullable"] = True
                return _strip_nullable(merged)
        return cleaned

    def _repair(node: Any) -> Any:
        if isinstance(node, list):
            return [_repair(item) for item in node]
        if not isinstance(node, dict):
            return node
        repaired = {key: _repair(value) for key, value in node.items()}
        if not repaired.get("type") and ("properties" in repaired or "required" in repaired):
            repaired["type"] = "object"
        if repaired.get("type") == "object":
            properties = repaired.get("properties")
            if not isinstance(properties, dict):
                repaired["properties"] = {}
                properties = repaired["properties"]
            required = repaired.get("required")
            if isinstance(required, list):
                valid = [item for item in required if isinstance(item, str) and item in properties]
                if valid:
                    repaired["required"] = valid
                else:
                    repaired.pop("required", None)
        return repaired

    normalized = _repair(_strip_nullable(_rewrite_local_refs(schema)))
    if not isinstance(normalized, dict) or normalized.get("type") != "object":
        return {"type": "object", "properties": {}}
    normalized.setdefault("properties", {})
    if not isinstance(normalized["properties"], dict):
        normalized["properties"] = {}
    return normalized


def _mcp_tool_read_only(tool: Any) -> bool:
    annotations = _mcp_tool_annotations(tool)
    return annotations.get("readOnlyHint") is True


def _mcp_tool_annotations(tool: Any) -> dict[str, Any]:
    raw_annotations = _first_field(tool, "annotations")
    payload: dict[str, Any] = {}
    title = _first_field(tool, "title") or _annotation_value(raw_annotations, "title")
    if title is not None and str(title).strip():
        payload["title"] = str(title).strip()
    for output_key, names in (
        ("readOnlyHint", ("readOnlyHint", "read_only_hint")),
        ("destructiveHint", ("destructiveHint", "destructive_hint")),
        ("idempotentHint", ("idempotentHint", "idempotent_hint")),
        ("openWorldHint", ("openWorldHint", "open_world_hint")),
    ):
        value = _annotation_value(raw_annotations, *names)
        if value is not None:
            payload[output_key] = bool(value)
    return payload


def _annotation_value(annotations: Any, *names: str) -> Any:
    if annotations is None:
        return None
    for name in names:
        value = _get_field(annotations, name)
        if value is not None:
            return value
    return None


def _mcp_tool_risk(annotations: dict[str, Any], *, read_only: bool) -> str:
    if read_only:
        return "read"
    if annotations.get("destructiveHint") is True:
        return "destructive"
    return "write"


def _mcp_tool_output_schema(tool: Any, *, warnings: list[dict[str, Any]] | None = None) -> dict[str, Any] | None:
    schema = _first_field(tool, "outputSchema", "output_schema")
    if not isinstance(schema, dict) or not schema:
        return None
    return _sanitize_mcp_schema_descriptions(
        _json_safe_value(schema),
        warnings=warnings if warnings is not None else [],
        surface="tool_output_schema",
    )


def _tool_result_payload(result: Any, *, server_id: str, media_store: Any = None, tool_name: str = "") -> dict[str, Any]:
    if bool(getattr(result, "isError", False)):
        error_text = _content_blocks_text(getattr(result, "content", None)) or "MCP tool returned an error."
        payload = {
            "success": False,
            "error": sanitize_mcp_error(error_text),
            "code": "mcp_tool_error",
            "server_id": server_id,
        }
        _attach_mcp_security_payload(payload, _mcp_security_warnings(error_text, surface="tool_result"))
        return payload
    rendered = _render_mcp_content_blocks(
        getattr(result, "content", None),
        server_id=server_id,
        media_store=media_store,
        tool_name=tool_name,
    )
    text = rendered["text"]
    structured = getattr(result, "structuredContent", None)
    payload: dict[str, Any] = {"success": True, "server_id": server_id}
    if text:
        payload["result"] = text
    if structured is not None:
        payload["structuredContent"] = structured
        if not text:
            payload["result"] = structured
    if "result" not in payload:
        payload["result"] = ""
    _attach_mcp_media_payload(payload, rendered["artifacts"], rendered["mediaErrors"])
    _attach_mcp_security_payload(payload, _mcp_security_warnings(payload, surface="tool_result"))
    return payload


def _content_blocks_text(content: Any) -> str:
    return _render_mcp_content_blocks(content)["text"]


def _render_mcp_content_blocks(
    content: Any,
    *,
    server_id: str = "",
    media_store: Any = None,
    tool_name: str = "",
    resource_uri: str = "",
) -> dict[str, Any]:
    blocks = content if isinstance(content, list) else ([] if content is None else [content])
    parts: list[str] = []
    artifacts: list[dict[str, Any]] = []
    media_errors: list[dict[str, Any]] = []
    for block in blocks:
        text = _first_field(block, "text")
        if text:
            parts.append(str(text))
            continue
        data = _first_field(block, "data")
        mime_type = str(_first_field(block, "mimeType", "mime_type") or "")
        if data is not None and mime_type.lower().startswith("image/"):
            parts.append(_mcp_image_summary(
                data,
                mime_type,
                server_id=server_id,
                media_store=media_store,
                tool_name=tool_name,
                resource_uri=resource_uri,
                file_name=str(_first_field(block, "fileName", "file_name", "name") or ""),
                artifacts=artifacts,
                media_errors=media_errors,
            ))
            continue
        if data is not None and _is_safe_mcp_pdf_mime(mime_type):
            parts.append(_mcp_pdf_summary(
                data,
                mime_type,
                server_id=server_id,
                media_store=media_store,
                tool_name=tool_name,
                resource_uri=resource_uri,
                file_name=str(_first_field(block, "fileName", "file_name", "name") or ""),
                artifacts=artifacts,
                media_errors=media_errors,
            ))
            continue
        if data is not None and _is_safe_mcp_file_mime(mime_type):
            parts.append(_mcp_file_summary(
                data,
                mime_type,
                encoded=True,
                server_id=server_id,
                media_store=media_store,
                tool_name=tool_name,
                resource_uri=resource_uri,
                file_name=str(_first_field(block, "fileName", "file_name", "name") or ""),
                artifacts=artifacts,
                media_errors=media_errors,
            ))
    return {"text": "\n".join(parts), "artifacts": artifacts, "mediaErrors": media_errors}


def _attach_mcp_media_payload(
    payload: dict[str, Any],
    artifacts: list[dict[str, Any]],
    media_errors: list[dict[str, Any]],
) -> None:
    if artifacts:
        payload["artifact"] = artifacts[0]
        payload["artifacts"] = artifacts
    if media_errors:
        payload["mediaErrors"] = media_errors


def _attach_mcp_security_payload(payload: dict[str, Any], warnings: list[dict[str, Any]]) -> None:
    if not warnings:
        return
    existing = payload.get("securityWarnings")
    combined: list[dict[str, Any]] = list(existing) if isinstance(existing, list) else []
    _extend_security_warnings(combined, warnings)
    payload["securityWarnings"] = combined


def _mcp_image_summary(
    data: Any,
    mime_type: str,
    *,
    server_id: str = "",
    media_store: Any = None,
    tool_name: str = "",
    resource_uri: str = "",
    file_name: str = "",
    artifacts: list[dict[str, Any]] | None = None,
    media_errors: list[dict[str, Any]] | None = None,
) -> str:
    normalized_mime = str(mime_type or "").lower()
    size = _decoded_media_size(data)
    if media_store is None:
        return f"[MCP image content: {normalized_mime}, {size} bytes]"
    create_mcp_image = getattr(media_store, "create_mcp_image", None)
    if not callable(create_mcp_image):
        return f"[MCP image content: {normalized_mime}, {size} bytes]"
    try:
        artifact = create_mcp_image(
            _mcp_image_data_value(data),
            mime_type=normalized_mime,
            server_id=server_id,
            tool_name=tool_name,
            resource_uri=resource_uri,
            file_name=file_name,
        )
    except Exception as error:
        if media_errors is not None:
            media_errors.append({
                "code": "mcp_media_artifact_failed",
                "mimeType": normalized_mime,
                "error": sanitize_mcp_error(_format_exception(error)),
            })
        return f"[MCP image content: {normalized_mime}, {size} bytes]"
    payload = artifact.to_dict() if hasattr(artifact, "to_dict") else dict(artifact)
    if artifacts is not None:
        artifacts.append(payload)
    return (
        f"[MCP image artifact: {payload.get('fileName') or 'image'}, "
        f"{payload.get('mimeType') or normalized_mime}, {payload.get('size') or size} bytes]"
    )


def _mcp_image_data_value(data: Any) -> str:
    if isinstance(data, bytes):
        return base64.b64encode(data).decode("ascii")
    return str(data or "")


def _mcp_file_summary(
    data: Any,
    mime_type: str,
    *,
    encoded: bool,
    server_id: str = "",
    media_store: Any = None,
    tool_name: str = "",
    resource_uri: str = "",
    file_name: str = "",
    artifacts: list[dict[str, Any]] | None = None,
    media_errors: list[dict[str, Any]] | None = None,
) -> str:
    normalized_mime = str(mime_type or "").lower()
    try:
        text = _decode_mcp_file_content(data) if encoded else ("" if data is None else str(data))
    except Exception as error:
        if media_errors is not None:
            media_errors.append({
                "code": "mcp_media_artifact_failed",
                "mimeType": normalized_mime,
                "error": sanitize_mcp_error(_format_exception(error)),
            })
        return f"[MCP file content: {normalized_mime}, {_decoded_media_size(data)} bytes]"

    preview = _mcp_file_preview(text)
    if media_store is None:
        return preview
    create_mcp_file = getattr(media_store, "create_mcp_file", None)
    if not callable(create_mcp_file):
        return preview
    try:
        artifact = create_mcp_file(
            text,
            mime_type=normalized_mime,
            server_id=server_id,
            tool_name=tool_name,
            resource_uri=resource_uri,
            file_name=file_name,
        )
    except Exception as error:
        if media_errors is not None:
            media_errors.append({
                "code": "mcp_media_artifact_failed",
                "mimeType": normalized_mime,
                "error": sanitize_mcp_error(_format_exception(error)),
            })
        return preview
    payload = artifact.to_dict() if hasattr(artifact, "to_dict") else dict(artifact)
    if artifacts is not None:
        artifacts.append(payload)
    summary = (
        f"[MCP file artifact: {payload.get('fileName') or 'file'}, "
        f"{payload.get('mimeType') or normalized_mime}, {payload.get('size') or len(text.encode('utf-8'))} bytes]"
    )
    return "\n".join(part for part in (summary, preview) if part)


def _mcp_pdf_summary(
    data: Any,
    mime_type: str,
    *,
    server_id: str = "",
    media_store: Any = None,
    tool_name: str = "",
    resource_uri: str = "",
    file_name: str = "",
    artifacts: list[dict[str, Any]] | None = None,
    media_errors: list[dict[str, Any]] | None = None,
) -> str:
    normalized_mime = str(mime_type or "").lower()
    size = _decoded_media_size(data)
    fallback = f"[MCP PDF content: {normalized_mime}, {size} bytes]"
    if media_store is None:
        return fallback
    create_mcp_pdf = getattr(media_store, "create_mcp_pdf", None)
    if not callable(create_mcp_pdf):
        return fallback
    try:
        artifact = create_mcp_pdf(
            data,
            mime_type=normalized_mime,
            server_id=server_id,
            tool_name=tool_name,
            resource_uri=resource_uri,
            file_name=file_name,
        )
    except Exception as error:
        if media_errors is not None:
            media_errors.append({
                "code": "mcp_media_artifact_failed",
                "mimeType": normalized_mime,
                "error": sanitize_mcp_error(_format_exception(error)),
            })
        return fallback
    payload = artifact.to_dict() if hasattr(artifact, "to_dict") else dict(artifact)
    if artifacts is not None:
        artifacts.append(payload)
    return (
        f"[MCP PDF artifact: {payload.get('fileName') or 'document.pdf'}, "
        f"{payload.get('mimeType') or normalized_mime}, {payload.get('size') or size} bytes]"
    )


def _decode_mcp_file_content(data: Any) -> str:
    if isinstance(data, bytes):
        raw = data
    else:
        text = str(data or "").strip()
        if text.startswith("data:") and "," in text:
            text = text.split(",", 1)[1]
        raw = base64.b64decode(text, validate=True)
    if len(raw) > _MAX_MCP_FILE_BYTES:
        raise ValueError("MCP file payload is too large.")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError("MCP file content must be UTF-8 text.") from error


def _mcp_file_preview(text: str) -> str:
    value = str(text or "")
    if len(value) <= _MCP_FILE_PREVIEW_CHARS:
        return value
    preview = value[:_MCP_FILE_PREVIEW_CHARS].rstrip()
    return f"{preview}...[truncated {len(value) - len(preview)} chars]"


def _is_safe_mcp_file_mime(mime_type: str) -> bool:
    return str(mime_type or "").lower() in _SAFE_MCP_FILE_MIME_TYPES


def _is_safe_mcp_pdf_mime(mime_type: str) -> bool:
    return str(mime_type or "").lower() == _SAFE_MCP_PDF_MIME_TYPE


def _decoded_media_size(data: Any) -> int:
    if isinstance(data, bytes):
        return len(data)
    text = str(data or "").strip()
    if text.startswith("data:") and "," in text:
        text = text.split(",", 1)[1]
    try:
        return len(base64.b64decode(text, validate=True))
    except Exception:
        return len(text)


def _file_name_from_resource_uri(uri: str) -> str:
    value = str(uri or "").split("?", 1)[0].rstrip("/")
    if not value:
        return ""
    return value.rsplit("/", 1)[-1]


def _client_session_supports_message_handler(client_session_cls: Any) -> bool:
    try:
        return "message_handler" in inspect.signature(client_session_cls).parameters
    except (TypeError, ValueError):
        return False


def _server_supports_capability(server: MCPServerTask, capability: str) -> bool:
    capabilities = _get_field(getattr(server, "initialize_result", None), "capabilities")
    if capabilities is None:
        return False
    value = _get_field(capabilities, capability)
    return value is not None


def _server_status_details(server: Any) -> dict[str, Any]:
    status_details = getattr(server, "status_details", None)
    if callable(status_details):
        try:
            return dict(status_details())
        except Exception:
            pass
    next_retry_at = float(getattr(server, "next_retry_at", 0.0) or 0.0)
    state = str(getattr(server, "state", "connected" if getattr(server, "session", None) else "disconnected") or "")
    return {
        "state": state,
        "failureCount": int(getattr(server, "failure_count", 0) or 0),
        "nextRetryAt": next_retry_at if next_retry_at > 0 else None,
        "circuitOpen": bool(getattr(server, "circuit_open", False)),
    }


def _server_tool_filter_allows(server: MCPServerTask, tool_name: str) -> bool:
    name = str(tool_name or "").strip()
    if not name:
        return False
    include_patterns = _server_tool_filter_patterns(server, "includeTools")
    exclude_patterns = _server_tool_filter_patterns(server, "excludeTools")
    if include_patterns and not _matches_tool_filter(name, include_patterns):
        return False
    return not _matches_tool_filter(name, exclude_patterns)


def _server_tool_filter_patterns(server: MCPServerTask, field: str) -> list[str]:
    value = (server.server or {}).get(field)
    if value is None and field == "includeTools":
        value = (server.server or {}).get("include_tools")
    if value is None and field == "excludeTools":
        value = (server.server or {}).get("exclude_tools")
    if not isinstance(value, list):
        return []
    return [str(pattern or "").strip() for pattern in value if str(pattern or "").strip()]


def _matches_tool_filter(tool_name: str, patterns: list[str]) -> bool:
    return any(fnmatchcase(tool_name, pattern) for pattern in patterns)


def _mcp_utility_metadata(server: MCPServerTask, utility_name: str) -> dict[str, Any]:
    return {
        "mcp": True,
        "mcpUtility": True,
        "serverId": server.id,
        "serverName": server.name,
        "utilityName": utility_name,
    }


def _tool_summary_from_definition(definition: ToolDefinition) -> dict[str, Any]:
    metadata = definition.metadata or {}
    payload = {
        "name": str(metadata.get("originalToolName") or metadata.get("utilityName") or definition.name),
        "generatedName": definition.name,
        "description": definition.description,
        "readOnly": definition.read_only,
        "mutating": definition.mutating,
        "serverId": str(metadata.get("serverId") or ""),
        "serverName": str(metadata.get("serverName") or ""),
    }
    _attach_mcp_tool_metadata_summary(payload, metadata.get("mcpAnnotations"), bool(metadata.get("mcpHasOutputSchema")))
    warnings = metadata.get("securityWarnings")
    if isinstance(warnings, list) and warnings:
        payload["securityWarnings"] = warnings
    return payload


def _attach_mcp_tool_metadata_summary(
    payload: dict[str, Any],
    annotations: Any,
    has_output_schema: bool = False,
) -> None:
    if isinstance(annotations, dict) and annotations:
        payload["annotations"] = dict(annotations)
        title = annotations.get("title")
        if title:
            payload["title"] = str(title)
        for key in ("readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint"):
            if key in annotations:
                payload[key] = bool(annotations.get(key))
    if has_output_schema:
        payload["hasOutputSchema"] = True


def _server_tool_summaries(server: MCPServerTask) -> list[dict[str, Any]]:
    tools = [
        _tool_summary(server, tool, mcp_tool_name(server.id, getattr(tool, "name", "")))
        for tool in server.tools
        if _server_tool_filter_allows(server, str(getattr(tool, "name", "") or ""))
    ]
    if _server_supports_capability(server, "resources"):
        if _server_tool_filter_allows(server, "list_resources"):
            tools.append(_utility_tool_summary(server, "list_resources"))
        if _server_tool_filter_allows(server, "read_resource"):
            tools.append(_utility_tool_summary(server, "read_resource"))
    if _server_supports_capability(server, "prompts"):
        if _server_tool_filter_allows(server, "list_prompts"):
            tools.append(_utility_tool_summary(server, "list_prompts"))
        if _server_tool_filter_allows(server, "get_prompt"):
            tools.append(_utility_tool_summary(server, "get_prompt"))
    return tools


def _utility_tool_summary(server: MCPServerTask, utility_name: str) -> dict[str, Any]:
    return {
        "name": utility_name,
        "generatedName": mcp_tool_name(server.id, utility_name),
        "description": f"MCP utility {utility_name} for {server.name}.",
        "readOnly": True,
        "mutating": False,
        "serverId": server.id,
        "serverName": server.name,
    }


def _resource_summary(resource: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for output_key, field_names in (
        ("uri", ("uri",)),
        ("name", ("name",)),
        ("description", ("description",)),
        ("mimeType", ("mimeType", "mime_type")),
        ("size", ("size",)),
    ):
        value = _first_field(resource, *field_names)
        if value is not None:
            payload[output_key] = str(value) if output_key != "size" else value
    return payload


def _resource_content_summary(
    content: Any,
    *,
    server_id: str = "",
    media_store: Any = None,
    tool_name: str = "",
    resource_uri: str = "",
    artifacts: list[dict[str, Any]] | None = None,
    media_errors: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    uri = _first_field(content, "uri")
    if uri is not None:
        payload["uri"] = str(uri)
    mime_type = _first_field(content, "mimeType", "mime_type")
    if mime_type is not None:
        payload["mimeType"] = str(mime_type)
    text = _first_field(content, "text")
    if text is not None:
        if _is_safe_mcp_file_mime(str(mime_type or "")):
            previous_artifact_count = len(artifacts or [])
            payload["text"] = _mcp_file_summary(
                text,
                str(mime_type or ""),
                encoded=False,
                server_id=server_id,
                media_store=media_store,
                tool_name=tool_name,
                resource_uri=str(uri or resource_uri or ""),
                file_name=_file_name_from_resource_uri(str(uri or resource_uri or "")),
                artifacts=artifacts,
                media_errors=media_errors,
            )
            artifact = artifacts[-1] if artifacts and len(artifacts) > previous_artifact_count else None
            if artifact:
                payload["artifact"] = artifact
            return payload
        payload["text"] = str(text)
        return payload
    blob = _first_field(content, "blob")
    if blob is not None:
        if str(mime_type or "").lower().startswith("image/"):
            previous_artifact_count = len(artifacts or [])
            summary = _mcp_image_summary(
                blob,
                str(mime_type or ""),
                server_id=server_id,
                media_store=media_store,
                tool_name=tool_name,
                resource_uri=str(uri or resource_uri or ""),
                file_name=_file_name_from_resource_uri(str(uri or resource_uri or "")),
                artifacts=artifacts,
                media_errors=media_errors,
            )
            payload["blob"] = summary
            artifact = artifacts[-1] if artifacts and len(artifacts) > previous_artifact_count else None
            if artifact:
                payload["artifact"] = artifact
            return payload
        if _is_safe_mcp_pdf_mime(str(mime_type or "")):
            previous_artifact_count = len(artifacts or [])
            payload["blob"] = _mcp_pdf_summary(
                blob,
                str(mime_type or ""),
                server_id=server_id,
                media_store=media_store,
                tool_name=tool_name,
                resource_uri=str(uri or resource_uri or ""),
                file_name=_file_name_from_resource_uri(str(uri or resource_uri or "")),
                artifacts=artifacts,
                media_errors=media_errors,
            )
            artifact = artifacts[-1] if artifacts and len(artifacts) > previous_artifact_count else None
            if artifact:
                payload["artifact"] = artifact
            return payload
        if _is_safe_mcp_file_mime(str(mime_type or "")):
            previous_artifact_count = len(artifacts or [])
            payload["blob"] = _mcp_file_summary(
                blob,
                str(mime_type or ""),
                encoded=True,
                server_id=server_id,
                media_store=media_store,
                tool_name=tool_name,
                resource_uri=str(uri or resource_uri or ""),
                file_name=_file_name_from_resource_uri(str(uri or resource_uri or "")),
                artifacts=artifacts,
                media_errors=media_errors,
            )
            artifact = artifacts[-1] if artifacts and len(artifacts) > previous_artifact_count else None
            if artifact:
                payload["artifact"] = artifact
            return payload
        payload["blob"] = _summarize_blob(blob)
    return payload


def _prompt_summary(prompt: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    name = _first_field(prompt, "name")
    if name is not None:
        payload["name"] = str(name)
    description = _first_field(prompt, "description")
    if description is not None:
        payload["description"] = str(description)
    arguments = _first_field(prompt, "arguments")
    if arguments:
        payload["arguments"] = [_prompt_argument_summary(argument) for argument in arguments]
    return payload


def _prompt_argument_summary(argument: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    name = _first_field(argument, "name")
    if name is not None:
        payload["name"] = str(name)
    description = _first_field(argument, "description")
    if description is not None:
        payload["description"] = str(description)
    required = _first_field(argument, "required")
    if required is not None:
        payload["required"] = bool(required)
    return payload


def _prompt_message_summary(
    message: Any,
    *,
    server_id: str = "",
    media_store: Any = None,
    tool_name: str = "",
    artifacts: list[dict[str, Any]] | None = None,
    media_errors: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    role = _first_field(message, "role")
    if role is not None:
        payload["role"] = str(role)
    content = _first_field(message, "content")
    payload["content"] = _prompt_content_summary(
        content,
        server_id=server_id,
        media_store=media_store,
        tool_name=tool_name,
        artifacts=artifacts,
        media_errors=media_errors,
    )
    return payload


def _prompt_content_summary(
    content: Any,
    *,
    server_id: str = "",
    media_store: Any = None,
    tool_name: str = "",
    artifacts: list[dict[str, Any]] | None = None,
    media_errors: list[dict[str, Any]] | None = None,
) -> Any:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return [
            _prompt_content_summary(
                item,
                server_id=server_id,
                media_store=media_store,
                tool_name=tool_name,
                artifacts=artifacts,
                media_errors=media_errors,
            )
            for item in content
        ]
    text = _first_field(content, "text")
    if text is not None:
        return str(text)
    resource = _first_field(content, "resource")
    if resource is not None:
        return {
            "resource": _resource_content_summary(
                resource,
                server_id=server_id,
                media_store=media_store,
                tool_name=tool_name,
                artifacts=artifacts,
                media_errors=media_errors,
            )
        }
    data = _first_field(content, "data")
    mime_type = _first_field(content, "mimeType", "mime_type")
    if data is not None and mime_type is not None:
        if str(mime_type).lower().startswith("image/"):
            return _mcp_image_summary(
                data,
                str(mime_type),
                server_id=server_id,
                media_store=media_store,
                tool_name=tool_name,
                artifacts=artifacts,
                media_errors=media_errors,
            )
        if _is_safe_mcp_pdf_mime(str(mime_type)):
            return _mcp_pdf_summary(
                data,
                str(mime_type),
                server_id=server_id,
                media_store=media_store,
                tool_name=tool_name,
                artifacts=artifacts,
                media_errors=media_errors,
            )
        if _is_safe_mcp_file_mime(str(mime_type)):
            return _mcp_file_summary(
                data,
                str(mime_type),
                encoded=True,
                server_id=server_id,
                media_store=media_store,
                tool_name=tool_name,
                artifacts=artifacts,
                media_errors=media_errors,
            )
        return _summarize_media(data, str(mime_type))
    if isinstance(content, dict):
        return {str(key): _json_safe_value(value) for key, value in content.items()}
    return str(content)


def _is_session_expired_error(error: BaseException) -> bool:
    text = f"{type(error).__name__}: {_format_exception(error)}".lower()
    return any(marker in text for marker in _SESSION_EXPIRED_MARKERS)


def _tool_summary(server: MCPServerTask, tool: Any, generated_name: str) -> dict[str, Any]:
    read_only = _mcp_tool_read_only(tool)
    annotations = _mcp_tool_annotations(tool)
    warnings: list[dict[str, Any]] = []
    raw_description = str(getattr(tool, "description", "") or "")
    description = _sanitize_mcp_description(
        raw_description,
        surface="tool_description",
        warnings=warnings,
        fallback=f"MCP tool {getattr(tool, 'name', '') or generated_name} from {server.name}.",
    )
    payload = {
        "name": str(getattr(tool, "name", "") or ""),
        "generatedName": generated_name,
        "description": description,
        "readOnly": read_only,
        "mutating": not read_only,
        "serverId": server.id,
        "serverName": server.name,
    }
    _attach_mcp_tool_metadata_summary(payload, annotations, _mcp_tool_output_schema(tool, warnings=warnings) is not None)
    if warnings:
        payload["securityWarnings"] = warnings
    return payload


def _get_field(value: Any, name: str) -> Any:
    if value is None:
        return None
    if isinstance(value, dict):
        return value.get(name)
    return getattr(value, name, None)


def _first_field(value: Any, *names: str) -> Any:
    for name in names:
        found = _get_field(value, name)
        if found is not None:
            return found
    return None


def _summarize_blob(blob: Any) -> str:
    if isinstance(blob, bytes):
        return f"[binary content: {len(blob)} bytes]"
    text = str(blob)
    try:
        decoded_size = len(base64.b64decode(text, validate=True))
    except Exception:
        decoded_size = len(text)
    return f"[binary content: {decoded_size} bytes]"


def _summarize_media(data: Any, mime_type: str) -> str:
    if isinstance(data, bytes):
        size = len(data)
    else:
        text = str(data)
        try:
            size = len(base64.b64decode(text, validate=True))
        except Exception:
            size = len(text)
    return f"[MCP media content: {mime_type}, {size} bytes]"


def _json_safe_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, list):
        return [_json_safe_value(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_safe_value(item) for key, item in value.items()}
    return str(value)


def _resolve_stdio_env(user_env: Any) -> dict[str, str]:
    env = {
        key: value
        for key, value in os.environ.items()
        if key in _SAFE_ENV_KEYS or key.startswith("XDG_")
    }
    if isinstance(user_env, dict):
        env.update({str(key): str(value) for key, value in user_env.items()})
    return env


def _resolve_stdio_command(command: str, env: dict[str, str]) -> tuple[str, dict[str, str]]:
    resolved = os.path.expanduser(command)
    if os.sep not in resolved:
        hit = shutil.which(resolved, path=env.get("PATH"))
        if hit:
            resolved = hit
    command_dir = os.path.dirname(resolved)
    if command_dir:
        parts = [part for part in env.get("PATH", "").split(os.pathsep) if part]
        if command_dir not in parts:
            env = {**env, "PATH": os.pathsep.join([command_dir, *parts])}
    return resolved, env


@asynccontextmanager
async def _tracked_stdio_client(server: Any, errlog: Any = sys.stderr, *, track_process: Any = None, untrack_process: Any = None):
    from mcp.client import stdio as stdio_mod

    read_stream_writer, read_stream = stdio_mod.anyio.create_memory_object_stream(0)
    write_stream, write_stream_reader = stdio_mod.anyio.create_memory_object_stream(0)

    try:
        command = stdio_mod._get_executable_command(server.command)
        process = await stdio_mod._create_platform_compatible_process(
            command=command,
            args=server.args,
            env=(
                {**stdio_mod.get_default_environment(), **server.env}
                if server.env is not None
                else stdio_mod.get_default_environment()
            ),
            errlog=errlog,
            cwd=server.cwd,
        )
    except OSError:
        await read_stream.aclose()
        await write_stream.aclose()
        await read_stream_writer.aclose()
        await write_stream_reader.aclose()
        raise

    if callable(track_process):
        try:
            track_process(process)
        except Exception as error:
            logger.debug("Failed to track MCP stdio process: %s", error)

    async def stdout_reader() -> None:
        assert process.stdout, "Opened process is missing stdout"
        try:
            async with read_stream_writer:
                buffer = ""
                async for chunk in stdio_mod.TextReceiveStream(
                    process.stdout,
                    encoding=server.encoding,
                    errors=server.encoding_error_handler,
                ):
                    lines = (buffer + chunk).split("\n")
                    buffer = lines.pop()
                    for line in lines:
                        try:
                            message = stdio_mod.types.JSONRPCMessage.model_validate_json(line)
                        except Exception as exc:  # pragma: no cover
                            logger.exception("Failed to parse JSONRPC message from MCP stdio server")
                            await read_stream_writer.send(exc)
                            continue
                        await read_stream_writer.send(stdio_mod.SessionMessage(message))
        except stdio_mod.anyio.ClosedResourceError:  # pragma: no cover
            await stdio_mod.anyio.lowlevel.checkpoint()

    async def stdin_writer() -> None:
        assert process.stdin, "Opened process is missing stdin"
        try:
            async with write_stream_reader:
                async for session_message in write_stream_reader:
                    message_json = session_message.message.model_dump_json(by_alias=True, exclude_none=True)
                    await process.stdin.send(
                        (message_json + "\n").encode(
                            encoding=server.encoding,
                            errors=server.encoding_error_handler,
                        )
                    )
        except stdio_mod.anyio.ClosedResourceError:  # pragma: no cover
            await stdio_mod.anyio.lowlevel.checkpoint()

    try:
        async with (
            stdio_mod.anyio.create_task_group() as task_group,
            process,
        ):
            task_group.start_soon(stdout_reader)
            task_group.start_soon(stdin_writer)
            try:
                yield read_stream, write_stream
            finally:
                await _cleanup_stdio_process(process)
                await read_stream.aclose()
                await write_stream.aclose()
                await read_stream_writer.aclose()
                await write_stream_reader.aclose()
    finally:
        if callable(untrack_process):
            try:
                untrack_process(process)
            except Exception as error:
                logger.debug("Failed to untrack MCP stdio process: %s", error)


async def _cleanup_stdio_process(process: Any) -> None:
    try:
        stdin = getattr(process, "stdin", None)
        if stdin is not None:
            aclose = getattr(stdin, "aclose", None)
            if callable(aclose):
                try:
                    await _maybe_await(aclose())
                except Exception:
                    pass

        wait = getattr(process, "wait", None)
        if callable(wait):
            try:
                await asyncio.wait_for(_maybe_await(wait()), timeout=0.75)
                return
            except (asyncio.TimeoutError, TimeoutError):
                pass
            except ProcessLookupError:
                return
            except Exception:
                pass

        try:
            from mcp.client import stdio as stdio_mod

            await stdio_mod._terminate_process_tree(process)
            return
        except Exception:
            pass

        terminate = getattr(process, "terminate", None)
        if callable(terminate):
            try:
                terminate()
                if callable(wait):
                    await asyncio.wait_for(_maybe_await(wait()), timeout=0.75)
                    return
            except (asyncio.TimeoutError, TimeoutError):
                pass
            except ProcessLookupError:
                return
            except Exception:
                pass

        kill = getattr(process, "kill", None)
        if callable(kill):
            try:
                kill()
                if callable(wait):
                    await asyncio.wait_for(_maybe_await(wait()), timeout=0.75)
            except Exception:
                pass
    except Exception as error:
        logger.debug("Best-effort MCP stdio process cleanup failed: %s", error)


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


@contextmanager
def _mcp_stderr_log(server_name: str):
    log_dir = LOCAL_STATE_DIR / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "mcp-stderr.log"
    try:
        file = log_path.open("a", encoding="utf-8", errors="replace", buffering=1)
    except OSError:
        file = sys.stderr
    try:
        file.write(f"\n===== starting MCP server '{server_name}' =====\n")
        file.flush()
    except Exception:
        pass
    try:
        yield file
    finally:
        if file is not sys.stderr:
            file.close()


def read_mcp_stderr_log(*, max_chars: int = 60000) -> dict[str, Any]:
    log_path = LOCAL_STATE_DIR / "logs" / "mcp-stderr.log"
    max_chars = max(1000, int(max_chars or 60000))
    if not log_path.exists():
        return {"success": True, "path": str(log_path), "log": "", "truncated": False}
    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError as error:
        return {"success": False, "path": str(log_path), "log": "", "truncated": False, "error": sanitize_mcp_error(str(error))}
    truncated = len(text) > max_chars
    if truncated:
        text = text[-max_chars:]
    return {"success": True, "path": str(log_path), "log": text, "truncated": truncated}


def _latest_protocol_version() -> str:
    try:
        from mcp.types import LATEST_PROTOCOL_VERSION

        return str(LATEST_PROTOCOL_VERSION)
    except Exception:
        return _DEFAULT_PROTOCOL_VERSION


def _format_exception(error: BaseException) -> str:
    text = str(error).strip()
    if text:
        return text
    return repr(error)


__all__ = [
    "MCPManager",
    "MCPServerTask",
    "_normalize_mcp_input_schema",
    "mcp_tool_name",
    "probe_mcp_server",
    "read_mcp_stderr_log",
    "sanitize_mcp_error",
    "sanitize_mcp_name_component",
]
