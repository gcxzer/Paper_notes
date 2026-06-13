from __future__ import annotations

import copy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    ChatMessage,
    HumanMessage,
    RemoveMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.messages.utils import count_tokens_approximately
from langchain_core.tools import BaseTool

from agent_runtime.agent_loop import run_agent_loop
from agent_sessions import AgentSession, AgentSessionStore
from app_config import AppConfig, load_app_config
from middleware import DEFAULT_COMPACTION_RESERVE_TOKENS, compaction_trigger_tokens
from model_providers import ModelProviderConfig, create_chat_model, resolve_context_length_for_model
from tools import create_tools


ATTACHMENT_ONLY_MESSAGE = "Please read and summarize the attached file."


@dataclass(slots=True)
class AgentServiceRequest:
    message: Any
    session_id: str | None = None
    title: str = "New chat"
    note_id: str | None = None
    provider: str = ""
    model: str = ""
    system_prompt: str | BaseMessage | None = None
    enable_tools: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)
    run_config: dict[str, Any] | None = None
    stream_mode: str = "values"
    debug: bool = False


@dataclass(slots=True)
class AgentServiceResult:
    session_id: str
    session: AgentSession
    completed: bool
    response: str | None
    messages: list[dict[str, Any]]
    created_session: bool = False
    error: str | None = None
    chunks: list[Any] = field(default_factory=list)


@dataclass(slots=True)
class AgentContextStatus:
    session_id: str
    provider: str
    model: str
    context_window: int
    estimated_tokens: int
    message_tokens: int
    tool_tokens: int
    remaining_tokens: int
    reserve_tokens: int
    collapse_trigger_tokens: int
    compaction_trigger_tokens: int
    collapse_ready: bool
    compaction_ready: bool
    compaction_enabled: bool
    message_count: int

    @property
    def percent_full(self) -> int:
        if self.context_window <= 0:
            return 0
        return min(100, max(0, round((self.estimated_tokens / self.context_window) * 100)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "sessionId": self.session_id,
            "provider": self.provider,
            "model": self.model,
            "contextWindow": self.context_window,
            "estimatedTokens": self.estimated_tokens,
            "messageTokens": self.message_tokens,
            "toolTokens": self.tool_tokens,
            "remainingTokens": self.remaining_tokens,
            "reserveTokens": self.reserve_tokens,
            "collapseTriggerTokens": self.collapse_trigger_tokens,
            "compactionTriggerTokens": self.compaction_trigger_tokens,
            "collapseReady": self.collapse_ready,
            "compactionReady": self.compaction_ready,
            "compactionEnabled": self.compaction_enabled,
            "messageCount": self.message_count,
            "percentFull": self.percent_full,
        }


class AgentService:
    def __init__(
        self,
        *,
        app_config: AppConfig | None = None,
        session_store: AgentSessionStore | None = None,
        chat_model: str | BaseChatModel | None = None,
        model_factory: Any | None = None,
        tools: list[BaseTool] | None = None,
        use_default_tools: bool = True,
        library_path: Path | None = None,
        annotations_dir: Path | None = None,
        html_dir: Path | None = None,
        papers_dir: Path | None = None,
        paper_text_cache_dir: Path | None = None,
        paper_page_cache_dir: Path | None = None,
        paper_image_cache_dir: Path | None = None,
        media_store: Any | None = None,
        paper_image_analyzer: Any | None = None,
    ) -> None:
        self.app_config = app_config or load_app_config()
        self.session_store = session_store or AgentSessionStore()
        self.chat_model = chat_model
        self.model_factory = model_factory or create_chat_model
        self.tools = list(tools) if tools is not None else None
        self.use_default_tools = use_default_tools
        self._tool_kwargs = {
            "library_path": library_path,
            "annotations_dir": annotations_dir,
            "html_dir": html_dir,
            "papers_dir": papers_dir,
            "paper_text_cache_dir": paper_text_cache_dir,
            "paper_page_cache_dir": paper_page_cache_dir,
            "paper_image_cache_dir": paper_image_cache_dir,
            "media_store": media_store,
            "paper_image_analyzer": paper_image_analyzer,
        }

    def run(self, request: AgentServiceRequest) -> AgentServiceResult:
        session, created_session = self._session_for_request(request)
        model_config = self._model_config_for_request(request, session=session)
        provider, model_name = _provider_model_names(model_config, fallback_provider=request.provider, fallback_model=request.model)
        model = self._chat_model(model_config)
        tools = self._tools_for_request(request)
        input_messages = [
            *_messages_from_transcript(session.messages),
            HumanMessage(content=_request_message_content(request)),
        ]

        chunks = list(
            run_agent_loop(
                model,
                input_messages,
                tools=tools,
                app_config=model_config,
                system_prompt=request.system_prompt,
                thread_id=session.metadata.session_id,
                run_config=request.run_config,
                stream_mode=request.stream_mode,
                debug=request.debug,
            )
        )
        final_messages = _messages_from_final_chunk(chunks) or input_messages
        persisted_messages = _messages_to_transcript(final_messages)
        updated_session = self.session_store.replace_messages(session.metadata.session_id, persisted_messages)
        updated_session = self.session_store.update_session_model(
            session.metadata.session_id,
            provider=provider or None,
            model=model_name or None,
        )
        return AgentServiceResult(
            session_id=session.metadata.session_id,
            session=updated_session,
            completed=True,
            response=_last_assistant_text(final_messages),
            messages=updated_session.messages,
            created_session=created_session,
            chunks=chunks,
        )

    def context_status(
        self,
        *,
        session_id: str,
        provider: str = "",
        model: str = "",
        enable_tools: bool = True,
    ) -> AgentContextStatus:
        session = self.session_store.require_session(session_id)
        request = AgentServiceRequest(
            message="",
            session_id=session_id,
            provider=provider,
            model=model,
            enable_tools=enable_tools,
        )
        model_config = self._model_config_for_request(request, session=session)
        provider_name, model_name = _provider_model_names(model_config, fallback_provider=provider, fallback_model=model)
        context_window = resolve_context_length_for_model(provider_name, model_name)
        reserve_tokens = _context_reserve_tokens(model_config)
        trigger_tokens = compaction_trigger_tokens(context_window, reserve_tokens)
        messages = _messages_from_transcript(session.messages)
        tools = self._tools_for_request(request)
        message_tokens = count_tokens_approximately(messages)
        total_tokens = count_tokens_approximately(messages, tools=tools)
        tool_tokens = max(0, total_tokens - message_tokens)
        remaining_tokens = max(0, context_window - total_tokens)
        return AgentContextStatus(
            session_id=session_id,
            provider=provider_name,
            model=model_name,
            context_window=context_window,
            estimated_tokens=total_tokens,
            message_tokens=message_tokens,
            tool_tokens=tool_tokens,
            remaining_tokens=remaining_tokens,
            reserve_tokens=reserve_tokens,
            collapse_trigger_tokens=trigger_tokens,
            compaction_trigger_tokens=trigger_tokens,
            collapse_ready=total_tokens >= trigger_tokens,
            compaction_ready=total_tokens >= trigger_tokens and _has_summary_message(messages),
            compaction_enabled=True,
            message_count=len(session.messages),
        )

    def _session_for_request(self, request: AgentServiceRequest) -> tuple[AgentSession, bool]:
        if request.session_id:
            return self.session_store.require_session(request.session_id), False

        model_config = self._model_config_for_request(request, session=None)
        provider, model_name = _provider_model_names(model_config, fallback_provider=request.provider, fallback_model=request.model)
        session = self.session_store.create_session(
            title=request.title,
            note_id=request.note_id,
            provider=provider or None,
            model=model_name or None,
            metadata=request.metadata,
        )
        return session, True

    def _model_config_for_request(self, request: AgentServiceRequest, *, session: AgentSession | None) -> AppConfig:
        provider = request.provider or (session.metadata.provider if session is not None else "") or ""
        model = request.model or (session.metadata.model if session is not None else "") or ""
        if not provider and not model:
            return self.app_config

        base_data = copy.deepcopy(self.app_config.data)
        base_models = base_data.get("models") if isinstance(base_data.get("models"), dict) else {}
        default_key = str(base_models.get("default") or "main")
        default_section = base_models.get(default_key) if isinstance(base_models.get(default_key), dict) else {}
        resolved_provider = provider or str(default_section.get("provider") or "")
        resolved_model = model or str(default_section.get("name") or "")
        options = default_section.get("options") if isinstance(default_section.get("options"), dict) else {}
        base_data["models"] = {
            "default": "main",
            "main": {
                "provider": resolved_provider,
                "name": resolved_model,
                "options": dict(options),
            },
        }
        return AppConfig(data=base_data, path=self.app_config.path)

    def _chat_model(self, model_config: AppConfig) -> str | BaseChatModel:
        if self.chat_model is not None:
            return self.chat_model
        return self.model_factory(model_config)

    def _tools_for_request(self, request: AgentServiceRequest) -> list[BaseTool]:
        if not request.enable_tools:
            return []
        if self.tools is not None:
            return list(self.tools)
        if not self.use_default_tools:
            return []
        return create_tools(**self._tool_kwargs)


def _request_message_content(request: AgentServiceRequest) -> Any:
    if request.message:
        return request.message
    return ATTACHMENT_ONLY_MESSAGE


def _provider_model_names(config: AppConfig, *, fallback_provider: str = "", fallback_model: str = "") -> tuple[str, str]:
    try:
        model_config = ModelProviderConfig.from_app_config(config)
    except Exception:
        return fallback_provider, fallback_model
    return model_config.provider, model_config.model


def _messages_from_transcript(messages: list[dict[str, Any]]) -> list[BaseMessage]:
    converted: list[BaseMessage] = []
    for message in messages:
        converted_message = _message_from_transcript(message)
        if converted_message is not None:
            converted.append(converted_message)
    return converted


def _message_from_transcript(message: dict[str, Any]) -> BaseMessage | None:
    role = str(message.get("role") or "").strip().lower()
    content = copy.deepcopy(message.get("content", ""))
    name = message.get("name")
    if role == "user":
        return HumanMessage(content=content, name=name)
    if role == "assistant":
        return AIMessage(content=content, name=name, tool_calls=copy.deepcopy(message.get("tool_calls") or []))
    if role == "tool":
        return ToolMessage(
            content=content,
            name=name,
            tool_call_id=str(message.get("tool_call_id") or message.get("id") or "tool-call"),
        )
    if role == "system":
        return SystemMessage(content=content, name=name)
    if role:
        return ChatMessage(role=role, content=content, name=name)
    return None


def _messages_from_final_chunk(chunks: list[Any]) -> list[BaseMessage]:
    for chunk in reversed(chunks):
        if isinstance(chunk, dict) and isinstance(chunk.get("messages"), list):
            return [message for message in chunk["messages"] if isinstance(message, BaseMessage)]
    return []


def _messages_to_transcript(messages: list[BaseMessage]) -> list[dict[str, Any]]:
    return [payload for message in messages if (payload := _message_to_transcript(message)) is not None]


def _message_to_transcript(message: BaseMessage) -> dict[str, Any] | None:
    if isinstance(message, RemoveMessage):
        return None
    payload: dict[str, Any] = {"role": _role_for_message(message), "content": copy.deepcopy(message.content)}
    if message.name:
        payload["name"] = message.name
    if isinstance(message, AIMessage) and message.tool_calls:
        payload["tool_calls"] = copy.deepcopy(message.tool_calls)
    if isinstance(message, ToolMessage):
        payload["tool_call_id"] = message.tool_call_id
    metadata = _message_metadata(message)
    if metadata:
        payload["metadata"] = metadata
    return payload


def _role_for_message(message: BaseMessage) -> str:
    if isinstance(message, HumanMessage):
        return "user"
    if isinstance(message, AIMessage):
        return "assistant"
    if isinstance(message, ToolMessage):
        return "tool"
    if isinstance(message, SystemMessage):
        return "system"
    return str(getattr(message, "role", "") or message.type or "message")


def _message_metadata(message: BaseMessage) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    if getattr(message, "additional_kwargs", None):
        metadata["additional_kwargs"] = copy.deepcopy(message.additional_kwargs)
    if getattr(message, "response_metadata", None):
        metadata["response_metadata"] = copy.deepcopy(message.response_metadata)
    usage = getattr(message, "usage_metadata", None)
    if usage:
        metadata["usage"] = copy.deepcopy(usage)
    return metadata


def _last_assistant_text(messages: list[BaseMessage]) -> str | None:
    for message in reversed(messages):
        if isinstance(message, AIMessage):
            return _content_text(message.content)
    return None


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text") or item.get("content")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(parts)
    return str(content or "")


def _context_reserve_tokens(config: AppConfig) -> int:
    for key in ("context_compaction.reserve_tokens", "contextCompaction.reserveTokens"):
        value = config.get(key, None)
        if value is None:
            continue
        try:
            return max(0, int(value))
        except (TypeError, ValueError):
            continue
    return DEFAULT_COMPACTION_RESERVE_TOKENS


def _has_summary_message(messages: list[BaseMessage]) -> bool:
    return any(
        isinstance(message.content, str) and message.content.strip().startswith("[summary]")
        for message in messages
    )


__all__ = [
    "ATTACHMENT_ONLY_MESSAGE",
    "AgentContextStatus",
    "AgentService",
    "AgentServiceRequest",
    "AgentServiceResult",
]
