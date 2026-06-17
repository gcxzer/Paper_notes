from __future__ import annotations

from typing import Any

from app_infra.formatting import normalize_text

__all__ = [
    "FILE_GENERATION_KEYS",
    "FILE_GENERATION_MIME_TYPES",
    "GENERATED_TEXT_MIME_KINDS",
    "IMAGE_GENERATION_KEYS",
    "file_generation_mime_type",
    "file_generation_request_options",
    "generated_text_artifact_kind",
    "generation_options",
    "generation_requested",
    "image_generation_provider_options",
    "image_generation_request_options",
    "request_model_options",
    "truthy_option",
]

IMAGE_GENERATION_KEYS = ("_paper_notes_image_generation", "imageGeneration")
FILE_GENERATION_KEYS = ("_paper_notes_file_generation", "fileGeneration")
REQUEST_MODEL_OPTION_KEYS = ("requestOptions",)
IMAGE_GENERATION_CONFIG_KEYS = ("size", "quality", "format", "output_format", "outputFormat", "model")
FILE_GENERATION_FORMATS = {
    "markdown": {"mime_type": "text/markdown", "kind": "text", "extension": ".md"},
    "text": {"mime_type": "text/plain", "kind": "text", "extension": ".txt"},
    "json": {"mime_type": "application/json", "kind": "json", "extension": ".json"},
    "csv": {"mime_type": "text/csv", "kind": "csv", "extension": ".csv"},
    "html": {"mime_type": "text/html", "kind": "html", "extension": ".html"},
}
FILE_GENERATION_MIME_TYPES = {
    file_format: config["mime_type"]
    for file_format, config in FILE_GENERATION_FORMATS.items()
}
GENERATED_TEXT_MIME_KINDS = {
    config["mime_type"]: (config["kind"], config["extension"])
    for config in FILE_GENERATION_FORMATS.values()
}


def request_model_options(body: dict[str, Any]) -> dict[str, Any]:
    options: dict[str, Any] = {}
    for key in REQUEST_MODEL_OPTION_KEYS:
        value = body.get(key)
        if isinstance(value, dict):
            options.update(value)
    return options


def generation_options(
    options: dict[str, Any] | None,
    keys: tuple[str, ...],
    *,
    require_enabled: bool = False,
    accept_config_keys: tuple[str, ...] = (),
) -> dict[str, Any]:
    if not isinstance(options, dict):
        return {}
    for key in keys:
        value = options.get(key)
        if not isinstance(value, dict):
            continue
        if require_enabled:
            return dict(value) if value.get("enabled") is True else {}
        if value.get("enabled") is False:
            return {}
        if not accept_config_keys or value.get("enabled") is True or any(name in value for name in accept_config_keys):
            return dict(value)
    return {}


def generation_requested(options: dict[str, Any] | None, keys: tuple[str, ...]) -> bool:
    return bool(generation_options(options, keys, require_enabled=True))


def image_generation_request_options(body: dict[str, Any]) -> dict[str, Any]:
    config = generation_options(body, IMAGE_GENERATION_KEYS[1:], require_enabled=True)
    if not config:
        return {}
    config.setdefault("format", "png")
    return config


def file_generation_request_options(body: dict[str, Any]) -> dict[str, Any]:
    config = generation_options(body, FILE_GENERATION_KEYS[1:], require_enabled=True)
    if not config:
        return {}
    file_format = normalize_file_generation_format(config.get("format"))
    return {
        **config,
        "enabled": True,
        "format": file_format,
        "mime_type": file_generation_mime_type(file_format),
    }


def image_generation_provider_options(options: dict[str, Any] | None) -> dict[str, Any]:
    return generation_options(
        options,
        IMAGE_GENERATION_KEYS,
        accept_config_keys=IMAGE_GENERATION_CONFIG_KEYS,
    )


def normalize_file_generation_format(value: Any) -> str:
    file_format = normalize_text(value).lower() or "markdown"
    return file_format if file_format in FILE_GENERATION_MIME_TYPES else "markdown"


def file_generation_mime_type(file_format: str) -> str:
    return FILE_GENERATION_MIME_TYPES.get(normalize_file_generation_format(file_format), "text/markdown")


def generated_text_artifact_kind(mime_type: Any) -> tuple[str, str]:
    return GENERATED_TEXT_MIME_KINDS.get(normalize_text(mime_type).lower(), ("", ""))


def truthy_option(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "enabled"}
    return False

