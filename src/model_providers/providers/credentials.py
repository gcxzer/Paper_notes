"""说明：解析各模型 provider 所需的 API key。

作用：从配置、环境变量和本地 secret 文件中找凭据，并返回可展示的来源状态。
"""

from __future__ import annotations

from typing import Any

from app_config.ai_settings import resolve_api_key_for_provider


def with_resolved_api_key(kwargs: dict[str, Any], provider: str) -> dict[str, Any]:
    if kwargs.get("api_key"):
        return kwargs
    key = resolve_api_key_for_provider(provider)
    if not key.value:
        return kwargs
    return {**kwargs, "api_key": key.value}
