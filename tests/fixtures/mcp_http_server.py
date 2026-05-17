from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

import uvicorn
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations


def build_app(header_file: Path | None = None):
    app = FastMCP(
        "paper-notes-http-fixture",
        host="127.0.0.1",
        port=0,
        streamable_http_path="/mcp",
        log_level="ERROR",
    )

    @app.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def echo(message: str = "ok") -> str:
        return f"http:{message}"

    @app.tool()
    async def write_note(name: str = "note") -> str:
        return f"http-wrote:{name}"

    @app.tool()
    async def fail_with_secret() -> str:
        raise RuntimeError("http failed with Authorization: Bearer http-secret-token and X-API-Key=secret-http")

    @app.tool()
    async def slow_echo(message: str = "slow", delay: float = 2.0) -> str:
        await asyncio.sleep(delay)
        return message

    @app.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def header_seen(name: str = "x-fixture-token") -> str:
        if header_file is None or not header_file.exists():
            return "missing"
        headers = header_file.read_text(encoding="utf-8")
        return "present" if name.lower() in headers.lower() else "missing"

    starlette_app = app.streamable_http_app()
    if header_file is not None:
        starlette_app.add_middleware(HeaderCaptureMiddleware, header_file=header_file)
    return starlette_app


class HeaderCaptureMiddleware:
    def __init__(self, app, *, header_file: Path) -> None:
        self.app = app
        self.header_file = header_file

    async def __call__(self, scope, receive, send) -> None:
        if scope.get("type") == "http":
            lines = [
                f"{key.decode('latin1')}: {value.decode('latin1')}"
                for key, value in scope.get("headers", [])
            ]
            self.header_file.write_text("\n".join(lines), encoding="utf-8")
        await self.app(scope, receive, send)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--header-file", default="")
    args = parser.parse_args()
    header_file = Path(args.header_file) if args.header_file else None
    uvicorn.run(
        build_app(header_file),
        host="127.0.0.1",
        port=args.port,
        log_level="error",
    )


if __name__ == "__main__":
    main()
