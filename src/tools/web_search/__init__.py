"""说明：导出网页搜索工具。

作用：让默认工具集合可以注册 web_search 能力。
"""

from tools.web_search.tool import create_tools

__all__ = [
    "create_tools",
    "providers",
]
