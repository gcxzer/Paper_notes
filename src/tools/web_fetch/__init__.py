"""说明：导出网页抓取工具。

作用：让默认工具集合可以注册 web_fetch 能力。
"""

from tools.web_fetch.tool import create_tools

__all__ = [
    "create_tools",
    "tool",
]
