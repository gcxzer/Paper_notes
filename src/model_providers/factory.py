from __future__ import annotations

from model_providers.base import ModelProvider
from model_providers.codex import CodexModelProvider
from model_providers.openai import OpenAIModelProvider


def create_model_provider(name: str = "openai", **kwargs) -> ModelProvider:
    normalized = name.strip().lower().replace("_", "-")
    if normalized == "openai":
        return OpenAIModelProvider(**kwargs)
    if normalized in {"codex", "codex-oauth", "openai-codex"}:
        return CodexModelProvider(**kwargs)
    raise ValueError(f"Unsupported model provider: {name}")
