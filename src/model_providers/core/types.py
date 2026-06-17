"""说明：定义模型 provider 的核心类型和协议。

作用：描述 provider 能力、模型请求参数和上层运行时需要依赖的接口。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app_config import AppConfig


PROVIDER_ALIASES = {
    "codex": "codex",
    "codex-oauth": "codex",
    "openai-codex": "codex",
    "deepseek": "deepseek",
    "openai": "openai",
}


@dataclass(frozen=True, slots=True)
class ModelProviderConfig:
    provider: str
    model: str
    options: dict[str, Any]

    @classmethod
    def from_app_config(cls, config: AppConfig) -> ModelProviderConfig:
        models = config.get("models")
        if not isinstance(models, dict):
            raise ValueError("Config section must be an object: models")

        default_model = _required_text(models.get("default"), "models.default")
        model_section = models.get(default_model)
        if not isinstance(model_section, dict):
            raise ValueError(f"Config section must be an object: models.{default_model}")

        provider = _required_text(model_section.get("provider"), f"models.{default_model}.provider")
        options = model_section.get("options", {})
        if not isinstance(options, dict):
            raise ValueError(f"Config section must be an object: models.{default_model}.options")

        return cls(
            provider=provider,
            model=_required_text(model_section.get("name"), f"models.{default_model}.name"),
            options=dict(options),
        )


def canonical_provider_name(provider: str) -> str | None:
    return PROVIDER_ALIASES.get(provider.strip().lower())


def model_kwargs(config: ModelProviderConfig, mapping: dict[str, str]) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"model": config.model}
    for config_key, constructor_key in mapping.items():
        if config_key in config.options:
            kwargs[constructor_key] = config.options[config_key]
    return kwargs


def _required_text(value: Any, key: str) -> str:
    text = str(value).strip() if value is not None else ""
    if not text:
        raise ValueError(f"Config value is required: {key}")
    return text
