from __future__ import annotations

import os
import secrets
import signal
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Callable

from tools.code_execution.rpc import CodeExecutionRpcServer
from tools.code_execution.stubs import build_stub_source
from tools.registry import ToolRegistry


TIMEOUT_SECONDS = 120.0
MAX_TOOL_CALLS = 25
MAX_STDOUT_BYTES = 50 * 1024
MAX_STDERR_BYTES = 10 * 1024
MAX_CODE_BYTES = 50 * 1024

_SECRET_ENV_MARKERS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL", "PASSWD", "AUTH")


def run_python_code(
    code: str,
    *,
    registry: ToolRegistry,
    allowed_tools: set[str],
    snapshot_manager: Any = None,
    session_id: str = "",
    cancel_check: Callable[[], bool] | None = None,
    timeout_seconds: float = TIMEOUT_SECONDS,
    max_tool_calls: int = MAX_TOOL_CALLS,
) -> dict[str, Any]:
    started = time.monotonic()
    runtime_token = ""
    with tempfile.TemporaryDirectory(prefix="paper_notes_code_") as tmp:
        tmp_path = Path(tmp)
        fake_home = tmp_path / "home"
        fake_home.mkdir(parents=True, exist_ok=True)
        script_path = tmp_path / "main.py"
        stub_path = tmp_path / "paper_notes_tools.py"
        script_path.write_text(code, encoding="utf-8")
        stub_path.write_text(build_stub_source(sorted(allowed_tools)), encoding="utf-8")

        token = secrets.token_urlsafe(32)
        runtime_token = token
        with CodeExecutionRpcServer(
            registry=registry,
            allowed_tools=set(allowed_tools),
            token=token,
            max_tool_calls=max_tool_calls,
            snapshot_manager=snapshot_manager,
            session_id=session_id,
        ) as rpc_server:
            env = _child_environment(
                fake_home=fake_home,
                rpc_host=rpc_server.host,
                rpc_port=rpc_server.port,
                rpc_token=token,
            )
            process = subprocess.Popen(
                [sys.executable, str(script_path)],
                cwd=str(tmp_path),
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=(os.name != "nt"),
            )
            stdout = _LimitedOutputBuffer(MAX_STDOUT_BYTES)
            stderr = _LimitedOutputBuffer(MAX_STDERR_BYTES)
            stdout_thread = _reader_thread(process.stdout, stdout)
            stderr_thread = _reader_thread(process.stderr, stderr)
            status = _wait_for_process(
                process,
                timeout_seconds=timeout_seconds,
                cancel_check=cancel_check,
            )
            stdout_thread.join(timeout=1)
            stderr_thread.join(timeout=1)
            if status == "success" and process.returncode != 0:
                status = "error"
            snapshot = rpc_server.snapshot()

    duration = round(time.monotonic() - started, 3)
    output_text = _redact_runtime_token(stdout.text(), runtime_token)
    error_text = _redact_runtime_token(stderr.text(), runtime_token)
    if status == "timeout" and not error_text:
        error_text = f"Execution timed out after {int(timeout_seconds)} seconds."
    elif status == "cancelled" and not error_text:
        error_text = "Execution was cancelled."
    elif status == "error" and not error_text:
        error_text = f"Process exited with status {process.returncode}."
    return {
        "success": status == "success",
        "status": status,
        "output": output_text,
        "error": error_text,
        "tool_calls_made": snapshot.tool_calls_made,
        "snapshots": list(snapshot.snapshots),
        "snapshot": snapshot.snapshots[-1] if snapshot.snapshots else None,
        "duration_seconds": duration,
    }


class _LimitedOutputBuffer:
    def __init__(self, max_bytes: int) -> None:
        self.max_bytes = max(200, int(max_bytes))
        self._head_limit = max(100, self.max_bytes // 2)
        self._tail_limit = max(100, self.max_bytes - self._head_limit)
        self._head = bytearray()
        self._tail = bytearray()
        self._total = 0
        self._lock = threading.Lock()

    def append(self, data: bytes) -> None:
        if not data:
            return
        with self._lock:
            self._total += len(data)
            if len(self._head) < self._head_limit:
                take = min(len(data), self._head_limit - len(self._head))
                self._head.extend(data[:take])
                data = data[take:]
            if data:
                self._tail.extend(data)
                if len(self._tail) > self._tail_limit:
                    del self._tail[: len(self._tail) - self._tail_limit]

    def text(self) -> str:
        with self._lock:
            total = self._total
            head = bytes(self._head)
            tail = bytes(self._tail)
        if total <= self.max_bytes:
            raw = head + tail
            return raw.decode("utf-8", errors="replace")
        omitted = total - len(head) - len(tail)
        marker = f"\n...[truncated {omitted} bytes]...\n".encode("utf-8")
        return (head + marker + tail).decode("utf-8", errors="replace")


def _reader_thread(stream: Any, buffer: _LimitedOutputBuffer) -> threading.Thread:
    def _read() -> None:
        if stream is None:
            return
        try:
            while True:
                chunk = stream.read(4096)
                if not chunk:
                    break
                buffer.append(chunk)
        except Exception:
            return

    thread = threading.Thread(target=_read, daemon=True)
    thread.start()
    return thread


def _wait_for_process(
    process: subprocess.Popen[bytes],
    *,
    timeout_seconds: float,
    cancel_check: Callable[[], bool] | None,
) -> str:
    deadline = time.monotonic() + max(0.1, float(timeout_seconds))
    while process.poll() is None:
        if cancel_check is not None and cancel_check():
            _terminate_process_tree(process)
            return "cancelled"
        if time.monotonic() >= deadline:
            _terminate_process_tree(process)
            return "timeout"
        time.sleep(0.05)
    return "success"


def _terminate_process_tree(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    try:
        if os.name != "nt":
            os.killpg(process.pid, signal.SIGTERM)
        else:
            process.terminate()
    except OSError:
        pass
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        try:
            if os.name != "nt":
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
        except OSError:
            pass
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            pass


def _child_environment(
    *,
    fake_home: Path,
    rpc_host: str,
    rpc_port: int,
    rpc_token: str,
) -> dict[str, str]:
    env: dict[str, str] = {}
    for key, value in os.environ.items():
        upper = key.upper()
        if any(marker in upper for marker in _SECRET_ENV_MARKERS):
            continue
        env[key] = value
    env.update({
        "HOME": str(fake_home),
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
        "PAPER_NOTES_RPC_HOST": rpc_host,
        "PAPER_NOTES_RPC_PORT": str(rpc_port),
        "PAPER_NOTES_RPC_TOKEN": rpc_token,
    })
    return env


def _redact_runtime_token(text: str, token: str) -> str:
    if not token:
        return text
    return text.replace(token, "[redacted_rpc_token]")


__all__ = [
    "MAX_CODE_BYTES",
    "MAX_STDERR_BYTES",
    "MAX_STDOUT_BYTES",
    "MAX_TOOL_CALLS",
    "TIMEOUT_SECONDS",
    "run_python_code",
]
