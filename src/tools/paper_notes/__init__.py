"""说明：导出 Paper Notes 本地工具包。

作用：让 agent 默认工具集合可以注册论文检索、批注、笔记编辑和审阅工具。
"""

__all__ = [
    "create_tools",
]


def create_tools(*args, **kwargs):
    from tools.paper_notes.tool import create_tools as create_paper_notes_tools

    return create_paper_notes_tools(*args, **kwargs)
