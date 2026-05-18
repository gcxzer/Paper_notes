from __future__ import annotations

from dataclasses import dataclass, field


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

    def to_public_dict(self) -> dict[str, object]:
        return {
            "supportsTools": self.supports_tools,
            "supportsVision": self.supports_vision,
            "supportsImageGeneration": self.supports_image_generation,
            "supportsImageArtifactGeneration": self.supports_image_artifact_generation,
            "supportsWebSearch": self.supports_web_search,
            "supportsReasoningOff": self.supports_reasoning_off,
            "contextWindow": self.context_window,
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

    def capabilities_for_model(self, model: object = "") -> ModelCapabilities:
        model_name = str(model or "").strip()
        for option in self.models:
            if option.value == model_name and option.capabilities is not None:
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
