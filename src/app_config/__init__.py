"""说明：导出应用配置加载入口。

作用：让其他模块用统一方式读取全局配置、AI 设置和工具设置。
"""

from app_config.config import (
    AppConfig,
    load_app_config,
)

__all__ = [
    "AppConfig",
    "load_app_config",
]
