from __future__ import annotations

import asyncio
import inspect
import logging
import os
import shutil
import sys
from contextlib import asynccontextmanager, contextmanager
from typing import Any
from urllib.parse import urlsplit

from app_config.secrets import LOCAL_STATE_DIR
from tools.mcp.security import sanitize_mcp_error


logger = logging.getLogger(__name__)


_CROSS_ORIGIN_STRIPPED_HEADER_NAMES = frozenset({
    "authorization",
    "proxy-authorization",
    "cookie",
    "x-api-key",
    "api-key",
    "openai-api-key",
    "x-auth-token",
    "x-access-token",
    "mcp-session-id",
})


def mcp_http_request_hook(initial_url: str, configured_headers: dict[str, Any]):
    initial_origin = _http_origin(initial_url)
    stripped_names = _configured_header_names(configured_headers) | set(_CROSS_ORIGIN_STRIPPED_HEADER_NAMES)

    async def _strip_cross_origin_headers(request: Any) -> None:
        if _http_origin(request.url) == initial_origin:
            return
        for name in stripped_names:
            _drop_request_header(request.headers, name)

    return _strip_cross_origin_headers


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


_SAFE_ENV_KEYS = frozenset({"PATH", "HOME", "USER", "LANG", "LC_ALL", "TERM", "SHELL", "TMPDIR"})
_DEFAULT_PROTOCOL_VERSION = "2025-03-26"


def resolve_stdio_env(user_env: Any) -> dict[str, str]:
    env = {
        key: value
        for key, value in os.environ.items()
        if key in _SAFE_ENV_KEYS or key.startswith("XDG_")
    }
    if isinstance(user_env, dict):
        env.update({str(key): str(value) for key, value in user_env.items()})
    return env


def resolve_stdio_command(command: str, env: dict[str, str]) -> tuple[str, dict[str, str]]:
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
async def tracked_stdio_client(
    server: Any,
    errlog: Any = sys.stderr,
    *,
    track_process: Any = None,
    untrack_process: Any = None,
):
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
                await cleanup_stdio_process(process)
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


async def cleanup_stdio_process(process: Any) -> None:
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
def mcp_stderr_log(server_name: str):
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
        file_size = log_path.stat().st_size
        read_bytes = max_chars * 4
        with log_path.open("rb") as file:
            if file_size > read_bytes:
                file.seek(-read_bytes, os.SEEK_END)
            text = file.read().decode("utf-8", errors="replace")
    except OSError as error:
        return {
            "success": False,
            "path": str(log_path),
            "log": "",
            "truncated": False,
            "error": sanitize_mcp_error(str(error)),
        }
    truncated = file_size > read_bytes or len(text) > max_chars
    if len(text) > max_chars:
        text = text[-max_chars:]
    return {"success": True, "path": str(log_path), "log": text, "truncated": truncated}


def latest_protocol_version() -> str:
    try:
        from mcp.types import LATEST_PROTOCOL_VERSION

        return str(LATEST_PROTOCOL_VERSION)
    except Exception:
        return _DEFAULT_PROTOCOL_VERSION


__all__ = [
    "cleanup_stdio_process",
    "latest_protocol_version",
    "mcp_http_request_hook",
    "mcp_stderr_log",
    "read_mcp_stderr_log",
    "resolve_stdio_command",
    "resolve_stdio_env",
    "tracked_stdio_client",
]
