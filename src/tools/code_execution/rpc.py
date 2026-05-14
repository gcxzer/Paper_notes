from __future__ import annotations

import json
import logging
import socket
import threading
from dataclasses import dataclass
from typing import Any

from tools.registry import ToolRegistry
from tools.types import ToolDefinition, ToolDispatchResult


logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RpcSnapshot:
    tool_calls_made: int


class CodeExecutionRpcServer:
    """Small loopback JSON-line RPC server for approved parent tool calls."""

    def __init__(
        self,
        *,
        registry: ToolRegistry,
        allowed_tools: set[str],
        token: str,
        max_tool_calls: int,
    ) -> None:
        self.registry = registry
        self.allowed_tools = set(allowed_tools)
        self.token = token
        self.max_tool_calls = max(0, int(max_tool_calls))
        self.host = "127.0.0.1"
        self.port = 0
        self._calls = 0
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._socket: socket.socket | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> "CodeExecutionRpcServer":
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((self.host, 0))
        server.listen()
        server.settimeout(0.2)
        self.port = int(server.getsockname()[1])
        self._socket = server
        self._thread = threading.Thread(target=self._serve, name="paper-notes-code-rpc", daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop_event.set()
        server = self._socket
        if server is not None:
            try:
                server.close()
            except OSError:
                pass
        thread = self._thread
        if thread is not None:
            thread.join(timeout=1)

    def snapshot(self) -> RpcSnapshot:
        with self._lock:
            calls = self._calls
        return RpcSnapshot(tool_calls_made=calls)

    def __enter__(self) -> "CodeExecutionRpcServer":
        return self.start()

    def __exit__(self, *_exc: object) -> None:
        self.stop()

    def _serve(self) -> None:
        server = self._socket
        if server is None:
            return
        while not self._stop_event.is_set():
            try:
                conn, _addr = server.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            thread = threading.Thread(target=self._handle_connection, args=(conn,), daemon=True)
            thread.start()

    def _handle_connection(self, conn: socket.socket) -> None:
        with conn:
            conn.settimeout(30)
            try:
                request = self._read_request(conn)
                response = self._dispatch_request(request)
            except Exception as error:
                logger.debug("execute_code RPC request failed: %s", error, exc_info=True)
                response = _rpc_error(f"RPC request failed: {type(error).__name__}: {error}", "rpc_failed")
            try:
                conn.sendall((json.dumps(response, ensure_ascii=False) + "\n").encode("utf-8"))
            except OSError:
                pass

    def _read_request(self, conn: socket.socket) -> dict[str, Any]:
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = conn.recv(65536)
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > 1024 * 1024:
                raise ValueError("RPC request is too large.")
            if b"\n" in chunk:
                break
        raw = b"".join(chunks).split(b"\n", 1)[0]
        if not raw:
            raise ValueError("RPC request is empty.")
        payload = json.loads(raw.decode("utf-8", errors="replace"))
        if not isinstance(payload, dict):
            raise ValueError("RPC request must be a JSON object.")
        return payload

    def _dispatch_request(self, request: dict[str, Any]) -> dict[str, Any]:
        if request.get("token") != self.token:
            return _rpc_error("Invalid RPC token.", "invalid_rpc_token")
        tool_name = str(request.get("tool") or "").strip()
        arguments = request.get("args")
        if not isinstance(arguments, dict):
            return _rpc_error("RPC tool args must be a JSON object.", "invalid_rpc_args", tool=tool_name)
        if tool_name not in self.allowed_tools:
            return _rpc_error("Tool is not available to execute_code.", "tool_not_allowed", tool=tool_name)
        definition = self.registry.get(tool_name)
        if not _is_safe_inner_tool(definition):
            return _rpc_error("Tool is not safe for execute_code RPC.", "unsafe_inner_tool", tool=tool_name)
        with self._lock:
            if self._calls >= self.max_tool_calls:
                return _rpc_error("execute_code inner tool call limit exceeded.", "tool_call_limit_exceeded", tool=tool_name)
            self._calls += 1
        result = self.registry.dispatch(tool_name, arguments)
        return _payload_from_dispatch_result(result)


def _is_safe_inner_tool(definition: ToolDefinition | None) -> bool:
    if definition is None:
        return False
    if definition.read_only and not definition.mutating and definition.risk == "read":
        return True
    return definition.name == "paper_notes_edit" and definition.mutating and definition.risk == "write"


def _payload_from_dispatch_result(result: ToolDispatchResult) -> dict[str, Any]:
    content = result.original_content or result.content
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        parsed = {"success": not result.is_error, "content": content}
    if not isinstance(parsed, dict):
        parsed = {"success": not result.is_error, "data": parsed}
    if result.is_error:
        parsed.setdefault("success", False)
    return parsed


def _rpc_error(message: str, code: str, *, tool: str = "") -> dict[str, Any]:
    payload: dict[str, Any] = {
        "success": False,
        "error": message,
        "code": code,
    }
    if tool:
        payload["tool"] = tool
    return payload


__all__ = ["CodeExecutionRpcServer", "RpcSnapshot"]
