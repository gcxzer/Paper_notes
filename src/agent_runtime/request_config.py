"""说明：从请求和配置里整理本轮模型运行参数。

作用：确定 provider、model、工具开关、生成模式和 prompt 上下文，供 AgentService 使用。
"""

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
)
from model_providers import ModelProviderConfig
from tools import AgentTool, ToolContext

__all__ = [
    "AgentTool",
    "model_config_for_request",
    "model_supports_tools",
    "provider_model_names",
    "provider_reasoning_enabled",
    "tool_context_for_request",
]


# 模型配置
def model_config_for_request(
    app_config: AppConfig,
    request: Any,
    *,
    session: Any | None,
    media_store: Any | None = None,
) -> AppConfig:
    """根据请求和会话覆盖默认模型配置，并注入生成类工具需要的运行上下文。"""
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
    if generation_requested(options, IMAGE_GENERATION_KEYS):
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


def provider_model_names(config: AppConfig | None, *, fallback_provider: str = "", fallback_model: str = "") -> tuple[str, str]:
    """从 AppConfig 里读取 provider/model，读取失败时回退到请求显式传入的值。"""
    if config is None:
        return fallback_provider, fallback_model
    try:
        model_config = ModelProviderConfig.from_app_config(config)
    except Exception:
        return fallback_provider, fallback_model
    return model_config.provider, model_config.model


def model_supports_tools(model: str | BaseChatModel) -> bool:
    """判断当前模型对象是否实现 LangChain 的 bind_tools 能力。"""
    if not isinstance(model, BaseChatModel):
        return True
    return type(model).bind_tools is not BaseChatModel.bind_tools


# 工具上下文
def tool_context_for_request(
    base_context: ToolContext,
    request: Any,
    *,
    model_config: AppConfig | None,
    session: Any | None,
    model_supports_tools: bool = True,
) -> ToolContext:
    """把请求、会话、模型配置转换成工具层使用的 ToolContext。"""
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
    attachments_value = options.get("_paper_notes_attachments")
    attachments = [dict(item) for item in attachments_value if isinstance(item, dict)] if isinstance(attachments_value, list) else []
    return ToolContext(
        library_path=base_context.library_path,
        annotations_dir=base_context.annotations_dir,
        html_dir=base_context.html_dir,
        papers_dir=base_context.papers_dir,
        paper_visual_cache_dir=base_context.paper_visual_cache_dir,
        media_store=options.get("_write_note_media_store") or base_context.media_store,
        mcp_manager=base_context.mcp_manager,
        session_id=str(options.get("_paper_notes_session_id") or (session.metadata.session_id if session is not None else "")),
        provider_name=provider,
        model=model,
        file_generation=generation_options(options, FILE_GENERATION_KEYS),
        image_generation=generation_options(options, IMAGE_GENERATION_KEYS),
        attachments=attachments,
        model_supports_tools=model_supports_tools,
        paper_image_analyzer=base_context.paper_image_analyzer,
    )


# Provider reasoning 开关
def provider_reasoning_enabled(config: AppConfig) -> bool:
    """根据模型 options 判断是否允许把 provider reasoning/summary 暴露成 trace。"""
    try:
        options = ModelProviderConfig.from_app_config(config).options
    except Exception:
        return True
    return not reasoning_options_disabled(options)


def reasoning_options_disabled(options: dict[str, Any]) -> bool:
    """识别多家 provider 常见的关闭 reasoning/thinking 的 option 组合。"""
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
    """判断 thinking 配置项是否表达为关闭。"""
    if value is False or value is None:
        return value is False
    if isinstance(value, str):
        return off_text(value)
    if isinstance(value, dict):
        return off_text(value.get("type")) or off_text(value.get("mode")) or value.get("enabled") is False
    return False


def reasoning_option_disabled(value: Any) -> bool:
    """判断 reasoning 配置项是否表达为关闭。"""
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
    """判断文本值是否属于常见的关闭标记。"""
    return str(value or "").strip().lower() in {"0", "false", "none", "off", "disabled", "disable"}
