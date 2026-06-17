"""说明：导出生成图片工具。

作用：让默认工具集合可以把 create_image_artifact 注册给 agent。
"""

from tools.generated_images.tool import create_tools

__all__ = [
    "create_tools",
]
