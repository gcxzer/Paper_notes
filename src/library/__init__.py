"""说明：导出论文库读写和批注相关 API。

作用：让 UI 后端和工具层通过统一入口操作 notes.json、HTML note 和批注文件。
"""

from library.annotations import (
    read_annotations,
    write_annotations,
)
from library.store import (
    delete_note,
    import_pdf,
    import_pdf_from_url,
    read_library,
    rename_note,
    sanitize_library,
    update_note_summary,
    write_library,
)

__all__ = [
    "delete_note",
    "import_pdf",
    "import_pdf_from_url",
    "read_annotations",
    "read_library",
    "rename_note",
    "sanitize_library",
    "update_note_summary",
    "write_annotations",
    "write_library",
]
