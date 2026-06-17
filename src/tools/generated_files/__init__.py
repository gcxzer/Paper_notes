"""说明：导出生成文件工具。

作用：让默认工具集合可以把 create_file_artifact 注册给 agent。
"""

from tools.generated_files.tool import create_tools

__all__ = [
    "create_tools",
]
