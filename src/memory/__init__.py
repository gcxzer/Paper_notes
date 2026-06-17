"""说明：导出全局记忆和当前论文记忆的公共函数。

作用：让 prompt 构建和设置页通过统一入口读取、写入 memory 文件。
"""

from memory.global_memory import build_memory_section
from memory.paper_memory import (
    PAPER_MEMORY_DIR,
    build_paper_memory_section,
    paper_memory_path,
    read_paper_memory_file,
    write_paper_memory_file,
)

__all__ = [
    "PAPER_MEMORY_DIR",
    "build_memory_section",
    "build_paper_memory_section",
    "paper_memory_path",
    "read_paper_memory_file",
    "write_paper_memory_file",
]
