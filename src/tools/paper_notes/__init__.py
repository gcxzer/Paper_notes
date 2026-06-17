__all__ = [
    "create_tools",
]


def create_tools(*args, **kwargs):
    from tools.paper_notes.tool import create_tools as create_paper_notes_tools

    return create_paper_notes_tools(*args, **kwargs)
