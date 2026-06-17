"""说明：根据配置创建具体模型 provider。

作用：把 provider 名称、模型名和凭据解析成可调用的聊天模型或响应客户端。
"""

from __future__ import annotations

from typing import Any

from app_config import AppConfig
from model_providers.core.types import ModelProviderConfig, canonical_provider_name
from model_providers.providers.codex import create_codex_chat_model
from model_providers.providers.deepseek_provider import create_deepseek_chat_model
from model_providers.providers.openai_provider import create_openai_chat_model


def create_chat_model(config: AppConfig) -> Any:
    model_config = ModelProviderConfig.from_app_config(config)
    provider = canonical_provider_name(model_config.provider)

    if provider == "openai":
        return create_openai_chat_model(model_config)
    if provider == "codex":
        return create_codex_chat_model(model_config)
    if provider == "deepseek":
        return create_deepseek_chat_model(model_config)

    raise ValueError(f"Unsupported model provider: {model_config.provider}")
