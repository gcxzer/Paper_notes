from __future__ import annotations

import copy
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel

from app_config import AppConfig
from app_infra.artifact_generation import (
    FILE_GENERATION_KEYS,
    IMAGE_GENERATION_KEYS,
    generation_options,
    generation_requested,
    truthy_option,
)
from model_providers import ModelProviderConfig
from tools import AgentTool, ToolContext, tool_name


def model_config_for_request(
    app_config: AppConfig,
    request: Any,
    *,
    session: Any | None,
    media_store: Any | None = None,
) -> AppConfig:
    provider = str(getattr(request, "provider", "") or (session.metadata.provider if session is not None else "") or "")
    model = str(getattr(request, "model", "") or (session.metadata.model if session is not None else "") or "")
    if not provider and not model:
        return app_config

    base_data = copy.deepcopy(app_config.data)
    base_models = base_data.get("models") if isinstance(base_data.get("models"), dict) else {}
    default_key = str(base_models.get("default") or "main")
    default_section = base_models.get(default_key) if isinstance(base_models.get(default_key), dict) else {}
    resolved_provider = provider or str(default_section.get("provider") or "")
    resolved_model = model or str(default_section.get("name") or "")
    options = dict(default_section.get("options") if isinstance(default_section.get("options"), dict) else {})
    request_options = getattr(request, "model_options", None)
    if isinstance(request_options, dict):
        options.update(request_options)
    if image_generation_requested(options):
        options.setdefault("_paper_notes_provider", resolved_provider)
        if session is not None:
            options["_paper_notes_session_id"] = session.metadata.session_id
        if media_store is not None:
            options.setdefault("_write_note_media_store", media_store)
    base_data["models"] = {
        "default": "main",
        "main": {
            "provider": resolved_provider,
            "name": resolved_model,
            "options": dict(options),
        },
    }
    return AppConfig(data=base_data, path=app_config.path)


def tool_context_for_request(
    base_context: ToolContext,
    request: Any,
    *,
    model_config: AppConfig | None,
    session: Any | None,
    model_supports_tools: bool = True,
) -> ToolContext:
    provider, model = (
        provider_model_names(
            model_config,
            fallback_provider=str(getattr(request, "provider", "") or ""),
            fallback_model=str(getattr(request, "model", "") or ""),
        )
        if model_config is not None
        else (str(getattr(request, "provider", "") or ""), str(getattr(request, "model", "") or ""))
    )
    options = getattr(request, "model_options", None)
    options = options if isinstance(options, dict) else {}
    return ToolContext(
        library_path=base_context.library_path,
        annotations_dir=base_context.annotations_dir,
        html_dir=base_context.html_dir,
        papers_dir=base_context.papers_dir,
        paper_page_cache_dir=base_context.paper_page_cache_dir,
        paper_image_cache_dir=base_context.paper_image_cache_dir,
        media_store=options.get("_write_note_media_store") or base_context.media_store,
        paper_image_analyzer=base_context.paper_image_analyzer,
        mcp_manager=base_context.mcp_manager,
        session_id=str(options.get("_paper_notes_session_id") or (session.metadata.session_id if session is not None else "")),
        provider_name=provider,
        model=model,
        file_generation=file_generation_options(options),
        image_generation=image_generation_options(options),
        attachments=attachments_from_options(options),
        model_supports_tools=model_supports_tools,
    )


def provider_model_names(config: AppConfig | None, *, fallback_provider: str = "", fallback_model: str = "") -> tuple[str, str]:
    if config is None:
        return fallback_provider, fallback_model
    try:
        model_config = ModelProviderConfig.from_app_config(config)
    except Exception:
        return fallback_provider, fallback_model
    return model_config.provider, model_config.model


def model_supports_tools(model: str | BaseChatModel) -> bool:
    if not isinstance(model, BaseChatModel):
        return True
    return type(model).bind_tools is not BaseChatModel.bind_tools


def native_web_search_requested(options: dict[str, Any] | None) -> bool:
    if not isinstance(options, dict):
        return False
    return truthy_option(options.get("_paper_notes_native_web_search", options.get("_paper_notes_provider_native_web_search")))


def file_generation_options(options: dict[str, Any] | None) -> dict[str, Any]:
    return generation_options(options, FILE_GENERATION_KEYS)


def image_generation_options(options: dict[str, Any] | None) -> dict[str, Any]:
    return generation_options(options, IMAGE_GENERATION_KEYS)


def attachments_from_options(options: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(options, dict):
        return []
    value = options.get("_paper_notes_attachments")
    return [dict(item) for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def image_generation_requested(options: dict[str, Any] | None) -> bool:
    return generation_requested(options, IMAGE_GENERATION_KEYS)


def file_generation_requested(options: dict[str, Any] | None) -> bool:
    return generation_requested(options, FILE_GENERATION_KEYS)


def provider_reasoning_enabled(config: AppConfig) -> bool:
    try:
        options = ModelProviderConfig.from_app_config(config).options
    except Exception:
        return True
    return not reasoning_options_disabled(options)


def reasoning_options_disabled(options: dict[str, Any]) -> bool:
    thinking = options.get("thinking")
    if thinking_option_disabled(thinking):
        return True
    reasoning = options.get("reasoning")
    if reasoning_option_disabled(reasoning):
        return True
    if off_text(options.get("summary")):
        return True
    if str(options.get("thinking_level") or "").strip().lower() == "minimal" and options.get("include_thoughts") is not True:
        return True
    for key in ("reasoning_effort", "effort", "thinking_level"):
        if off_text(options.get(key)):
            return True
    if options.get("include_thoughts") is False:
        return True
    return False


def thinking_option_disabled(value: Any) -> bool:
    if value is False or value is None:
        return value is False
    if isinstance(value, str):
        return off_text(value)
    if isinstance(value, dict):
        return off_text(value.get("type")) or off_text(value.get("mode")) or value.get("enabled") is False
    return False


def reasoning_option_disabled(value: Any) -> bool:
    if value is False or value is None:
        return value is False
    if isinstance(value, str):
        return off_text(value)
    if isinstance(value, dict):
        return (
            off_text(value.get("effort"))
            or off_text(value.get("summary"))
            or off_text(value.get("type"))
            or value.get("enabled") is False
        )
    return False


def off_text(value: Any) -> bool:
    return str(value or "").strip().lower() in {"0", "false", "none", "off", "disabled", "disable"}


__all__ = [
    "AgentTool",
    "attachments_from_options",
    "file_generation_options",
    "file_generation_requested",
    "image_generation_options",
    "image_generation_requested",
    "model_config_for_request",
    "model_supports_tools",
    "native_web_search_requested",
    "provider_model_names",
    "provider_reasoning_enabled",
    "tool_context_for_request",
    "tool_name",
]
