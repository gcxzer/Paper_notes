"""Coordinate agent requests, sessions, context, transcript updates, and retries."""

from __future__ import annotations

import copy
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import (
    BaseMessage,
    get_buffer_string,
    HumanMessage,
)
from langchain_core.messages.utils import count_tokens_approximately

from agent_runtime.agent_loop import run_agent_loop
from agent_runtime.context_status import (
    AgentContextStatus,
    context_collapse_trigger_messages,
    context_collapse_trigger_tokens,
    context_reserve_tokens,
    has_compactable_history,
    latest_usage_from_transcript,
    manual_compaction_cutoff_index,
    model_visible_transcript_messages,
)
from agent_runtime.messages import (
    ATTACHMENT_ONLY_MESSAGE,
    content_text as _content_text,
    last_assistant_text as _last_assistant_text,
    last_assistant_transcript_text as _last_assistant_transcript_text,
    merge_existing_transcript_fields as _merge_existing_transcript_fields,
    messages_from_final_chunk as _messages_from_final_chunk,
    messages_from_transcript as _messages_from_transcript,
    messages_to_transcript as _messages_to_transcript,
    request_message_content as _request_message_content,
)
from agent_runtime.recovery import (
    is_recoverable_model_request_error as _is_recoverable_model_request_error,
    messages_with_recovery_instruction as _messages_with_recovery_instruction,
    model_config_for_recovery as _model_config_for_recovery,
    recovered_final_messages as _recovered_final_messages,
    run_agent_loop_with_recovery as _run_agent_loop_with_recovery,
    short_exception_text as _short_exception_text,
)
from agent_runtime.request_config import (
    AgentTool,
    model_config_for_request as _request_model_config,
    model_supports_tools as _model_supports_tools,
    provider_model_names as _provider_model_names,
    provider_reasoning_enabled as _provider_reasoning_enabled,
    tool_context_for_request as _tool_context_for_request,
)
from agent_runtime.run_trace import (
    context_compaction_trace_event as _context_compaction_trace_event,
    finish_active_run as _finish_active_run,
    is_provider_reasoning_stream_event as _is_provider_reasoning_stream_event,
    isoformat_utc as _isoformat_utc,
    model_response_trace_events,
    new_messages_for_current_run as _new_messages_for_current_run,
    now_utc as _now_utc,
    persist_active_run as _persist_active_run,
    run_trace_event_from_stream_event as _run_trace_event_from_stream_event,
    run_trace_has_equivalent_event as _run_trace_has_equivalent_event,
    run_trace_payload as _run_trace_payload,
    stamp_stream_event as _stamp_stream_event,
    update_active_run_progress as _update_active_run_progress,
    with_assistant_run_trace as _with_assistant_run_trace,
    work_trace_events_from_messages as _work_trace_events_from_messages,
)
from agent_runtime.streaming import (
    AgentStreamEvent,
    LANGCHAIN_AGENT_STREAM_MODES,
    events_from_langchain_chunk,
)
from agent_sessions import AgentSession, AgentSessionStore
from app_config import AppConfig, load_app_config
from middleware import SUMMARY_MESSAGE_PREFIX, compaction_trigger_tokens
from middleware.compaction import COMPACT_SUMMARY_PROMPT
from model_providers import create_chat_model, resolve_context_length_for_model
from tools import ToolContext, create_tools, filter_disabled_tools as _filter_disabled_tools
from tools.generated_artifacts.payloads import (
    with_generated_artifacts_on_latest_assistant,
)


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


class AgentService:
    def __init__(
        self,
        *,
        app_config: AppConfig | None = None,
        session_store: AgentSessionStore | None = None,
        chat_model: str | BaseChatModel | None = None,
        model_factory: Any | None = None,
        extra_tools: list[AgentTool] | None = None,
        use_default_tools: bool = True,
        library_path: Path | None = None,
        annotations_dir: Path | None = None,
        html_dir: Path | None = None,
        papers_dir: Path | None = None,
        paper_visual_cache_dir: Path | None = None,
        media_store: Any | None = None,
    ) -> None:
        self.app_config = app_config or load_app_config()
        self.session_store = session_store or AgentSessionStore()
        self.chat_model = chat_model
        self.model_factory = model_factory or create_chat_model
        self.extra_tools = list(extra_tools) if extra_tools is not None else None
        self.use_default_tools = use_default_tools
        self.mcp_manager = None
        if self.use_default_tools:
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
            paper_visual_cache_dir=paper_visual_cache_dir,
            media_store=media_store,
            mcp_manager=self.mcp_manager,
        )

    def run(self, request: AgentServiceRequest) -> AgentServiceResult:
        session, created_session = self._session_for_request(request)
        model_config = self._model_config_for_request(request, session=session)
        provider, model_name = _provider_model_names(model_config, fallback_provider=request.provider, fallback_model=request.model)
        model = self._chat_model(model_config)
        tools = self._tools_for_request(
            request,
            model_config=model_config,
            session=session,
            model_supports_tools=_model_supports_tools(model),
        )
        paper_memory_context = self._paper_memory_context_for_request(request, session=session)
        input_messages = [
            *_messages_from_transcript(session.messages),
            HumanMessage(content=_request_message_content(request)),
        ]
        session = _persist_active_run(
            self.session_store,
            session,
            request,
            input_messages=input_messages,
            provider=provider,
            model=model_name,
        )

        try:
            chunks, final_messages = _run_agent_loop_with_recovery(
                run_agent_loop,
                self._chat_model,
                model=model,
                input_messages=input_messages,
                tools=tools,
                model_config=model_config,
                system_prompt=request.system_prompt,
                paper_memory_context=paper_memory_context,
                thread_id=session.metadata.session_id,
                run_config=request.run_config,
                stream_mode=request.stream_mode,
                provider=provider,
                model_name=model_name,
            )
        except BaseException as error:
            _finish_active_run(
                self.session_store,
                session.metadata.session_id,
                request,
                status="failed",
                error_text=_short_exception_text(error),
            )
            raise
        persisted_messages = with_generated_artifacts_on_latest_assistant(
            _messages_to_transcript(final_messages),
            start_index=max(0, len(session.messages) - 1),
        )
        persisted_messages = _merge_existing_transcript_fields(
            persisted_messages,
            session.messages,
        )
        response_text = _last_assistant_text(final_messages) or _last_assistant_transcript_text(persisted_messages)
        updated_session = self.session_store.replace_messages(session.metadata.session_id, persisted_messages)
        _finish_active_run(self.session_store, session.metadata.session_id, request, status="completed")
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
        tools = self._tools_for_request(
            request,
            model_config=model_config,
            session=session,
            model_supports_tools=_model_supports_tools(model),
        )
        paper_memory_context = self._paper_memory_context_for_request(request, session=session)
        input_messages = [
            *_messages_from_transcript(session.messages),
            HumanMessage(content=_request_message_content(request)),
        ]
        session = _persist_active_run(
            self.session_store,
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
        _update_active_run_progress(
            self.session_store,
            session.metadata.session_id,
            request,
            events=run_events,
            status="running",
        )
        yield start_event
        try:
            for chunk in run_agent_loop(
                model,
                input_messages,
                tools=tools,
                app_config=model_config,
                system_prompt=request.system_prompt,
                paper_memory_context=paper_memory_context,
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
                        _update_active_run_progress(
                            self.session_store,
                            session.metadata.session_id,
                            request,
                            events=run_events,
                            status="running",
                        )
                    yield event
            final_messages = _messages_from_final_chunk(chunks) or input_messages
        except Exception as error:
            if not _is_recoverable_model_request_error(error):
                _finish_active_run(
                    self.session_store,
                    session.metadata.session_id,
                    request,
                    status="failed",
                    error_text=_short_exception_text(error),
                )
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
                _update_active_run_progress(
                    self.session_store,
                    session.metadata.session_id,
                    request,
                    events=run_events,
                    status="running",
                )
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
                    paper_memory_context=paper_memory_context,
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
                            _update_active_run_progress(
                                self.session_store,
                                session.metadata.session_id,
                                request,
                                events=run_events,
                                status="running",
                            )
                        yield event
            except BaseException as recovery_error:
                _finish_active_run(
                    self.session_store,
                    session.metadata.session_id,
                    request,
                    status="failed",
                    error_text=_short_exception_text(recovery_error),
                )
                raise
            final_messages = _recovered_final_messages(chunks, recovery_messages, input_messages, error)
        except BaseException as error:
            _finish_active_run(
                self.session_store,
                session.metadata.session_id,
                request,
                status="failed",
                error_text=_short_exception_text(error),
            )
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
        for trace_event in model_response_trace_events(
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
        persisted_messages = with_generated_artifacts_on_latest_assistant(
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
        _finish_active_run(self.session_store, session.metadata.session_id, request, status="completed")
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
        reserve_tokens = context_reserve_tokens(model_config)
        trigger_tokens = compaction_trigger_tokens(context_window, reserve_tokens)
        collapse_trigger_messages = context_collapse_trigger_messages(model_config)
        collapse_trigger_tokens = context_collapse_trigger_tokens(model_config)
        messages = _messages_from_transcript(session.messages)
        tools = self._tools_for_request(request, model_config=model_config)
        message_tokens = count_tokens_approximately(messages)
        total_tokens = count_tokens_approximately(messages, tools=tools)
        tool_tokens = max(0, total_tokens - message_tokens)
        actual_usage = latest_usage_from_transcript(session.messages)
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
            compaction_ready=total_tokens >= trigger_tokens and has_compactable_history(messages),
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
        cutoff_index = manual_compaction_cutoff_index(session.messages)
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

        raw_messages_to_compact = model_visible_transcript_messages(session.messages[:cutoff_index])
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
        return _request_model_config(
            self.app_config,
            request,
            session=session,
            media_store=getattr(self._tool_context, "media_store", None),
        )

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
        model_supports_tools: bool = True,
    ) -> list[AgentTool]:
        if not request.enable_tools:
            return []
        context = _tool_context_for_request(
            self._tool_context,
            request,
            model_config=model_config,
            session=session,
            model_supports_tools=model_supports_tools,
        )
        if not context.model_supports_tools:
            return []
        tools: list[AgentTool] = []
        if self.use_default_tools:
            tools.extend(create_tools(context))
        if self.extra_tools is not None:
            tools.extend(self.extra_tools)
        return _filter_disabled_tools(tools, tuple(request.disabled_tools or ()))

    def _paper_memory_context_for_request(
        self,
        request: AgentServiceRequest,
        *,
        session: AgentSession,
    ) -> dict[str, Any] | None:
        note_id, note_title = _paper_memory_note_scope(request, session)
        if not note_id:
            return None
        return {
            "note_id": note_id,
            "note_title": note_title,
            "session_id": session.metadata.session_id,
        }

    def close(self) -> None:
        manager = self.mcp_manager
        self.mcp_manager = None
        shutdown = getattr(manager, "shutdown", None)
        if callable(shutdown):
            shutdown()

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


def _paper_memory_note_scope(request: AgentServiceRequest, session: AgentSession) -> tuple[str, str]:
    metadata = session.metadata.metadata if isinstance(session.metadata.metadata, dict) else {}
    request_metadata = request.metadata if isinstance(request.metadata, dict) else {}
    note_id = _first_text(
        request.note_id,
        session.metadata.note_id,
        _scoped_metadata_text(request_metadata, "currentNoteId", "originNoteId"),
        _scoped_metadata_text(metadata, "currentNoteId", "originNoteId"),
    )
    note_title = _first_text(
        _scoped_metadata_text(request_metadata, "currentNoteTitle", "originNoteTitle"),
        _scoped_metadata_text(metadata, "currentNoteTitle", "originNoteTitle"),
    )
    return note_id, note_title


def _scoped_metadata_text(metadata: dict[str, Any], *keys: str) -> str:
    return _first_text(*(metadata.get(key) for key in keys))


def _first_text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _compacted_summary_transcript_message(summary: str) -> dict[str, Any]:
    return {
        "role": "summary",
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



__all__ = [
    "ATTACHMENT_ONLY_MESSAGE",
    "AgentCompactResult",
    "AgentContextStatus",
    "AgentService",
    "AgentServiceRequest",
    "AgentServiceResult",
]
