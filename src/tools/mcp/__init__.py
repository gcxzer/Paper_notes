"""说明：导出 MCP 工具管理入口。

作用：让 agent runtime 可以按配置发现、连接和调用外部 MCP server。
"""

from tools.mcp.manager import (
    MCPManager,
    probe_mcp_server,
    read_mcp_stderr_log,
)
from tools.mcp.settings import (
    mcp_enabled,
    normalize_mcp_server_config,
    normalize_mcp_settings_update,
    public_mcp_settings,
    read_mcp_settings,
    write_mcp_settings,
)

__all__ = [
    "MCPManager",
    "mcp_enabled",
    "normalize_mcp_server_config",
    "normalize_mcp_settings_update",
    "probe_mcp_server",
    "public_mcp_settings",
    "read_mcp_stderr_log",
    "read_mcp_settings",
    "write_mcp_settings",
]
