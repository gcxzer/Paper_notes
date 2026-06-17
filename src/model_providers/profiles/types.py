"""说明：定义 provider profile 的数据结构。

作用：描述模型显示名、能力、上下文限制和图片/文件支持等配置字段。
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace


@dataclass(frozen=True, slots=True)
class ModelCapabilities:
    supports_tools: bool = True
    supports_vision: bool = False
    supports_image_generation: bool = False
    supports_image_artifact_generation: bool = False
    supports_web_search: bool = False
    supports_reasoning_off: bool = True
    context_window: int = 0
    image_input_mode: str = "unsupported"

    @property
    def context_length(self) -> int:
        return self.context_window

    def with_context_window(self, context_window: int) -> ModelCapabilities:
        return replace(self, context_window=max(0, int(context_window or 0)))

    def to_public_dict(self) -> dict[str, object]:
        return {
            "supportsTools": self.supports_tools,
            "supportsVision": self.supports_vision,
            "supportsImageGeneration": self.supports_image_generation,
            "supportsImageArtifactGeneration": self.supports_image_artifact_generation,
            "supportsWebSearch": self.supports_web_search,
            "supportsReasoningOff": self.supports_reasoning_off,
            "contextWindow": self.context_window,
            "contextLength": self.context_length,
            "imageInputMode": self.image_input_mode,
        }


@dataclass(frozen=True, slots=True)
class ModelOption:
    value: str
    label: str
    short_label: str = ""
    description: str = ""
    capabilities: ModelCapabilities | None = None

    def to_public_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "value": self.value,
            "label": self.label,
            "shortLabel": self.short_label or self.label,
            "description": self.description,
            "detail": self.description,
        }
        if self.capabilities is not None:
            payload["capabilities"] = self.capabilities.to_public_dict()
        return payload


@dataclass(frozen=True, slots=True)
class ModelProviderProfile:
    name: str
    display_name: str
    auth_type: str
    description: str = ""
    default_model: str = ""
    aliases: tuple[str, ...] = ()
    models: tuple[ModelOption, ...] = ()
    default_capabilities: ModelCapabilities = field(default_factory=ModelCapabilities)

    def option_for_model(self, model: object = "") -> ModelOption | None:
        model_name = str(model or "").strip().lower()
        if not model_name:
            model_name = self.default_model.strip().lower()
        for option in self.models:
            if option.value.strip().lower() == model_name:
                return option
        return None

    def capabilities_for_model(self, model: object = "") -> ModelCapabilities:
        option = self.option_for_model(model)
        if option is not None and option.capabilities is not None:
            return option.capabilities
        return self.default_capabilities

    def to_public_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "displayName": self.display_name,
            "authType": self.auth_type,
            "description": self.description,
            "defaultModel": self.default_model,
            "aliases": list(self.aliases),
            "capabilities": self.default_capabilities.to_public_dict(),
            "models": [model.to_public_dict() for model in self.models],
        }
