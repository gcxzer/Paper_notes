"""说明：导出媒体存储服务的公共入口。

作用：让聊天附件、生成文件和工具输出统一使用 MediaStore 保存和读取 artifact。
"""

from media.store import (
    MediaStore,
    MediaStoreError,
)

__all__ = [
    "MediaStore",
    "MediaStoreError",
]
