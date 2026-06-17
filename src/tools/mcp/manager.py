"""说明：管理 MCP server 生命周期和工具发现。

作用：负责启动/连接 server、缓存工具定义、执行调用并把结果接入 agent。
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import inspect
import logging
import threading
import time
from contextlib import suppress
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from langchain_core.tools import StructuredTool

from tools.mcp.content import (
    attach_mcp_media_payload as _attach_mcp_media_payload,
    attach_mcp_security_payload as _attach_mcp_security_payload,
    tool_result_payload as _tool_result_payload,
)
from tools.mcp.errors import (
    is_session_expired_error as _is_session_expired_error,
    mcp_error_payload as _mcp_error_payload,
)
from tools.mcp.manifest import TOOLSET
from tools.mcp.names import mcp_tool_name
from tools.mcp.schema import normalize_mcp_input_schema as _normalize_mcp_input_schema
from tools.mcp.security import (
    collect_security_warnings as _collect_security_warnings,
    mcp_security_warnings as _mcp_security_warnings,
    sanitize_mcp_description as _sanitize_mcp_description,
    sanitize_mcp_error,
    sanitize_mcp_schema_descriptions as _sanitize_mcp_schema_descriptions,
)
from tools.mcp.settings import mcp_runtime_config, normalize_mcp_server_config, read_mcp_settings
from tools.mcp.summaries import (
    mcp_tool_annotations as _mcp_tool_annotations,
    mcp_tool_output_schema as _mcp_tool_output_schema,
    mcp_tool_read_only as _mcp_tool_read_only,
    mcp_tool_risk as _mcp_tool_risk,
    mcp_utility_metadata as _mcp_utility_metadata,
    prompt_message_summary as _prompt_message_summary,
    prompt_summary as _prompt_summary,
    resource_content_summary as _resource_content_summary,
    resource_summary as _resource_summary,
    server_status_details as _server_status_details,
    server_supports_capability as _server_supports_capability,
    server_tool_filter_allows as _server_tool_filter_allows,
    server_tool_summaries as _server_tool_summaries,
    tool_summary_from_definition as _tool_summary_from_definition,
)
from tools.mcp.transport import (
    cleanup_stdio_process as _cleanup_stdio_process,
    latest_protocol_version as _latest_protocol_version,
    mcp_http_request_hook as _mcp_http_request_hook,
    mcp_stderr_log as _mcp_stderr_log,
    read_mcp_stderr_log,
    resolve_stdio_command as _resolve_stdio_command,
    resolve_stdio_env as _resolve_stdio_env,
    tracked_stdio_client as _tracked_stdio_client,
)
from tools.mcp.utils import format_exception as _format_exception

__all__ = [
    "MCPManager",
    "probe_mcp_server",
    "read_mcp_stderr_log",
]

logger = logging.getLogger(__name__)

_KEEPALIVE_INTERVAL_SECONDS = 180
_KEEPALIVE_TIMEOUT_SECONDS = 30
_MAX_INITIAL_CONNECT_RETRIES = 3
_MAX_RECONNECT_RETRIES = 5
_MAX_BACKOFF_SECONDS = 16
_CIRCUIT_OPEN_COOLDOWN_SECONDS = 60
_mcp_loop: asyncio.AbstractEventLoop | None = None
_mcp_thread: threading.Thread | None = None
_mcp_loop_lock = threading.Lock()


@dataclass(slots=True)
class MCPToolRecord:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: Any
    read_only: bool
    mutating: bool
    risk: str = "read"
    output_schema: dict[str, Any] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_langchain_tool(self) -> StructuredTool:
        def _run(**kwargs: Any) -> Any:
            return self.handler(dict(kwargs))

        metadata = {
            **self.metadata,
            "toolset": TOOLSET,
            "readOnly": self.read_only,
            "mutating": self.mutating,
            "risk": self.risk,
        }
        if self.output_schema is not None:
            metadata["outputSchema"] = self.output_schema
        return StructuredTool(
            name=self.name,
            description=self.description,
            args_schema=self.parameters,
            func=_run,
            metadata=metadata,
        )


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


def _client_session_supports_message_handler(client_session_cls: Any) -> bool:
    try:
        return "message_handler" in inspect.signature(client_session_cls).parameters
    except (TypeError, ValueError):
        return False


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
        self._refresh_requested = False
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
            return await self._request_with_cancellation(
                lambda: self.session.call_tool(tool_name, arguments=arguments or {}),
                timeout=timeout,
                description=f"tools/call {tool_name}",
            )

    async def list_resources(self, *, timeout: float) -> Any:
        if self.session is None:
            raise RuntimeError(f"MCP server '{self.name}' is not connected")
        async with self._rpc_lock:
            return await self._request_with_cancellation(
                lambda: self.session.list_resources(),
                timeout=timeout,
                description="resources/list",
            )

    async def read_resource(self, uri: str, *, timeout: float) -> Any:
        if self.session is None:
            raise RuntimeError(f"MCP server '{self.name}' is not connected")
        async with self._rpc_lock:
            return await self._request_with_cancellation(
                lambda: self.session.read_resource(uri),
                timeout=timeout,
                description=f"resources/read {uri}",
            )

    async def list_prompts(self, *, timeout: float) -> Any:
        if self.session is None:
            raise RuntimeError(f"MCP server '{self.name}' is not connected")
        async with self._rpc_lock:
            return await self._request_with_cancellation(
                lambda: self.session.list_prompts(),
                timeout=timeout,
                description="prompts/list",
            )

    async def get_prompt(self, name: str, arguments: dict[str, Any], *, timeout: float) -> Any:
        if self.session is None:
            raise RuntimeError(f"MCP server '{self.name}' is not connected")
        async with self._rpc_lock:
            return await self._request_with_cancellation(
                lambda: self.session.get_prompt(name, arguments=arguments or {}),
                timeout=timeout,
                description=f"prompts/get {name}",
            )

    async def _request_with_cancellation(self, call_factory: Any, *, timeout: float, description: str) -> Any:
        request_id = getattr(self.session, "_request_id", None)
        task = asyncio.create_task(call_factory())
        done, _pending = await asyncio.wait({task}, timeout=max(0.0, timeout))
        if done:
            return task.result()
        reason = f"MCP {description} timed out after {timeout:g}s"
        await self._send_cancelled_notification(request_id, reason)
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        raise TimeoutError(reason)

    async def _send_cancelled_notification(self, request_id: Any, reason: str) -> None:
        if self.session is None:
            return
        try:
            from mcp.types import CancelledNotification, CancelledNotificationParams

            notification = CancelledNotification(
                params=CancelledNotificationParams(requestId=request_id, reason=reason)
            )
            await self.session.send_notification(notification, related_request_id=request_id)
        except Exception as error:
            logger.debug("Failed to send MCP cancellation notification for '%s': %s", self.name, error)

    async def reconnect_and_wait(self, *, timeout: float = 15) -> bool:
        previous_session = self.session
        self.request_reconnect(reset_failures=False)
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            if self._shutdown.is_set():
                return False
            if self.session is not None and self.session is not previous_session:
                return True
            await asyncio.sleep(0.1)
        return self.session is not None and self.session is not previous_session

    def request_reconnect(self, *, reset_failures: bool = True) -> None:
        if reset_failures:
            self.failure_count = 0
            self.next_retry_at = 0.0
        self.state = "reconnecting"
        self._reconnect.set()

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
        if self._pending_refresh_tasks:
            self._refresh_requested = True
            return next(iter(self._pending_refresh_tasks))
        task = asyncio.create_task(self._refresh_tools_task())
        self._pending_refresh_tasks.add(task)
        task.add_done_callback(self._pending_refresh_tasks.discard)
        return task

    async def _refresh_tools_task(self) -> None:
        try:
            while True:
                self._refresh_requested = False
                await self.refresh_tools()
                if not self._refresh_requested:
                    return
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
    def __init__(self, *, media_store: Any = None) -> None:
        self.media_store = media_store
        self._servers: dict[str, MCPServerTask] = {}
        self._statuses: dict[str, dict[str, Any]] = {}
        self._tools: dict[str, StructuredTool] = {}
        self._lock = threading.RLock()

    def discover_from_settings(self) -> list[str]:
        settings = read_mcp_settings()
        return self.register_servers(settings.get("servers") or [])

    def register_servers(self, servers: list[dict[str, Any]]) -> list[str]:
        enabled_servers = [server for server in servers if server.get("enabled") is not False]
        enabled_ids = {str(server.get("id") or "").strip() for server in enabled_servers if str(server.get("id") or "").strip()}

        async def _register_all() -> list[str]:
            with self._lock:
                replaced_servers = list(self._servers.values())
                registered_names = [name for server in replaced_servers for name in server.registered_tool_names]
                self._servers.clear()
                for name in registered_names:
                    self._tools.pop(name, None)
                for server_id in list(self._statuses):
                    if server_id not in enabled_ids:
                        self._statuses.pop(server_id, None)
            if replaced_servers:
                await asyncio.gather(*(server.shutdown() for server in replaced_servers), return_exceptions=True)
            if not enabled_servers:
                return []
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

    def tools(self) -> list[StructuredTool]:
        with self._lock:
            return [self._tools[name] for name in sorted(self._tools)]

    def reconnect_server(self, server_id: str) -> dict[str, Any]:
        return self._request_server_reconnect(server_id)

    def reset_server_circuit(self, server_id: str) -> dict[str, Any]:
        return self._request_server_reconnect(server_id)

    def _request_server_reconnect(self, server_id: str) -> dict[str, Any]:
        server_id = str(server_id or "").strip()
        if not server_id:
            raise ValueError("MCP server id is required.")

        async def _request_reconnect() -> dict[str, Any]:
            with self._lock:
                server = self._servers.get(server_id)
            if server is None:
                return {"success": False, "serverId": server_id, "error": "MCP server is not running.", "code": "mcp_server_not_running"}
            server.request_reconnect(reset_failures=True)
            status = _server_status_details(server)
            with self._lock:
                current = self._statuses.setdefault(server.id, {})
                current.update(status)
            return {"success": True, "serverId": server.id, "status": status}

        return _run_on_mcp_loop(_request_reconnect(), timeout=5)

    def shutdown(self) -> None:
        with self._lock:
            servers = list(self._servers.values())
            self._servers.clear()
            self._statuses.clear()
            self._tools.clear()

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
        definitions: list[MCPToolRecord] = []
        seen: set[str] = set()
        for mcp_tool in server.tools:
            original_name = str(getattr(mcp_tool, "name", "") or "").strip()
            if not original_name:
                continue
            if not _server_tool_filter_allows(server, original_name):
                continue
            tool_name = mcp_tool_name(server.id, original_name)
            if tool_name in seen:
                logger.warning("MCP tool collision skipped: %s", tool_name)
                continue
            seen.add(tool_name)
            definitions.append(self._tool_definition_for_mcp_tool(server, mcp_tool, original_name, tool_name))

        for definition in self._utility_tool_definitions(server):
            if definition.name in seen:
                logger.warning("MCP utility collision skipped: %s", definition.name)
                continue
            seen.add(definition.name)
            definitions.append(definition)

        registered = [definition.name for definition in definitions]
        previous = set(server.registered_tool_names)
        with self._lock:
            for definition in definitions:
                self._tools[definition.name] = definition.to_langchain_tool()
            for stale_name in sorted(previous - set(registered)):
                self._tools.pop(stale_name, None)

        server.registered_tool_names = list(registered)
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
    ) -> MCPToolRecord:
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
        return MCPToolRecord(
            name=tool_name,
            description=description,
            parameters=parameters,
            handler=self._make_tool_handler(server.id, original_name, float(server.server.get("timeoutSeconds") or 120)),
            read_only=read_only,
            mutating=not read_only,
            risk=risk,
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

    def _utility_tool_definitions(self, server: MCPServerTask) -> list[MCPToolRecord]:
        timeout = float(server.server.get("timeoutSeconds") or 120)
        definitions: list[MCPToolRecord] = []

        def _add_utility(utility_name: str, description: str, parameters: dict[str, Any], handler: Any) -> None:
            if not _server_tool_filter_allows(server, utility_name):
                return
            definitions.append(MCPToolRecord(
                name=mcp_tool_name(server.id, utility_name),
                description=description,
                parameters=parameters,
                handler=handler,
                read_only=True,
                mutating=False,
                risk="read",
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
                lambda server: server.list_resources(timeout=timeout),
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
                lambda server: server.read_resource(uri, timeout=timeout),
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
                lambda server: server.list_prompts(timeout=timeout),
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
                lambda server: server.get_prompt(name, prompt_arguments, timeout=timeout),
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
                server.request_reconnect(reset_failures=False)
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
            payload = _mcp_error_payload(error_text, server_id=server_id, default_code="mcp_call_failed")
            if payload.get("code") != "mcp_rate_limited":
                self._mark_server_disconnected(server_id, error_text)
            return False, payload

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
