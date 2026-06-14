from __future__ import annotations

import copy
import json
from collections.abc import Iterator
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    ChatMessage,
    get_buffer_string,
    HumanMessage,
    RemoveMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.messages.utils import count_tokens_approximately
from langchain_core.tools import BaseTool

from agent_runtime.agent_loop import run_agent_loop
from agent_runtime.streaming import (
    AgentStreamEvent,
    LANGCHAIN_AGENT_STREAM_MODES,
    events_from_langchain_chunk,
    provider_reasoning_event_from_message,
)
from agent_sessions import AgentSession, AgentSessionStore
from app_config import AppConfig, load_app_config
from middleware import DEFAULT_COMPACTION_RESERVE_TOKENS, SUMMARY_MESSAGE_PREFIX, compaction_trigger_tokens
from middleware.compaction import COMPACT_SUMMARY_PROMPT
from model_providers import ModelProviderConfig, create_chat_model, resolve_context_length_for_model
from model_providers.core.types import canonical_provider_name
from tools import ToolContext, create_tools


ATTACHMENT_ONLY_MESSAGE = "Please read and summarize the attached file."
RECOVERY_MESSAGE_NAME = "paper_notes_recovery"
ACTIVE_RUN_METADATA_KEY = "activeRun"
RECOVERABLE_REQUEST_OPTION_KEYS = {
    "_paper_notes_image_generation",
    "imageGeneration",
    "image_generation",
    "_paper_notes_native_web_search",
    "_paper_notes_provider_native_web_search",
    "native_web_search",
    "web_search",
    "temperature",
    "top_p",
    "reasoning",
    "reasoning_effort",
    "effort",
    "summary",
    "thinking",
    "thinking_level",
    "include_thoughts",
    "max_tokens",
    "max_completion_tokens",
    "max_output_tokens",
    "response_format",
    "tool_choice",
    "parallel_tool_calls",
}
AgentTool = BaseTool | dict[str, Any]


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
    model_options: dict[str, Any] = field(default_factory=dict)
    disabled_tools: tuple[str, ...] = ()
    run_config: dict[str, Any] | None = None
    stream_mode: str = "values"


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
    events: list[dict[str, Any]] = field(default_factory=list)
    run_trace: dict[str, Any] | None = None


@dataclass(slots=True)
class AgentCompactResult:
    session_id: str
    session: AgentSession
    compressed: bool
    context: AgentContextStatus
    events: list[dict[str, Any]] = field(default_factory=list)
    warning: str = ""


@dataclass(slots=True)
class AgentContextStatus:
    session_id: str
    provider: str
    model: str
    context_window: int
    estimated_tokens: int
    message_tokens: int
    tool_tokens: int
    actual_input_tokens: int
    actual_output_tokens: int
    actual_total_tokens: int
    actual_usage_available: bool
    usage_updated_at: str
    usage_request_id: str
    remaining_tokens: int
    reserve_tokens: int
    collapse_trigger_tokens: int
    collapse_trigger_messages: int
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
            "actualInputTokens": self.actual_input_tokens,
            "actualOutputTokens": self.actual_output_tokens,
            "actualTotalTokens": self.actual_total_tokens,
            "actualUsageAvailable": self.actual_usage_available,
            "usageUpdatedAt": self.usage_updated_at,
            "usageRequestId": self.usage_request_id,
            "remainingTokens": self.remaining_tokens,
            "reserveTokens": self.reserve_tokens,
            "collapseTriggerTokens": self.collapse_trigger_tokens,
            "collapseTriggerMessages": self.collapse_trigger_messages,
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
        self.mcp_manager = None
        if self.use_default_tools and tools is None:
            try:
                from tools.mcp import MCPManager

                self.mcp_manager = MCPManager(media_store=media_store)
                self.mcp_manager.discover_from_settings()
            except Exception:
                self.mcp_manager = None
        self._tool_context = ToolContext(
            library_path=library_path,
            annotations_dir=annotations_dir,
            html_dir=html_dir,
            papers_dir=papers_dir,
            paper_text_cache_dir=paper_text_cache_dir,
            paper_page_cache_dir=paper_page_cache_dir,
            paper_image_cache_dir=paper_image_cache_dir,
            media_store=media_store,
            paper_image_analyzer=paper_image_analyzer,
            mcp_manager=self.mcp_manager,
        )

    def run(self, request: AgentServiceRequest) -> AgentServiceResult:
        session, created_session = self._session_for_request(request)
        model_config = self._model_config_for_request(request, session=session)
        provider, model_name = _provider_model_names(model_config, fallback_provider=request.provider, fallback_model=request.model)
        model = self._chat_model(model_config)
        tools = self._tools_for_request(request, model_config=model_config, session=session)
        if tools and not _model_supports_tools(model):
            tools = []
        input_messages = [
            *_messages_from_transcript(session.messages),
            HumanMessage(content=_request_message_content(request)),
        ]
        session = self._persist_active_run(
            session,
            request,
            input_messages=input_messages,
            provider=provider,
            model=model_name,
        )

        try:
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
                )
            )
            final_messages = _messages_from_final_chunk(chunks) or input_messages
        except Exception as error:
            if not _is_recoverable_model_request_error(error):
                self._finish_active_run(session.metadata.session_id, request, status="failed", error=error)
                raise
            recovery_config = _model_config_for_recovery(model_config)
            recovery_messages = _messages_with_recovery_instruction(
                input_messages,
                error,
                provider=provider,
                model=model_name,
            )
            try:
                chunks = list(
                    run_agent_loop(
                        self._chat_model(recovery_config),
                        recovery_messages,
                        tools=[],
                        app_config=recovery_config,
                        system_prompt=request.system_prompt,
                        thread_id=session.metadata.session_id,
                        run_config=request.run_config,
                        stream_mode=request.stream_mode,
                    )
                )
            except BaseException as recovery_error:
                self._finish_active_run(session.metadata.session_id, request, status="failed", error=recovery_error)
                raise
            final_messages = _recovered_final_messages(chunks, recovery_messages, input_messages, error)
        except BaseException as error:
            self._finish_active_run(session.metadata.session_id, request, status="failed", error=error)
            raise
        persisted_messages = _with_generated_artifacts_on_latest_assistant(
            _messages_to_transcript(final_messages),
            start_index=max(0, len(session.messages) - 1),
        )
        persisted_messages = _merge_existing_transcript_fields(
            persisted_messages,
            session.messages,
        )
        response_text = _last_assistant_text(final_messages) or _last_assistant_transcript_text(persisted_messages)
        updated_session = self.session_store.replace_messages(session.metadata.session_id, persisted_messages)
        self._finish_active_run(session.metadata.session_id, request, status="completed")
        updated_session = self.session_store.update_session_model(
            session.metadata.session_id,
            provider=provider or None,
            model=model_name or None,
        )
        return AgentServiceResult(
            session_id=session.metadata.session_id,
            session=updated_session,
            completed=True,
            response=response_text,
            messages=updated_session.messages,
            created_session=created_session,
            chunks=chunks,
        )

    def stream(self, request: AgentServiceRequest) -> Iterator[AgentStreamEvent]:
        session, created_session = self._session_for_request(request)
        model_config = self._model_config_for_request(request, session=session)
        provider, model_name = _provider_model_names(model_config, fallback_provider=request.provider, fallback_model=request.model)
        model = self._chat_model(model_config)
        tools = self._tools_for_request(request, model_config=model_config, session=session)
        if tools and not _model_supports_tools(model):
            tools = []
        input_messages = [
            *_messages_from_transcript(session.messages),
            HumanMessage(content=_request_message_content(request)),
        ]
        session = self._persist_active_run(
            session,
            request,
            input_messages=input_messages,
            provider=provider,
            model=model_name,
        )

        chunks: list[Any] = []
        started_at = _now_utc()
        run_events: list[dict[str, Any]] = []
        provider_reasoning_enabled = _provider_reasoning_enabled(model_config)
        start_event = AgentStreamEvent("work_trace_item", {
            "text": "Starting agent run.",
            "traceType": "status",
            "source": "runtime",
        })
        _stamp_stream_event(start_event)
        start_trace_event = _run_trace_event_from_stream_event(start_event)
        if start_trace_event:
            run_events.append(start_trace_event)
        self._update_active_run_progress(session.metadata.session_id, request, events=run_events, status="running")
        yield start_event
        try:
            for chunk in run_agent_loop(
                model,
                input_messages,
                tools=tools,
                app_config=model_config,
                system_prompt=request.system_prompt,
                thread_id=session.metadata.session_id,
                run_config=request.run_config,
                stream_mode=LANGCHAIN_AGENT_STREAM_MODES,
                stream_version="v2",
            ):
                chunks.append(chunk)
                for event in events_from_langchain_chunk(chunk):
                    if not provider_reasoning_enabled and _is_provider_reasoning_stream_event(event):
                        continue
                    _stamp_stream_event(event)
                    trace_event = _run_trace_event_from_stream_event(event)
                    if trace_event:
                        run_events.append(trace_event)
                        self._update_active_run_progress(
                            session.metadata.session_id,
                            request,
                            events=run_events,
                            status="running",
                        )
                    yield event
            final_messages = _messages_from_final_chunk(chunks) or input_messages
        except Exception as error:
            if not _is_recoverable_model_request_error(error):
                self._finish_active_run(session.metadata.session_id, request, status="failed", error=error)
                raise
            recovery_event = AgentStreamEvent("work_trace_item", {
                "text": "Provider rejected an unsupported request option; asking the model to respond without that capability.",
                "traceType": "status",
                "source": "runtime",
            })
            _stamp_stream_event(recovery_event)
            trace_event = _run_trace_event_from_stream_event(recovery_event)
            if trace_event:
                run_events.append(trace_event)
                self._update_active_run_progress(session.metadata.session_id, request, events=run_events, status="running")
            yield recovery_event
            recovery_config = _model_config_for_recovery(model_config)
            recovery_messages = _messages_with_recovery_instruction(
                input_messages,
                error,
                provider=provider,
                model=model_name,
            )
            chunks = []
            provider_reasoning_enabled = _provider_reasoning_enabled(recovery_config)
            try:
                for chunk in run_agent_loop(
                    self._chat_model(recovery_config),
                    recovery_messages,
                    tools=[],
                    app_config=recovery_config,
                    system_prompt=request.system_prompt,
                    thread_id=session.metadata.session_id,
                    run_config=request.run_config,
                    stream_mode=LANGCHAIN_AGENT_STREAM_MODES,
                    stream_version="v2",
                ):
                    chunks.append(chunk)
                    for event in events_from_langchain_chunk(chunk):
                        if not provider_reasoning_enabled and _is_provider_reasoning_stream_event(event):
                            continue
                        _stamp_stream_event(event)
                        trace_event = _run_trace_event_from_stream_event(event)
                        if trace_event:
                            run_events.append(trace_event)
                            self._update_active_run_progress(
                                session.metadata.session_id,
                                request,
                                events=run_events,
                                status="running",
                            )
                        yield event
            except BaseException as recovery_error:
                self._finish_active_run(session.metadata.session_id, request, status="failed", error=recovery_error)
                raise
            final_messages = _recovered_final_messages(chunks, recovery_messages, input_messages, error)
        except BaseException as error:
            self._finish_active_run(session.metadata.session_id, request, status="failed", error=error)
            raise

        finished_at = _now_utc()
        for event in _work_trace_events_from_messages(
            final_messages,
            include_provider_reasoning=provider_reasoning_enabled,
        ):
            event.data.setdefault("at", _isoformat_utc(finished_at))
            trace_event = _run_trace_event_from_stream_event(event)
            if trace_event and _run_trace_has_equivalent_event(run_events, trace_event):
                continue
            if trace_event:
                run_events.append(trace_event)
            yield event
        for trace_event in _model_response_trace_events(
            _new_messages_for_current_run(final_messages, input_messages),
            at=finished_at,
        ):
            if _run_trace_has_equivalent_event(run_events, trace_event):
                continue
            run_events.append(trace_event)
        run_trace = _run_trace_payload(
            request,
            started_at=started_at,
            finished_at=finished_at,
            status="completed",
            events=run_events,
        )
        persisted_messages = _with_generated_artifacts_on_latest_assistant(
            _messages_to_transcript(final_messages),
            start_index=max(0, len(session.messages) - 1),
        )
        persisted_messages = _merge_existing_transcript_fields(
            persisted_messages,
            session.messages,
        )
        persisted_messages = _with_assistant_run_trace(persisted_messages, run_trace)
        response_text = _last_assistant_text(final_messages) or _last_assistant_transcript_text(persisted_messages)
        updated_session = self.session_store.replace_messages(session.metadata.session_id, persisted_messages)
        self._finish_active_run(session.metadata.session_id, request, status="completed")
        updated_session = self.session_store.update_session_model(
            session.metadata.session_id,
            provider=provider or None,
            model=model_name or None,
        )
        yield AgentStreamEvent("final", {
            "result": AgentServiceResult(
                session_id=session.metadata.session_id,
                session=updated_session,
                completed=True,
                response=response_text,
                messages=updated_session.messages,
                created_session=created_session,
                chunks=chunks,
                events=run_events,
                run_trace=run_trace,
            )
        })

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
        collapse_trigger_messages = _context_collapse_trigger_messages(model_config)
        collapse_trigger_tokens = _context_collapse_trigger_tokens(model_config)
        messages = _messages_from_transcript(session.messages)
        tools = self._tools_for_request(request, model_config=model_config)
        message_tokens = count_tokens_approximately(messages)
        total_tokens = count_tokens_approximately(messages, tools=tools)
        tool_tokens = max(0, total_tokens - message_tokens)
        actual_usage = _latest_usage_from_transcript(session.messages)
        remaining_tokens = max(0, context_window - total_tokens)
        return AgentContextStatus(
            session_id=session_id,
            provider=provider_name,
            model=model_name,
            context_window=context_window,
            estimated_tokens=total_tokens,
            message_tokens=message_tokens,
            tool_tokens=tool_tokens,
            actual_input_tokens=int(actual_usage.get("input_tokens") or 0),
            actual_output_tokens=int(actual_usage.get("output_tokens") or 0),
            actual_total_tokens=int(actual_usage.get("total_tokens") or 0),
            actual_usage_available=bool(actual_usage.get("available")),
            usage_updated_at=str(actual_usage.get("updated_at") or ""),
            usage_request_id=str(actual_usage.get("request_id") or ""),
            remaining_tokens=remaining_tokens,
            reserve_tokens=reserve_tokens,
            collapse_trigger_tokens=collapse_trigger_tokens,
            collapse_trigger_messages=collapse_trigger_messages,
            compaction_trigger_tokens=trigger_tokens,
            collapse_ready=len(session.messages) >= collapse_trigger_messages or total_tokens >= collapse_trigger_tokens,
            compaction_ready=total_tokens >= trigger_tokens and _has_compactable_history(messages),
            compaction_enabled=True,
            message_count=len(session.messages),
        )

    def compact_session(
        self,
        *,
        session_id: str,
        focus: str | None = None,
        provider: str = "",
        model: str = "",
        enable_tools: bool = True,
        model_options: dict[str, Any] | None = None,
        disabled_tools: tuple[str, ...] = (),
    ) -> AgentCompactResult:
        session = self.session_store.require_session(session_id)
        request = AgentServiceRequest(
            message="compact",
            session_id=session_id,
            provider=provider,
            model=model,
            enable_tools=enable_tools,
            model_options=dict(model_options or {}),
            disabled_tools=tuple(disabled_tools or ()),
        )
        model_config = self._model_config_for_request(request, session=session)
        provider_name, model_name = _provider_model_names(model_config, fallback_provider=provider, fallback_model=model)
        cutoff_index = _manual_compaction_cutoff_index(session.messages)
        if cutoff_index is None:
            return AgentCompactResult(
                session_id=session.metadata.session_id,
                session=session,
                compressed=False,
                context=self.context_status(
                    session_id=session.metadata.session_id,
                    provider=provider_name,
                    model=model_name,
                    enable_tools=enable_tools,
                ),
            )

        raw_messages_to_compact = _model_visible_transcript_messages(session.messages[:cutoff_index])
        messages_to_compact = _messages_from_transcript(raw_messages_to_compact)
        if not messages_to_compact:
            return AgentCompactResult(
                session_id=session.metadata.session_id,
                session=session,
                compressed=False,
                context=self.context_status(
                    session_id=session.metadata.session_id,
                    provider=provider_name,
                    model=model_name,
                    enable_tools=enable_tools,
                ),
            )

        started_at = _now_utc()
        start_event = _context_compaction_trace_event(
            "context_compressing",
            "Compacting session context.",
            at=started_at,
            session_id=session.metadata.session_id,
            provider=provider_name,
            model=model_name,
            focus=focus,
        )
        summary = _compact_messages_with_model(self._chat_model(model_config), messages_to_compact, focus=focus)
        summary_message = _compacted_summary_transcript_message(summary)
        marker = _context_compaction_marker_message(focus=focus)
        preserved_messages = copy.deepcopy(session.messages[cutoff_index:])
        updated_session = self.session_store.replace_messages(
            session.metadata.session_id,
            [summary_message, *preserved_messages, marker],
        )
        updated_session = self.session_store.update_session_model(
            session.metadata.session_id,
            provider=provider_name or None,
            model=model_name or None,
        )
        finished_at = _now_utc()
        done_event = _context_compaction_trace_event(
            "context_compressed",
            "Context compacted.",
            at=finished_at,
            session_id=session.metadata.session_id,
            provider=provider_name,
            model=model_name,
            focus=focus,
        )
        return AgentCompactResult(
            session_id=updated_session.metadata.session_id,
            session=updated_session,
            compressed=True,
            context=self.context_status(
                session_id=updated_session.metadata.session_id,
                provider=provider_name,
                model=model_name,
                enable_tools=enable_tools,
            ),
            events=[start_event, done_event],
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
        options = dict(default_section.get("options") if isinstance(default_section.get("options"), dict) else {})
        if isinstance(request.model_options, dict):
            options.update(request.model_options)
        if _image_generation_requested(options):
            options.setdefault("_paper_notes_provider", resolved_provider)
            if session is not None:
                options["_paper_notes_session_id"] = session.metadata.session_id
            media_store = getattr(self._tool_context, "media_store", None)
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
        return AppConfig(data=base_data, path=self.app_config.path)

    def _chat_model(self, model_config: AppConfig) -> str | BaseChatModel:
        if self.chat_model is not None:
            return self.chat_model
        return self.model_factory(model_config)

    def _tools_for_request(
        self,
        request: AgentServiceRequest,
        *,
        model_config: AppConfig | None = None,
        session: AgentSession | None = None,
    ) -> list[AgentTool]:
        if not request.enable_tools:
            return []
        if self.tools is not None:
            tools = _filter_disabled_tools(list(self.tools), request.disabled_tools)
        elif not self.use_default_tools:
            tools = []
        else:
            tools = _filter_disabled_tools(
                create_tools(context=self._tool_context_for_request(request, model_config=model_config, session=session)),
                request.disabled_tools,
            )
        return _with_provider_native_web_search(tools, request, model_config=model_config)

    def _tool_context_for_request(
        self,
        request: AgentServiceRequest,
        *,
        model_config: AppConfig | None,
        session: AgentSession | None,
    ) -> ToolContext:
        provider, model = _provider_model_names(model_config, fallback_provider=request.provider, fallback_model=request.model) if model_config is not None else (request.provider, request.model)
        options = request.model_options if isinstance(request.model_options, dict) else {}
        return ToolContext(
            library_path=self._tool_context.library_path,
            annotations_dir=self._tool_context.annotations_dir,
            html_dir=self._tool_context.html_dir,
            papers_dir=self._tool_context.papers_dir,
            paper_text_cache_dir=self._tool_context.paper_text_cache_dir,
            paper_page_cache_dir=self._tool_context.paper_page_cache_dir,
            paper_image_cache_dir=self._tool_context.paper_image_cache_dir,
            media_store=options.get("_write_note_media_store") or self._tool_context.media_store,
            paper_image_analyzer=self._tool_context.paper_image_analyzer,
            mcp_manager=self._tool_context.mcp_manager,
            session_id=str(options.get("_paper_notes_session_id") or (session.metadata.session_id if session is not None else "")),
            provider_name=provider,
            model=model,
            file_generation=_file_generation_options(options),
            image_generation=_image_generation_options(options),
            attachments=_attachments_from_options(options),
        )

    def close(self) -> None:
        manager = self.mcp_manager
        self.mcp_manager = None
        shutdown = getattr(manager, "shutdown", None)
        if callable(shutdown):
            shutdown()

    def _persist_active_run(
        self,
        session: AgentSession,
        request: AgentServiceRequest,
        *,
        input_messages: list[BaseMessage],
        provider: str,
        model: str,
    ) -> AgentSession:
        transcript = _messages_to_transcript(input_messages)
        transcript = _merge_existing_transcript_fields(transcript, session.messages)
        persisted = self.session_store.replace_messages(session.metadata.session_id, transcript)
        metadata = _active_run_metadata(
            request,
            provider=provider,
            model=model,
            status="running",
        )
        if metadata:
            self.session_store.update_session_metadata(session.metadata.session_id, {ACTIVE_RUN_METADATA_KEY: metadata})
            persisted = self.session_store.require_session(session.metadata.session_id)
        return persisted

    def _update_active_run_progress(
        self,
        session_id: str,
        request: AgentServiceRequest,
        *,
        events: list[dict[str, Any]],
        status: str,
    ) -> None:
        request_id = _request_id(request)
        if not request_id:
            return
        current = self.session_store.get_session(session_id)
        active_run = _active_run_for_request(current, request_id)
        if not active_run:
            return
        active_run = dict(active_run)
        active_run["status"] = status
        active_run["progress"] = _active_run_progress_payload(request_id, status=status, events=events)
        self.session_store.update_session_metadata(session_id, {ACTIVE_RUN_METADATA_KEY: active_run})

    def _finish_active_run(
        self,
        session_id: str,
        request: AgentServiceRequest,
        *,
        status: str,
        error: BaseException | None = None,
    ) -> None:
        request_id = _request_id(request)
        if not request_id:
            return
        current = self.session_store.get_session(session_id)
        active_run = _active_run_for_request(current, request_id)
        if not active_run:
            return
        metadata = dict(current.metadata.metadata)
        if status == "completed":
            metadata.pop(ACTIVE_RUN_METADATA_KEY, None)
        else:
            failed = dict(active_run)
            failed["status"] = status
            failed["finishedAt"] = _isoformat_utc(_now_utc())
            if error is not None:
                failed["error"] = _short_exception_text(error)
            metadata[ACTIVE_RUN_METADATA_KEY] = failed
        self.session_store.update_session_metadata(session_id, metadata, replace=True)


def _request_message_content(request: AgentServiceRequest) -> Any:
    if request.message:
        return request.message
    return ATTACHMENT_ONLY_MESSAGE


def _request_id(request: AgentServiceRequest) -> str:
    return str(request.metadata.get("requestId") or request.metadata.get("request_id") or "").strip()


def _active_run_metadata(
    request: AgentServiceRequest,
    *,
    provider: str,
    model: str,
    status: str,
) -> dict[str, Any]:
    request_id = _request_id(request)
    if not request_id:
        return {}
    started_at = _isoformat_utc(_now_utc())
    message = _content_text(_request_message_content(request)).strip()
    return {
        "requestId": request_id,
        "status": status,
        "startedAt": started_at,
        "provider": provider,
        "model": model,
        "noteId": request.note_id or "",
        "message": message[:500],
        "progress": _active_run_progress_payload(request_id, status=status, events=[]),
    }


def _active_run_for_request(session: AgentSession | None, request_id: str) -> dict[str, Any]:
    if session is None:
        return {}
    metadata = session.metadata.metadata if isinstance(session.metadata.metadata, dict) else {}
    active_run = metadata.get(ACTIVE_RUN_METADATA_KEY)
    if not isinstance(active_run, dict):
        return {}
    if str(active_run.get("requestId") or active_run.get("request_id") or "").strip() != request_id:
        return {}
    return active_run


def _active_run_progress_payload(
    request_id: str,
    *,
    status: str,
    events: list[dict[str, Any]],
) -> dict[str, Any]:
    visible_events = [
        {
            "stage": str(event.get("stage") or event.get("type") or "").strip(),
            "detail": str(event.get("message") or "").strip(),
            "at": str(event.get("at") or "").strip(),
        }
        for event in events
        if str(event.get("message") or "").strip()
    ]
    work_items = [
        {
            "type": str(event.get("stage") or event.get("type") or "status").strip() or "status",
            "text": str(event.get("message") or "").strip(),
            "at": str(event.get("at") or "").strip(),
            "source": str((event.get("data") if isinstance(event.get("data"), dict) else {}).get("source") or "runtime"),
            "data": event.get("data") if isinstance(event.get("data"), dict) else {},
            "complete": _run_trace_event_work_item_complete(event),
        }
        for event in events
        if str(event.get("message") or "").strip()
    ]
    detail = visible_events[-1]["detail"] if visible_events else "Starting agent run."
    stage = visible_events[-1]["stage"] if visible_events else "starting"
    return {
        "requestId": request_id,
        "status": status,
        "stage": stage or status,
        "detail": detail,
        "visibleEvents": visible_events,
        "events": list(events),
        "workTrace": {"status": status, "items": work_items},
    }


def _run_trace_event_work_item_complete(event: dict[str, Any]) -> bool:
    if str(event.get("type") or "").strip() == "work_trace_delta":
        return False
    data = event.get("data") if isinstance(event.get("data"), dict) else {}
    nested = data.get("data") if isinstance(data.get("data"), dict) else {}
    for payload in (nested, data):
        if payload.get("statusComplete") is False or payload.get("complete") is False:
            return False
        if payload.get("statusComplete") is True or payload.get("complete") is True:
            return True
    return True


def _is_recoverable_model_request_error(error: Exception) -> bool:
    text = _exception_text(error).lower()
    if not text:
        return False
    has_request_failure = any(
        marker in text
        for marker in (
            "invalid_request_error",
            "bad request",
            "error code: 400",
            "status code: 400",
            "unsupported",
            "not supported",
        )
    )
    if not has_request_failure:
        return False
    return any(
        marker in text
        for marker in (
            "tool",
            "tools",
            "parameter",
            "image_generation",
            "web_search",
            "temperature",
            "reasoning",
            "tool_choice",
            "response_format",
            "max_output_tokens",
        )
    )


def _model_config_for_recovery(config: AppConfig) -> AppConfig:
    data = copy.deepcopy(config.data)
    models = data.get("models") if isinstance(data.get("models"), dict) else {}
    default_key = str(models.get("default") or "main")
    section = dict(models.get(default_key) if isinstance(models.get(default_key), dict) else {})
    options = dict(section.get("options") if isinstance(section.get("options"), dict) else {})
    for key in RECOVERABLE_REQUEST_OPTION_KEYS:
        options.pop(key, None)
    section["options"] = options
    models[default_key] = section
    data["models"] = models
    return AppConfig(data=data, path=config.path)


def _messages_with_recovery_instruction(
    input_messages: list[BaseMessage],
    error: Exception,
    *,
    provider: str,
    model: str,
) -> list[BaseMessage]:
    return [
        *input_messages,
        HumanMessage(
            content=_model_request_recovery_instruction(error, provider=provider, model=model),
            name=RECOVERY_MESSAGE_NAME,
        ),
    ]


def _model_request_recovery_instruction(error: Exception, *, provider: str, model: str) -> str:
    label = " / ".join(part for part in (provider, model) if part)
    detail = _short_exception_text(error)
    return (
        "The previous provider request failed before an assistant reply because the current "
        f"{label or 'provider/model'} rejected an unsupported tool, capability, or optional request parameter.\n"
        f"Provider error: {detail}\n\n"
        "Answer the user's latest real request directly in natural language using the conversation and visible "
        "context. Do not call tools in this recovery reply. If the user asked for an unavailable artifact or "
        "capability, explain the limitation plainly and offer the closest useful text-only help, such as a prompt, "
        "outline, or next step. Match the user's language."
    )


def _recovered_final_messages(
    chunks: list[Any],
    recovery_messages: list[BaseMessage],
    original_input_messages: list[BaseMessage],
    error: Exception,
) -> list[BaseMessage]:
    final_messages = _messages_from_final_chunk(chunks) or recovery_messages
    stripped = _without_recovery_messages(final_messages)
    if _last_assistant_text(stripped) is not None:
        return _mark_latest_assistant_recovered(stripped, error)
    return [
        *original_input_messages,
        AIMessage(
            content=_generic_recovery_response(error),
            response_metadata={"recovered_from_error": _short_exception_text(error)},
        ),
    ]


def _without_recovery_messages(messages: list[BaseMessage]) -> list[BaseMessage]:
    return [
        message
        for message in messages
        if not (isinstance(message, HumanMessage) and str(getattr(message, "name", "") or "") == RECOVERY_MESSAGE_NAME)
    ]


def _mark_latest_assistant_recovered(messages: list[BaseMessage], error: Exception) -> list[BaseMessage]:
    updated = list(messages)
    for index in range(len(updated) - 1, -1, -1):
        message = updated[index]
        if not isinstance(message, AIMessage):
            continue
        metadata = dict(getattr(message, "response_metadata", None) or {})
        metadata.setdefault("recovered_from_error", _short_exception_text(error))
        updated[index] = message.model_copy(update={"response_metadata": metadata})
        break
    return updated


def _generic_recovery_response(error: Exception) -> str:
    return (
        "The current model could not use one of the requested capabilities for this turn. "
        f"Provider detail: {_short_exception_text(error)}"
    )


def _short_exception_text(error: Exception, *, limit: int = 500) -> str:
    text = _exception_text(error)
    return text if len(text) <= limit else f"{text[:limit - 3]}..."


def _exception_text(error: Exception) -> str:
    return " ".join(str(error or "").split())


def _provider_model_names(config: AppConfig, *, fallback_provider: str = "", fallback_model: str = "") -> tuple[str, str]:
    try:
        model_config = ModelProviderConfig.from_app_config(config)
    except Exception:
        return fallback_provider, fallback_model
    return model_config.provider, model_config.model


def _latest_usage_from_transcript(messages: list[dict[str, Any]]) -> dict[str, Any]:
    for message in reversed(messages):
        if message.get("role") != "assistant":
            continue
        usage = _usage_from_transcript_message(message)
        if not usage.get("available"):
            continue
        run_trace = message.get("runTrace") if isinstance(message.get("runTrace"), dict) else {}
        usage["updated_at"] = str(run_trace.get("finishedAt") or "")
        usage["request_id"] = str(run_trace.get("requestId") or "")
        return usage
    return {
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "available": False,
        "updated_at": "",
        "request_id": "",
    }


def _usage_from_transcript_message(message: dict[str, Any]) -> dict[str, Any]:
    metadata = message.get("metadata") if isinstance(message.get("metadata"), dict) else {}
    response_metadata = metadata.get("response_metadata") if isinstance(metadata.get("response_metadata"), dict) else {}
    candidates = [
        metadata.get("usage"),
        response_metadata.get("usage"),
        response_metadata.get("usage_metadata"),
        response_metadata.get("usageMetadata"),
        response_metadata.get("token_usage"),
        response_metadata.get("tokenUsage"),
    ]
    for candidate in candidates:
        usage = _normalize_usage(candidate)
        if usage.get("available"):
            return usage
    return {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "available": False}


def _normalize_usage(value: Any) -> dict[str, Any]:
    if value is None:
        return {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "available": False}
    if is_dataclass(value) and not isinstance(value, type):
        value = asdict(value)
    elif hasattr(value, "model_dump"):
        try:
            value = value.model_dump(mode="json")
        except TypeError:
            value = value.model_dump()
    elif hasattr(value, "to_dict"):
        value = value.to_dict()
    if not isinstance(value, dict):
        return {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "available": False}
    input_tokens = _first_int(
        value,
        "input_tokens",
        "inputTokens",
        "prompt_tokens",
        "promptTokens",
        "input_token_count",
        "inputTokenCount",
    )
    output_tokens = _first_int(
        value,
        "output_tokens",
        "outputTokens",
        "completion_tokens",
        "completionTokens",
    )
    total_tokens = _first_int(value, "total_tokens", "totalTokens")
    if total_tokens <= 0 and (input_tokens or output_tokens):
        total_tokens = input_tokens + output_tokens
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "available": bool(input_tokens or output_tokens or total_tokens),
    }


def _first_int(mapping: dict[str, Any], *keys: str) -> int:
    for key in keys:
        value = mapping.get(key)
        try:
            number = int(value)
        except (TypeError, ValueError):
            continue
        if number > 0:
            return number
    return 0


def _model_supports_tools(model: str | BaseChatModel) -> bool:
    if not isinstance(model, BaseChatModel):
        return True
    return type(model).bind_tools is not BaseChatModel.bind_tools


def _filter_disabled_tools(tools: list[BaseTool], disabled_tools: tuple[str, ...]) -> list[BaseTool]:
    disabled = {str(name or "").strip() for name in disabled_tools if str(name or "").strip()}
    if not disabled:
        return tools
    return [tool for tool in tools if str(getattr(tool, "name", "") or "").strip() not in disabled]


def _with_provider_native_web_search(
    tools: list[AgentTool],
    request: AgentServiceRequest,
    *,
    model_config: AppConfig | None = None,
) -> list[AgentTool]:
    if not _native_web_search_requested(request.model_options):
        return tools
    provider = _provider_for_native_web_search(request, model_config=model_config)
    native_tool = _provider_native_web_search_tool(provider)
    if native_tool is None:
        return tools
    filtered = [tool for tool in tools if _tool_name(tool) != "web_search"]
    return [native_tool, *filtered]


def _provider_for_native_web_search(
    request: AgentServiceRequest,
    *,
    model_config: AppConfig | None = None,
) -> str:
    provider = ""
    if model_config is not None:
        provider, _model = _provider_model_names(model_config, fallback_provider=request.provider, fallback_model=request.model)
    if not provider:
        provider = request.provider
    return canonical_provider_name(provider or "") or str(provider or "").strip().lower()


def _provider_native_web_search_tool(provider: str) -> dict[str, Any] | None:
    if provider == "openai":
        return {"type": "web_search"}
    return None


def _native_web_search_requested(options: dict[str, Any] | None) -> bool:
    if not isinstance(options, dict):
        return False
    return _truthy(options.get("_paper_notes_native_web_search", options.get("_paper_notes_provider_native_web_search")))


def _file_generation_options(options: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(options, dict):
        return {}
    for key in ("_paper_notes_file_generation", "fileGeneration", "file_generation"):
        value = options.get(key)
        if isinstance(value, dict):
            return dict(value)
    return {}


def _image_generation_options(options: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(options, dict):
        return {}
    for key in ("_paper_notes_image_generation", "imageGeneration", "image_generation"):
        value = options.get(key)
        if isinstance(value, dict):
            return dict(value)
    return {}


def _attachments_from_options(options: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(options, dict):
        return []
    value = options.get("_paper_notes_attachments")
    return [dict(item) for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _image_generation_requested(options: dict[str, Any] | None) -> bool:
    if not isinstance(options, dict):
        return False
    for key in ("_paper_notes_image_generation", "imageGeneration", "image_generation"):
        value = options.get(key)
        if isinstance(value, dict) and value.get("enabled") is True:
            return True
    return False


def _file_generation_requested(options: dict[str, Any] | None) -> bool:
    if not isinstance(options, dict):
        return False
    for key in ("_paper_notes_file_generation", "fileGeneration", "file_generation"):
        value = options.get(key)
        if isinstance(value, dict) and value.get("enabled") is True:
            return True
    return False


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "enabled"}
    return False


def _tool_name(tool: AgentTool) -> str:
    if isinstance(tool, dict):
        function = tool.get("function") if isinstance(tool.get("function"), dict) else {}
        name = function.get("name") or tool.get("name") or tool.get("type")
    else:
        name = getattr(tool, "name", "")
    text = str(name or "").strip()
    return "web_search" if text.startswith("web_search_") else text


def _provider_reasoning_enabled(config: AppConfig) -> bool:
    try:
        options = ModelProviderConfig.from_app_config(config).options
    except Exception:
        return True
    return not _reasoning_options_disabled(options)


def _reasoning_options_disabled(options: dict[str, Any]) -> bool:
    thinking = options.get("thinking")
    if _thinking_option_disabled(thinking):
        return True
    reasoning = options.get("reasoning")
    if _reasoning_option_disabled(reasoning):
        return True
    if _off_text(options.get("summary")):
        return True
    if str(options.get("thinking_level") or "").strip().lower() == "minimal" and options.get("include_thoughts") is not True:
        return True
    for key in ("reasoning_effort", "effort", "thinking_level"):
        if _off_text(options.get(key)):
            return True
    if options.get("include_thoughts") is False:
        return True
    return False


def _thinking_option_disabled(value: Any) -> bool:
    if value is False or value is None:
        return value is False
    if isinstance(value, str):
        return _off_text(value)
    if isinstance(value, dict):
        return _off_text(value.get("type")) or _off_text(value.get("mode")) or value.get("enabled") is False
    return False


def _reasoning_option_disabled(value: Any) -> bool:
    if value is False or value is None:
        return value is False
    if isinstance(value, str):
        return _off_text(value)
    if isinstance(value, dict):
        return (
            _off_text(value.get("effort"))
            or _off_text(value.get("summary"))
            or _off_text(value.get("type"))
            or value.get("enabled") is False
        )
    return False


def _off_text(value: Any) -> bool:
    return str(value or "").strip().lower() in {"0", "false", "none", "off", "disabled", "disable"}


def _is_provider_reasoning_stream_event(event: AgentStreamEvent) -> bool:
    if event.event not in {"work_trace_item", "work_trace_delta"}:
        return False
    trace_type = str(event.data.get("traceType") or event.data.get("trace_type") or "").strip()
    if trace_type not in {"reasoning", "summary"}:
        return False
    data = event.data.get("data") if isinstance(event.data.get("data"), dict) else {}
    detail_type = str(data.get("type") or "").strip()
    return detail_type in {"reasoning", "reasoning_summary"} or str(event.data.get("source") or "").strip() in {
        "deepseek",
        "openai",
        "codex",
        "provider",
    }


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _isoformat_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _stamp_stream_event(event: AgentStreamEvent) -> None:
    event.data = dict(event.data)
    event.data.setdefault("at", _isoformat_utc(_now_utc()))


def _run_trace_event_from_stream_event(event: AgentStreamEvent) -> dict[str, Any] | None:
    if event.event not in {"work_trace_item", "work_trace_delta"}:
        return None
    data = dict(event.data)
    message = str(data.get("text") or data.get("delta") or "").strip()
    if not message:
        return None
    return {
        "type": event.event,
        "stage": str(data.get("traceType") or data.get("trace_type") or "").strip(),
        "message": message,
        "at": str(data.get("at") or "").strip(),
        "data": _json_safe(data),
    }


def _run_trace_has_equivalent_event(events: list[dict[str, Any]], candidate: dict[str, Any]) -> bool:
    candidate_message = str(candidate.get("message") or "").strip()
    candidate_stage = str(candidate.get("stage") or "").strip()
    candidate_source = str((candidate.get("data") if isinstance(candidate.get("data"), dict) else {}).get("source") or "").strip()
    for event in events:
        message = str(event.get("message") or "").strip()
        stage = str(event.get("stage") or "").strip()
        data = event.get("data") if isinstance(event.get("data"), dict) else {}
        source = str(data.get("source") or "").strip()
        if message == candidate_message and stage == candidate_stage and source == candidate_source:
            return True
    return False


def _new_messages_for_current_run(
    final_messages: list[BaseMessage],
    input_messages: list[BaseMessage],
) -> list[BaseMessage]:
    if len(final_messages) > len(input_messages):
        return final_messages[len(input_messages):]
    return final_messages[-1:] if final_messages else []


def _model_response_trace_events(messages: list[BaseMessage], *, at: datetime) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for turn, message in enumerate(messages, start=1):
        if not isinstance(message, AIMessage):
            continue
        web_search_data = _web_search_trace_data_from_message(message)
        if not web_search_data:
            continue
        call_count = int(web_search_data.get("web_search_call_count") or 0)
        source_count = int(web_search_data.get("web_search_source_count") or 0)
        source_text = (
            f" and {source_count} source{'s' if source_count != 1 else ''}"
            if source_count
            else ""
        )
        events.append({
            "type": "model_response",
            "stage": "model_response",
            "message": (
                "Model provider returned a response with "
                f"{call_count} web search call{'s' if call_count != 1 else ''}"
                f"{source_text}."
            ),
            "at": _isoformat_utc(at),
            "data": {
                "turn": turn,
                "source": _message_provider_name(message),
                **web_search_data,
            },
        })
    return events


def _web_search_trace_data_from_message(message: AIMessage) -> dict[str, Any]:
    calls: list[Any] = []
    sources: list[dict[str, str]] = []
    queries: list[str] = []
    seen_urls: set[str] = set()
    content_blocks = _message_content_blocks(message)
    for block in content_blocks:
        _collect_web_search_trace_from_block(block, calls=calls, sources=sources, queries=queries, seen_urls=seen_urls)
    additional_kwargs = getattr(message, "additional_kwargs", None)
    if isinstance(additional_kwargs, dict):
        for item in additional_kwargs.get("tool_outputs") or []:
            _collect_web_search_trace_from_block(item, calls=calls, sources=sources, queries=queries, seen_urls=seen_urls)
    if not calls:
        return {}
    data: dict[str, Any] = {"web_search_call_count": len(calls)}
    if sources:
        data["web_search_source_count"] = len(sources)
    if queries:
        data["web_search_queries"] = queries[:6]
    return data


def _message_content_blocks(message: AIMessage) -> list[Any]:
    content = getattr(message, "content", None)
    return content if isinstance(content, list) else []


def _collect_web_search_trace_from_block(
    block: Any,
    *,
    calls: list[Any],
    sources: list[dict[str, str]],
    queries: list[str],
    seen_urls: set[str],
) -> None:
    if not isinstance(block, dict):
        return
    block_type = str(block.get("type") or "").strip()
    name = str(block.get("name") or "").strip()
    if block_type == "web_search_call" or (block_type == "server_tool_use" and name == "web_search"):
        calls.append(block)
        _collect_web_search_queries(block, queries, set(queries), depth=0)
        _collect_sources_from_value(block, sources=sources, seen_urls=seen_urls)
    if block_type == "web_search_tool_result":
        _collect_sources_from_value(block, sources=sources, seen_urls=seen_urls)
    for annotation in block.get("annotations") or []:
        _collect_source_from_mapping(annotation, sources=sources, seen_urls=seen_urls)


def _collect_sources_from_value(value: Any, *, sources: list[dict[str, str]], seen_urls: set[str], depth: int = 0) -> None:
    if depth > 5:
        return
    if isinstance(value, dict):
        _collect_source_from_mapping(value, sources=sources, seen_urls=seen_urls)
        for item in value.values():
            _collect_sources_from_value(item, sources=sources, seen_urls=seen_urls, depth=depth + 1)
    elif isinstance(value, list):
        for item in value:
            _collect_sources_from_value(item, sources=sources, seen_urls=seen_urls, depth=depth + 1)


def _collect_source_from_mapping(value: dict[str, Any], *, sources: list[dict[str, str]], seen_urls: set[str]) -> None:
    url = str(value.get("url") or value.get("uri") or "").strip()
    if not url or url in seen_urls:
        return
    seen_urls.add(url)
    sources.append({
        "title": str(value.get("title") or "").strip(),
        "url": url,
        "snippet": str(value.get("snippet") or value.get("text") or "").strip(),
    })


def _collect_web_search_queries(value: Any, queries: list[str], seen: set[str], *, depth: int) -> None:
    if depth > 4 or len(queries) >= 6:
        return
    if isinstance(value, dict):
        for key, item in value.items():
            normalized_key = str(key or "").strip()
            if normalized_key in {"query", "queries", "search_query", "searchQuery", "webSearchQueries", "web_search_queries"}:
                _append_web_search_query(item, queries, seen)
                if len(queries) >= 6:
                    return
                continue
            _collect_web_search_queries(item, queries, seen, depth=depth + 1)
            if len(queries) >= 6:
                return
        return
    if isinstance(value, list):
        for item in value:
            _collect_web_search_queries(item, queries, seen, depth=depth + 1)
            if len(queries) >= 6:
                return


def _append_web_search_query(value: Any, queries: list[str], seen: set[str]) -> None:
    if isinstance(value, list):
        for item in value:
            _append_web_search_query(item, queries, seen)
            if len(queries) >= 6:
                return
        return
    if isinstance(value, dict):
        _collect_web_search_queries(value, queries, seen, depth=0)
        return
    text = " ".join(str(value or "").split())
    if not text:
        return
    if len(text) > 160:
        text = f"{text[:159]}..."
    key = text.casefold()
    if key in seen:
        return
    seen.add(key)
    queries.append(text)


def _message_provider_name(message: AIMessage) -> str:
    metadata = getattr(message, "response_metadata", None)
    if isinstance(metadata, dict):
        provider = str(metadata.get("model_provider") or "").strip()
        if provider:
            return provider
    return "provider"


def _work_trace_events_from_messages(
    messages: list[BaseMessage],
    *,
    include_provider_reasoning: bool = True,
) -> list[AgentStreamEvent]:
    events: list[AgentStreamEvent] = []
    for message in messages:
        if not isinstance(message, AIMessage):
            continue
        metadata = getattr(message, "response_metadata", None)
        trace_items: list[Any] = []
        if isinstance(metadata, dict):
            trace_keys = ["codex_work_trace"]
            if include_provider_reasoning:
                trace_keys.append("codex_model_trace")
            for key in trace_keys:
                value = metadata.get(key)
                if isinstance(value, list):
                    trace_items.extend(value)
        for item in trace_items:
            if not isinstance(item, dict):
                continue
            text = str(item.get("text") or item.get("delta") or "").strip()
            if not text:
                continue
            events.append(AgentStreamEvent("work_trace_item", {
                "text": text,
                "traceType": str(item.get("traceType") or item.get("trace_type") or "summary"),
                "source": str(item.get("source") or "codex"),
                "data": _json_safe(item.get("data") if isinstance(item.get("data"), dict) else item),
            }))
        reasoning_event = provider_reasoning_event_from_message(message) if include_provider_reasoning else None
        if reasoning_event is not None:
            events.append(reasoning_event)
    return _dedupe_work_trace_events(events)


def _dedupe_work_trace_events(events: list[AgentStreamEvent]) -> list[AgentStreamEvent]:
    deduped: list[AgentStreamEvent] = []
    seen: set[tuple[str, str, str]] = set()
    for event in events:
        key = (
            str(event.data.get("traceType") or ""),
            str(event.data.get("source") or ""),
            str(event.data.get("text") or event.data.get("delta") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(event)
    return deduped


def _run_trace_payload(
    request: AgentServiceRequest,
    *,
    started_at: datetime,
    finished_at: datetime,
    status: str,
    events: list[dict[str, Any]],
) -> dict[str, Any]:
    duration_ms = max(0, round((finished_at - started_at).total_seconds() * 1000))
    request_id = str(request.metadata.get("requestId") or request.metadata.get("request_id") or "").strip()
    return {
        "requestId": request_id,
        "startedAt": _isoformat_utc(started_at),
        "finishedAt": _isoformat_utc(finished_at),
        "durationMs": duration_ms,
        "status": status,
        "events": list(events),
    }


def _with_assistant_run_trace(messages: list[dict[str, Any]], run_trace: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not run_trace:
        return messages
    updated = [dict(message) for message in messages]
    for index in range(len(updated) - 1, -1, -1):
        if updated[index].get("role") == "assistant":
            updated[index]["runTrace"] = copy.deepcopy(run_trace)
            break
    return updated


def _merge_existing_transcript_fields(
    messages: list[dict[str, Any]],
    existing_messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not messages or not existing_messages:
        return messages
    merged: list[dict[str, Any]] = []
    for index, message in enumerate(messages):
        if index < len(existing_messages) and _transcript_messages_match(existing_messages[index], message):
            merged.append(_merge_transcript_message_fields(message, existing_messages[index]))
        else:
            merged.append(message)
    return merged


def _merge_transcript_message_fields(message: dict[str, Any], existing: dict[str, Any]) -> dict[str, Any]:
    merged = dict(message)
    for key, value in existing.items():
        if key == "metadata":
            existing_metadata = value if isinstance(value, dict) else {}
            message_metadata = merged.get("metadata") if isinstance(merged.get("metadata"), dict) else {}
            metadata = {**copy.deepcopy(existing_metadata), **copy.deepcopy(message_metadata)}
            if metadata:
                merged["metadata"] = metadata
            continue
        if key not in merged:
            merged[key] = copy.deepcopy(value)
    return merged


def _transcript_messages_match(existing: dict[str, Any], message: dict[str, Any]) -> bool:
    if _role_text(existing.get("role")) != _role_text(message.get("role")):
        return False
    existing_tool_call_id = str(existing.get("tool_call_id") or "")
    message_tool_call_id = str(message.get("tool_call_id") or "")
    if existing_tool_call_id or message_tool_call_id:
        return existing_tool_call_id == message_tool_call_id
    existing_tool_calls = existing.get("tool_calls") or []
    message_tool_calls = message.get("tool_calls") or []
    if existing_tool_calls or message_tool_calls:
        return existing_tool_calls == message_tool_calls
    return _content_text(existing.get("content")) == _content_text(message.get("content"))


def _with_generated_artifacts_on_latest_assistant(
    messages: list[dict[str, Any]],
    *,
    start_index: int,
) -> list[dict[str, Any]]:
    if not messages:
        return messages
    artifacts: list[dict[str, Any]] = []
    summaries: list[str] = []
    seen: set[str] = set()
    for message in messages[max(0, start_index):]:
        if message.get("role") != "tool":
            continue
        payload = _generated_artifact_tool_payload(message)
        if not payload:
            continue
        summary = _content_text(payload.get("summary"))
        if summary.strip():
            summaries.append(summary.strip())
        for artifact in _generated_artifacts_from_payload(payload):
            artifact_id = str(artifact.get("id") or artifact.get("artifactId") or "")
            if artifact_id and artifact_id in seen:
                continue
            if artifact_id:
                seen.add(artifact_id)
            artifacts.append(artifact)
    if not artifacts:
        return messages
    updated = [dict(message) for message in messages]
    for index in range(len(updated) - 1, max(-1, start_index - 1), -1):
        if updated[index].get("role") != "assistant" or updated[index].get("tool_calls"):
            continue
        updated[index] = _message_with_response_metadata_artifacts(updated[index], artifacts)
        updated[index] = _message_with_generated_artifact_fallback_content(updated[index], summaries, artifacts)
        break
    return updated


def _generated_artifacts_from_tool_message(message: dict[str, Any]) -> list[dict[str, Any]]:
    return _generated_artifacts_from_payload(_generated_artifact_tool_payload(message))


def _generated_artifact_tool_payload(message: dict[str, Any]) -> dict[str, Any]:
    if str(message.get("name") or "") not in {"create_file_artifact", "create_image_artifact"}:
        return {}
    payload = _tool_message_payload(message.get("content"))
    if not isinstance(payload, dict):
        return {}
    return payload


def _generated_artifacts_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    artifacts: list[dict[str, Any]] = []
    raw_artifacts = payload.get("artifacts")
    if isinstance(raw_artifacts, list):
        artifacts.extend(dict(item) for item in raw_artifacts if isinstance(item, dict))
    artifact = payload.get("artifact")
    if isinstance(artifact, dict):
        artifact_id = str(artifact.get("id") or artifact.get("artifactId") or "")
        if not artifact_id or all(str(item.get("id") or item.get("artifactId") or "") != artifact_id for item in artifacts):
            artifacts.append(dict(artifact))
    return artifacts


def _tool_message_payload(content: Any) -> dict[str, Any]:
    if isinstance(content, dict):
        return content
    if isinstance(content, list):
        for item in content:
            payload = _tool_message_payload(item)
            if payload:
                return payload
        return {}
    if not isinstance(content, str):
        return {}
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _message_with_response_metadata_artifacts(message: dict[str, Any], artifacts: list[dict[str, Any]]) -> dict[str, Any]:
    updated = dict(message)
    metadata = dict(updated.get("metadata") if isinstance(updated.get("metadata"), dict) else {})
    response_metadata = dict(metadata.get("response_metadata") if isinstance(metadata.get("response_metadata"), dict) else {})
    existing = response_metadata.get("artifacts")
    merged: list[dict[str, Any]] = [dict(item) for item in existing if isinstance(item, dict)] if isinstance(existing, list) else []
    seen = {str(item.get("id") or item.get("artifactId") or "") for item in merged if isinstance(item, dict)}
    for artifact in artifacts:
        artifact_id = str(artifact.get("id") or artifact.get("artifactId") or "")
        if artifact_id and artifact_id in seen:
            continue
        if artifact_id:
            seen.add(artifact_id)
        merged.append(dict(artifact))
    response_metadata["artifacts"] = merged
    metadata["response_metadata"] = response_metadata
    updated["metadata"] = metadata
    return updated


def _message_with_generated_artifact_fallback_content(
    message: dict[str, Any],
    summaries: list[str],
    artifacts: list[dict[str, Any]],
) -> dict[str, Any]:
    if _content_text(message.get("content")).strip():
        return message
    updated = dict(message)
    summary = next((item for item in summaries if item.strip()), "")
    if not summary:
        names = [
            str(artifact.get("fileName") or artifact.get("file_name") or "").strip()
            for artifact in artifacts
            if isinstance(artifact, dict)
        ]
        names = [name for name in names if name]
        summary = f"Created {', '.join(names)}." if names else "Created the requested artifact."
    updated["content"] = summary
    return updated


def _role_text(value: Any) -> str:
    return str(value or "").strip().lower()


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
        if not isinstance(chunk, dict):
            continue
        data = chunk.get("data") if chunk.get("type") == "values" else chunk
        if isinstance(data, dict) and isinstance(data.get("messages"), list):
            return [message for message in data["messages"] if isinstance(message, BaseMessage)]
        if chunk.get("type") == "updates" and isinstance(chunk.get("data"), dict):
            for update in reversed(list(chunk["data"].values())):
                if isinstance(update, dict) and isinstance(update.get("messages"), list):
                    messages = [message for message in update["messages"] if isinstance(message, BaseMessage)]
                    if messages:
                        return messages
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
    if additional_kwargs := _public_additional_kwargs(getattr(message, "additional_kwargs", None)):
        metadata["additional_kwargs"] = _json_safe(additional_kwargs)
    if getattr(message, "response_metadata", None):
        metadata["response_metadata"] = _json_safe(message.response_metadata)
    usage = getattr(message, "usage_metadata", None)
    if usage:
        metadata["usage"] = _json_safe(usage)
    return metadata


def _public_additional_kwargs(additional_kwargs: Any) -> dict[str, Any]:
    if not isinstance(additional_kwargs, dict):
        return {}
    hidden_keys = {"reasoning_content", "reasoning_details", "reasoning"}
    return {key: copy.deepcopy(value) for key, value in additional_kwargs.items() if key not in hidden_keys}


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, Enum):
        return _json_safe(value.value)
    if isinstance(value, dict):
        return {str(_json_safe(key)): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list | tuple | set):
        return [_json_safe(item) for item in value]
    if is_dataclass(value) and not isinstance(value, type):
        return _json_safe(asdict(value))
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        try:
            return _json_safe(model_dump(mode="json"))
        except TypeError:
            return _json_safe(model_dump())
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return _json_safe(to_dict())
    return str(value)


def _last_assistant_text(messages: list[BaseMessage]) -> str | None:
    for message in reversed(messages):
        if isinstance(message, AIMessage):
            return _content_text(message.content)
    return None


def _last_assistant_transcript_text(messages: list[dict[str, Any]]) -> str | None:
    for message in reversed(messages):
        if message.get("role") != "assistant" or message.get("tool_calls"):
            continue
        return _content_text(message.get("content"))
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


def _compact_messages_with_model(model: str | BaseChatModel, messages: list[BaseMessage], *, focus: str | None = None) -> str:
    if isinstance(model, str):
        from langchain.chat_models import init_chat_model

        model = init_chat_model(model)
    prompt = COMPACT_SUMMARY_PROMPT.format(summaries=get_buffer_string(messages)).rstrip()
    focus_text = str(focus or "").strip()
    if focus_text:
        prompt = (
            f"{prompt}\n\nCompaction focus requested by the user: {focus_text}\n"
            "Emphasize details relevant to this focus while preserving the required summary structure."
        )
    try:
        response = model.invoke(
            prompt,
            config={"metadata": {"lc_source": "manual_context_compaction"}},
        )
    except Exception as error:
        return f"Error compacting summaries: {error!s}"
    if hasattr(response, "content"):
        text = _content_text(getattr(response, "content", response))
    else:
        text_value = getattr(response, "text", None)
        text = text_value() if callable(text_value) else text_value
    return str(text or "").strip()


def _compacted_summary_transcript_message(summary: str) -> dict[str, Any]:
    return {
        "role": "user",
        "content": f"{SUMMARY_MESSAGE_PREFIX}\n\nCompacted conversation summary:\n\n{summary}".rstrip(),
        "metadata": {"source": "context_compaction"},
    }


def _context_compaction_marker_message(*, focus: str | None = None, warning: str | None = None) -> dict[str, Any]:
    metadata = {
        "type": "context_compaction_marker",
        "focus": str(focus or "").strip(),
        "warning": str(warning or "").strip(),
    }
    return {
        "role": "divider",
        "content": "Context compacted",
        "metadata": metadata,
    }


def _context_compaction_trace_event(
    event_type: str,
    message: str,
    *,
    at: datetime,
    session_id: str,
    provider: str,
    model: str,
    focus: str | None = None,
) -> dict[str, Any]:
    return {
        "type": event_type,
        "stage": event_type,
        "message": message,
        "at": _isoformat_utc(at),
        "data": {
            "sessionId": session_id,
            "provider": provider,
            "model": model,
            "focus": str(focus or "").strip(),
        },
    }


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


def _context_collapse_trigger_messages(config: AppConfig) -> int:
    for key in ("context_collapse.trigger_messages", "contextCollapse.triggerMessages"):
        value = config.get(key, None)
        if value is None:
            continue
        try:
            return max(1, int(value))
        except (TypeError, ValueError):
            continue
    return 40


def _context_collapse_trigger_tokens(config: AppConfig) -> int:
    for key in ("context_collapse.trigger_tokens", "contextCollapse.triggerTokens"):
        value = config.get(key, None)
        if value is None:
            continue
        try:
            return max(1, int(value))
        except (TypeError, ValueError):
            continue
    return 40_000


def _has_compactable_history(messages: list[BaseMessage]) -> bool:
    user_indices = [
        index
        for index, message in enumerate(messages)
        if isinstance(message, HumanMessage)
        and not (isinstance(message.content, str) and message.content.strip().startswith("[summary]"))
    ]
    return len(user_indices) >= 2 and user_indices[-2] > 0


def _manual_compaction_cutoff_index(messages: list[dict[str, Any]]) -> int | None:
    user_indices = [
        index
        for index, message in enumerate(messages)
        if _role_text(message.get("role")) == "user"
        and not _is_summary_transcript_message(message)
    ]
    if len(user_indices) < 2:
        return None
    cutoff = user_indices[-2]
    return cutoff if cutoff > 0 else None


def _is_summary_transcript_message(message: dict[str, Any]) -> bool:
    content = message.get("content", "")
    return isinstance(content, str) and content.strip().startswith(SUMMARY_MESSAGE_PREFIX)


def _model_visible_transcript_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [message for message in messages if _role_text(message.get("role")) != "divider"]


__all__ = [
    "ATTACHMENT_ONLY_MESSAGE",
    "AgentCompactResult",
    "AgentContextStatus",
    "AgentService",
    "AgentServiceRequest",
    "AgentServiceResult",
]
