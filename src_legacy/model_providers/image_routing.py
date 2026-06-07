from __future__ import annotations

from dataclasses import dataclass

from model_providers.profiles import capabilities_for_provider_model, normalize_provider_profile_name


# Inspired by Hermes Agent's image_routing.py: decide how user-attached images
# enter the active model once per provider/model instead of sprinkling checks
# through each caller.


@dataclass(frozen=True, slots=True)
class ImageInputRoute:
    provider: str
    model: str
    mode: str
    reason: str = ""

    @property
    def native(self) -> bool:
        return self.mode == "native"


def decide_image_input_route(provider: object, model: object = "") -> ImageInputRoute:
    provider_name = normalize_provider_profile_name(provider) or str(provider or "").strip().lower()
    model_name = str(model or "").strip()
    capabilities = capabilities_for_provider_model(provider_name, model_name)
    if capabilities.supports_vision and capabilities.image_input_mode == "native":
        return ImageInputRoute(provider=provider_name, model=model_name, mode="native")
    return ImageInputRoute(
        provider=provider_name,
        model=model_name,
        mode="unsupported",
        reason=f"{_provider_label(provider_name)} does not support native image input in Paper Notes yet.",
    )


def supports_image_generation(provider: object, model: object = "") -> bool:
    provider_name = normalize_provider_profile_name(provider) or str(provider or "").strip().lower()
    return capabilities_for_provider_model(provider_name, model).supports_image_generation


def image_input_unsupported_message(route: ImageInputRoute) -> str:
    provider_label = _provider_label(route.provider)
    model_label = f" ({route.model})" if route.model else ""
    return (
        f"{provider_label}{model_label} is not configured for image input in Paper Notes. "
        "Switch to a model/provider that supports image input, or remove image attachments and try again."
    )


def image_generation_unsupported_message(provider: object, model: object = "") -> str:
    provider_name = normalize_provider_profile_name(provider) or str(provider or "").strip().lower()
    model_name = str(model or "").strip()
    model_label = f" ({model_name})" if model_name else ""
    return (
        f"{_provider_label(provider_name)}{model_label} is not configured for image generation in Paper Notes. "
        "Switch to the OpenAI API key provider or Codex OAuth provider to generate or edit images."
    )


def _provider_label(provider: str) -> str:
    return {
        "openai": "OpenAI API key",
        "codex-oauth": "Codex OAuth",
    }.get(provider, provider or "The selected provider")
