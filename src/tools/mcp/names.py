"""说明：处理 MCP server 和工具名的规范化。

作用：保证来自不同 server 的工具名称安全、稳定且不会互相冲突。
"""

from __future__ import annotations

import re

__all__ = [
    "mcp_tool_name",
]

def sanitize_mcp_name_component(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_]", "_", str(value or "").strip())
    return cleaned or "server"


def mcp_tool_name(server_name: str, tool_name: str) -> str:
    return f"mcp_{sanitize_mcp_name_component(server_name)}_{sanitize_mcp_name_component(tool_name)}"
