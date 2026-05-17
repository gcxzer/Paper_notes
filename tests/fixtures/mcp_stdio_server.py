from __future__ import annotations

import asyncio
import sys
import time

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations


app = FastMCP("paper-notes-stdio-fixture", log_level="ERROR")


@app.tool(annotations=ToolAnnotations(readOnlyHint=True))
async def echo(message: str = "ok") -> str:
    return f"echo:{message}"


@app.tool()
async def write_note(name: str = "note") -> str:
    return f"wrote:{name}"


@app.tool()
async def fail_with_secret() -> str:
    raise RuntimeError("stdio failed with Authorization: Bearer stdio-secret-token and OPENAI_API_KEY=sk-stdiosecret")


@app.tool()
async def slow_echo(message: str = "slow", delay: float = 2.0) -> str:
    await asyncio.sleep(delay)
    return message


def main() -> None:
    if "--crash" in sys.argv:
        print("crash Authorization: Bearer crashed-secret-token", file=sys.stderr, flush=True)
        raise SystemExit(42)
    if "--hang" in sys.argv:
        time.sleep(60)
    app.run(transport="stdio")


if __name__ == "__main__":
    main()
