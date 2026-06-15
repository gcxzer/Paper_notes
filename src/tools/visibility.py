from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from langchain_core.tools import BaseTool

from app_config.ai_settings import CODEX_PROVIDER, OPENAI_PROVIDER, resolve_openai_api_key
from app_infra.formatting import normalize_text
from model_providers.profiles import ModelCapabilities, capabilities_for_provider_model, normalize_provider_profile_name
from model_providers.providers.codex.auth import codex_auth_path


AgentTool = BaseTool | dict[str, Any]


@dataclass(frozen=True, slots=True)
class ToolContext:
    library_path: Path | None = None
    annotations_dir: Path | None = None
    html_dir: Path | None = None
    papers_dir: Path | None = None
    paper_page_cache_dir: Path | None = None
    paper_image_cache_dir: Path | None = None
    media_store: Any | None = None
    paper_image_analyzer: Any | None = None
    mcp_manager: Any | None = None
    session_id: str = ""
    provider_name: str = ""
    model: str = ""
    file_generation: dict[str, Any] | None = None
    image_generation: dict[str, Any] | None = None
    attachments: list[dict[str, Any]] | None = None
    model_supports_tools: bool = True
    prefer_native_web_search: bool = True


def create_tools(context: ToolContext) -> list[AgentTool]:
    """Build the exact tool list that is visible to the current model request."""
    capabilities = capabilities_for_provider_model(context.provider_name, context.model)
    if not _function_tools_available(context, capabilities):
        return []

    tools: list[AgentTool] = []
    tools.extend(_paper_notes_tools(context, capabilities))
    tools.extend(_generated_file_tools(context))
    tools.extend(_generated_image_tools(context, capabilities))
    tools.extend(_web_tools(context, capabilities))
    tools.extend(_skills_tools())
    tools.extend(_mcp_tools(context))
    return tools


def filter_disabled_tools(tools: list[AgentTool], disabled_tools: tuple[str, ...]) -> list[AgentTool]:
    disabled = {_canonical_tool_name(name) for name in disabled_tools if _canonical_tool_name(name)}
    if not disabled:
        return tools
    return [tool for tool in tools if tool_name(tool) not in disabled]


def tool_name(tool: AgentTool) -> str:
    if isinstance(tool, dict):
        function = tool.get("function") if isinstance(tool.get("function"), dict) else {}
        name = function.get("name") or tool.get("name") or tool.get("type")
    else:
        name = getattr(tool, "name", "")
    return _canonical_tool_name(name)


def _paper_notes_tools(context: ToolContext, capabilities: ModelCapabilities) -> list[BaseTool]:
    from tools.paper_notes import create_tools as create_paper_notes_tools

    can_analyze_images = callable(context.paper_image_analyzer)
    return create_paper_notes_tools(
        library_path=context.library_path,
        annotations_dir=context.annotations_dir,
        html_dir=context.html_dir,
        papers_dir=context.papers_dir,
        paper_page_cache_dir=context.paper_page_cache_dir,
        paper_image_cache_dir=context.paper_image_cache_dir,
        media_store=context.media_store,
        paper_image_analyzer=context.paper_image_analyzer,
        image_analysis_available=can_analyze_images,
        visual_inspection_available=capabilities.supports_vision,
    )


def _generated_file_tools(context: ToolContext) -> list[BaseTool]:
    if context.media_store is None:
        return []
    from tools.generated_files import create_tools as create_generated_file_tools

    return create_generated_file_tools(
        media_store=context.media_store,
        session_id=context.session_id,
        provider_name=context.provider_name,
        model=context.model,
        file_generation=context.file_generation,
    )


def _generated_image_tools(context: ToolContext, capabilities: ModelCapabilities) -> list[BaseTool]:
    if not _image_artifact_generation_available(context, capabilities):
        return []
    from tools.generated_images import create_tools as create_generated_image_tools

    return create_generated_image_tools(
        media_store=context.media_store,
        session_id=context.session_id,
        provider_name=context.provider_name,
        model=context.model,
        image_generation=context.image_generation,
        attachments=context.attachments,
    )


def _web_tools(context: ToolContext, capabilities: ModelCapabilities) -> list[AgentTool]:
    from tools.web_fetch import create_tools as create_web_fetch_tools
    from tools.web_search import create_tools as create_web_search_tools
    from tools.web_search.providers import configured_web_search_available

    tools: list[AgentTool] = []
    native_tool = _provider_native_web_search_tool(context, capabilities)
    if native_tool is not None:
        tools.append(native_tool)
    elif configured_web_search_available():
        tools.extend(create_web_search_tools())
    tools.extend(create_web_fetch_tools())
    return tools


def _skills_tools() -> list[BaseTool]:
    from tools.skills import create_tools as create_skills_tools

    return create_skills_tools()


def _mcp_tools(context: ToolContext) -> list[BaseTool]:
    if context.mcp_manager is None:
        return []
    get_tools = getattr(context.mcp_manager, "tools", None)
    return list(get_tools()) if callable(get_tools) else []


def _function_tools_available(context: ToolContext, capabilities: ModelCapabilities) -> bool:
    return bool(context.model_supports_tools and capabilities.supports_tools)


def _image_artifact_generation_available(context: ToolContext, capabilities: ModelCapabilities) -> bool:
    if context.media_store is None or not capabilities.supports_image_artifact_generation:
        return False
    provider = _provider_name(context.provider_name)
    if provider == OPENAI_PROVIDER:
        return resolve_openai_api_key().configured
    if provider == CODEX_PROVIDER:
        return _codex_auth_configured()
    return False


def _provider_native_web_search_tool(
    context: ToolContext,
    capabilities: ModelCapabilities,
) -> dict[str, Any] | None:
    if not context.prefer_native_web_search or not capabilities.supports_web_search:
        return None
    if _provider_name(context.provider_name) == OPENAI_PROVIDER:
        return {"type": "web_search"}
    return None


def _codex_auth_configured() -> bool:
    try:
        payload = json.loads(codex_auth_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(payload, dict):
        return False
    tokens = payload.get("tokens") if isinstance(payload.get("tokens"), dict) else {}
    return bool(
        tokens.get("access_token")
        or tokens.get("refresh_token")
        or payload.get("accessToken")
        or payload.get("access_token")
        or payload.get("refreshToken")
        or payload.get("refresh_token")
    )


def _provider_name(value: object) -> str:
    text = normalize_text(value).lower()
    return normalize_provider_profile_name(text) or text


def _canonical_tool_name(value: object) -> str:
    text = normalize_text(value)
    return "web_search" if text.startswith("web_search_") else text


__all__ = [
    "AgentTool",
    "ToolContext",
    "create_tools",
    "filter_disabled_tools",
    "tool_name",
]
