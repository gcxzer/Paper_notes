"""说明：提供 Paper Notes agent 的核心服务层。

作用：串联会话、模型配置、工具、流式输出和持久化，是聊天 API 背后的主要协调者。
"""

from __future__ import annotations

import copy
from collections.abc import Generator, Iterator
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
)
from agent_runtime.messages import (
    ATTACHMENT_ONLY_MESSAGE,
    content_text,
    last_assistant_text,
    last_assistant_transcript_text,
    merge_existing_transcript_fields,
    messages_from_final_chunk,
    messages_from_transcript,
    messages_to_transcript,
    request_message_content,
)
from agent_runtime.recovery import (
    is_recoverable_model_request_error,
    messages_with_recovery_instruction,
    model_config_for_recovery,
    recovered_final_messages,
    run_agent_loop_with_recovery,
    short_exception_text,
)
from agent_runtime.request_config import (
    AgentTool,
    model_config_for_request,
    model_supports_tools,
    provider_model_names,
    provider_reasoning_enabled,
    tool_context_for_request,
)
from agent_runtime.run_trace import (
    AgentStreamEvent,
    LANGCHAIN_AGENT_STREAM_MODES,
    attach_run_trace_to_latest_assistant,
    finish_active_run_metadata,
    is_provider_reasoning_trace_event,
    now_utc,
    record_stream_event_in_active_run,
    save_active_run_metadata,
    stream_events_from_langchain_chunk,
    stream_final_trace_events_and_build_run_trace,
)
from agent_sessions import AgentSession, AgentSessionStore
from app_config import AppConfig, load_app_config
from middleware import SUMMARY_MESSAGE_PREFIX, compaction_trigger_tokens
from middleware.compaction import COMPACT_SUMMARY_PROMPT
from model_providers import create_chat_model, resolve_context_length_for_model
from tools import ToolContext, create_tools, filter_disabled_tools
from tools.generated_artifacts.payloads import (
    with_generated_artifacts_on_latest_assistant,
)

__all__ = [
    "ATTACHMENT_ONLY_MESSAGE",
    "AgentService",
    "AgentServiceRequest",
]


# 请求和结果对象
@dataclass(slots=True)
class AgentServiceRequest:
    """描述一次 agent 请求，包括会话、模型、工具和前端 metadata。"""

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
    """描述一次普通或流式 agent 请求完成后的最终结果。"""

    session_id: str
    session: AgentSession
    completed: bool
    response: str | None
    messages: list[dict[str, Any]]
    is_session_created: bool = False
    error: str | None = None
    chunks: list[Any] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    run_trace: dict[str, Any] | None = None


@dataclass(slots=True)
class AgentCompactResult:
    """描述一次上下文压缩操作的结果和压缩后的上下文状态。"""

    session_id: str
    session: AgentSession
    compressed: bool
    context: AgentContextStatus
    events: list[dict[str, Any]] = field(default_factory=list)
    warning: str = ""


@dataclass(slots=True)
class _PreparedAgentRun:
    """保存一次运行在真正调用模型前准备好的上下文。"""

    session: AgentSession
    is_session_created: bool
    model_config: AppConfig
    provider: str
    model_name: str
    model: str | BaseChatModel
    tools: list[AgentTool]
    paper_memory_context: dict[str, Any] | None
    input_messages: list[BaseMessage]
    started_at: Any
    run_events: list[dict[str, Any]] = field(default_factory=list)
    provider_reasoning_enabled: bool = False


# Agent 服务入口
class AgentService:
    """协调会话、模型、工具、流式事件、恢复重试和上下文压缩。"""

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
        """初始化 agent 服务依赖、工具上下文和可选 MCP 管理器。"""
        self.app_config = app_config or load_app_config()
        self.session_store = session_store or AgentSessionStore()
        self.chat_model = chat_model
        self.model_factory = model_factory or create_chat_model
        self.extra_tools = list(extra_tools) if extra_tools is not None else None
        self.use_default_tools = use_default_tools
        self.mcp_manager = None
        try:
            from tools.mcp import MCPManager, mcp_enabled

            if mcp_enabled():
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
        """执行一次非流式 agent 请求，并返回最终结果。"""
        run = self._prepare_agent_run(request)
        try:
            chunks, final_messages = run_agent_loop_with_recovery(
                run_agent_loop,
                self._chat_model,
                model=run.model,
                input_messages=run.input_messages,
                tools=run.tools,
                model_config=run.model_config,
                system_prompt=request.system_prompt,
                paper_memory_context=run.paper_memory_context,
                thread_id=run.session.metadata.session_id,
                run_config=request.run_config,
                stream_mode=request.stream_mode,
                provider=run.provider,
                model_name=run.model_name,
            )
        except BaseException as error:
            finish_active_run_metadata(
                self.session_store,
                run.session.metadata.session_id,
                request,
                status="failed",
                error_text=short_exception_text(error),
            )
            raise

        persisted_messages = self._persist_completed_messages(run, final_messages)
        response_text = last_assistant_text(final_messages) or last_assistant_transcript_text(persisted_messages)
        updated_session = self._mark_agent_run_completed(request, run, persisted_messages)
        return AgentServiceResult(
            session_id=run.session.metadata.session_id,
            session=updated_session,
            completed=True,
            response=response_text,
            messages=updated_session.messages,
            is_session_created=run.is_session_created,
            chunks=chunks,
        )

    def stream(self, request: AgentServiceRequest) -> Iterator[AgentStreamEvent]:
        """执行一次流式 agent 请求，持续产出进度、模型、trace 和最终事件。"""
        run = self._prepare_agent_run(request)
        chunks: list[Any] = []
        yield self._record_stream_status_event(request, run, "Starting agent run.")
        final_messages = yield from self._stream_model_events_with_recovery(request, run, chunks)
        finished_at = now_utc()
        run_trace = yield from stream_final_trace_events_and_build_run_trace(
            request,
            input_messages=run.input_messages,
            final_messages=final_messages,
            run_events=run.run_events,
            started_at=run.started_at,
            finished_at=finished_at,
            include_provider_reasoning=run.provider_reasoning_enabled,
        )
        persisted_messages = self._persist_completed_messages(run, final_messages, run_trace=run_trace)
        response_text = last_assistant_text(final_messages) or last_assistant_transcript_text(persisted_messages)
        updated_session = self._mark_agent_run_completed(request, run, persisted_messages)
        yield AgentStreamEvent("final", {
            "result": AgentServiceResult(
                session_id=run.session.metadata.session_id,
                session=updated_session,
                completed=True,
                response=response_text,
                messages=updated_session.messages,
                is_session_created=run.is_session_created,
                chunks=chunks,
                events=run.run_events,
                run_trace=run_trace,
            ),
        })

    def _prepare_agent_run(self, request: AgentServiceRequest) -> _PreparedAgentRun:
        """准备会话、模型、工具、记忆上下文，并持久化 activeRun 状态。"""
        if request.session_id:
            session = self.session_store.require_session(request.session_id)
            is_session_created = False
        else:
            initial_model_config = model_config_for_request(
                self.app_config,
                request,
                session=None,
                media_store=getattr(self._tool_context, "media_store", None),
            )
            provider, model_name = provider_model_names(
                initial_model_config,
                fallback_provider=request.provider,
                fallback_model=request.model,
            )
            session = self.session_store.create_session(
                title=request.title,
                note_id=request.note_id,
                provider=provider or None,
                model=model_name or None,
                metadata=request.metadata,
            )
            is_session_created = True
        model_config = model_config_for_request(
            self.app_config,
            request,
            session=session,
            media_store=getattr(self._tool_context, "media_store", None),
        )
        provider, model_name = provider_model_names(model_config, fallback_provider=request.provider, fallback_model=request.model)
        model = self._chat_model(model_config)
        tools = self._tools_for_request(
            request,
            model_config=model_config,
            session=session,
            model_supports_tools=model_supports_tools(model),
        )
        input_messages = [
            *messages_from_transcript(session.messages),
            HumanMessage(content=request_message_content(request)),
        ]
        session = save_active_run_metadata(
            self.session_store,
            session,
            request,
            input_messages=input_messages,
            provider=provider,
            model=model_name,
        )
        session_metadata = session.metadata.metadata if isinstance(session.metadata.metadata, dict) else {}
        request_metadata = request.metadata if isinstance(request.metadata, dict) else {}
        note_id = _first_text(
            request.note_id,
            session.metadata.note_id,
            *(request_metadata.get(key) for key in ("currentNoteId", "originNoteId")),
            *(session_metadata.get(key) for key in ("currentNoteId", "originNoteId")),
        )
        note_title = _first_text(
            *(request_metadata.get(key) for key in ("currentNoteTitle", "originNoteTitle")),
            *(session_metadata.get(key) for key in ("currentNoteTitle", "originNoteTitle")),
        )
        paper_memory_context = {
            "note_id": note_id,
            "note_title": note_title,
            "session_id": session.metadata.session_id,
        } if note_id else None
        return _PreparedAgentRun(
            session=session,
            is_session_created=is_session_created,
            model_config=model_config,
            provider=provider,
            model_name=model_name,
            model=model,
            tools=tools,
            paper_memory_context=paper_memory_context,
            input_messages=input_messages,
            started_at=now_utc(),
            provider_reasoning_enabled=provider_reasoning_enabled(model_config),
        )

    def _record_stream_status_event(
        self,
        request: AgentServiceRequest,
        run: _PreparedAgentRun,
        text: str,
    ) -> AgentStreamEvent:
        """创建运行时状态事件，并记录到流式进度里。"""
        event = AgentStreamEvent("work_trace_item", {
            "text": text,
            "traceType": "status",
            "source": "runtime",
        })
        record_stream_event_in_active_run(
            self.session_store,
            run.session.metadata.session_id,
            request,
            run.run_events,
            event,
        )
        return event

    def _stream_model_events_with_recovery(
        self,
        request: AgentServiceRequest,
        run: _PreparedAgentRun,
        chunks: list[Any],
    ) -> Generator[AgentStreamEvent, None, list[BaseMessage]]:
        """产出模型流式事件，并在可恢复错误时用降级配置重试一次。"""
        try:
            yield from self._stream_langchain_events(
                request,
                run,
                chunks=chunks,
                model=run.model,
                messages=run.input_messages,
                tools=run.tools,
                model_config=run.model_config,
            )
            return messages_from_final_chunk(chunks) or run.input_messages
        except Exception as error:
            if not is_recoverable_model_request_error(error):
                finish_active_run_metadata(
                    self.session_store,
                    run.session.metadata.session_id,
                    request,
                    status="failed",
                    error_text=short_exception_text(error),
                )
                raise
            yield self._record_stream_status_event(
                request,
                run,
                "Provider rejected an unsupported request option; asking the model to respond without that capability.",
            )
            recovery_config = model_config_for_recovery(run.model_config)
            recovery_messages = messages_with_recovery_instruction(
                run.input_messages,
                error,
                provider=run.provider,
                model=run.model_name,
            )
            chunks.clear()
            run.provider_reasoning_enabled = provider_reasoning_enabled(recovery_config)
            try:
                yield from self._stream_langchain_events(
                    request,
                    run,
                    chunks=chunks,
                    model=self._chat_model(recovery_config),
                    messages=recovery_messages,
                    tools=[],
                    model_config=recovery_config,
                )
            except BaseException as recovery_error:
                finish_active_run_metadata(
                    self.session_store,
                    run.session.metadata.session_id,
                    request,
                    status="failed",
                    error_text=short_exception_text(recovery_error),
                )
                raise
            return recovered_final_messages(chunks, recovery_messages, run.input_messages, error)
        except BaseException as error:
            finish_active_run_metadata(
                self.session_store,
                run.session.metadata.session_id,
                request,
                status="failed",
                error_text=short_exception_text(error),
            )
            raise

    def _stream_langchain_events(
        self,
        request: AgentServiceRequest,
        run: _PreparedAgentRun,
        *,
        chunks: list[Any],
        model: str | BaseChatModel,
        messages: list[BaseMessage],
        tools: list[AgentTool],
        model_config: AppConfig,
    ) -> Iterator[AgentStreamEvent]:
        """把 LangChain chunk 转成已过滤、已补时间戳的流式事件。"""
        for chunk in run_agent_loop(
            model,
            messages,
            tools=tools,
            app_config=model_config,
            system_prompt=request.system_prompt,
            paper_memory_context=run.paper_memory_context,
            thread_id=run.session.metadata.session_id,
            run_config=request.run_config,
            stream_mode=LANGCHAIN_AGENT_STREAM_MODES,
            stream_version="v2",
        ):
            chunks.append(chunk)
            for event in stream_events_from_langchain_chunk(chunk):
                if not run.provider_reasoning_enabled and is_provider_reasoning_trace_event(event):
                    continue
                record_stream_event_in_active_run(
                    self.session_store,
                    run.session.metadata.session_id,
                    request,
                    run.run_events,
                    event,
                )
                yield event

    def _persist_completed_messages(
        self,
        run: _PreparedAgentRun,
        final_messages: list[BaseMessage],
        *,
        run_trace: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """准备要保存的 transcript 消息，并按需附加 runTrace。"""
        persisted_messages = with_generated_artifacts_on_latest_assistant(
            messages_to_transcript(final_messages),
            start_index=max(0, len(run.session.messages) - 1),
        )
        persisted_messages = merge_existing_transcript_fields(
            persisted_messages,
            run.session.messages,
        )
        if run_trace is not None:
            persisted_messages = attach_run_trace_to_latest_assistant(persisted_messages, run_trace)
        return persisted_messages

    def _mark_agent_run_completed(
        self,
        request: AgentServiceRequest,
        run: _PreparedAgentRun,
        persisted_messages: list[dict[str, Any]],
    ) -> AgentSession:
        """保存最终消息，关闭 activeRun，并持久化本次模型选择。"""
        self.session_store.replace_messages(run.session.metadata.session_id, persisted_messages)
        finish_active_run_metadata(self.session_store, run.session.metadata.session_id, request, status="completed")
        return self.session_store.update_session_model(
            run.session.metadata.session_id,
            provider=run.provider or None,
            model=run.model_name or None,
        )

    def context_status(
        self,
        *,
        session_id: str,
        provider: str = "",
        model: str = "",
        enable_tools: bool = True,
    ) -> AgentContextStatus:
        """计算指定会话当前的上下文窗口、token 和压缩状态。"""
        session = self.session_store.require_session(session_id)
        request = AgentServiceRequest(
            message="",
            session_id=session_id,
            provider=provider,
            model=model,
            enable_tools=enable_tools,
        )
        model_config = model_config_for_request(
            self.app_config,
            request,
            session=session,
            media_store=getattr(self._tool_context, "media_store", None),
        )
        provider_name, model_name = provider_model_names(model_config, fallback_provider=provider, fallback_model=model)
        context_window = resolve_context_length_for_model(provider_name, model_name)
        reserve_tokens = context_reserve_tokens(model_config)
        trigger_tokens = compaction_trigger_tokens(context_window, reserve_tokens)
        collapse_trigger_messages = context_collapse_trigger_messages(model_config)
        collapse_trigger_tokens = context_collapse_trigger_tokens(model_config)
        messages = messages_from_transcript(session.messages)
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
        """把会话历史压缩成 summary 消息，并返回新的上下文状态。"""
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
        model_config = model_config_for_request(
            self.app_config,
            request,
            session=session,
            media_store=getattr(self._tool_context, "media_store", None),
        )
        provider_name, model_name = provider_model_names(model_config, fallback_provider=provider, fallback_model=model)
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

        raw_messages_to_compact = [
            message
            for message in session.messages[:cutoff_index]
            if str(message.get("role") or "").strip().lower() != "divider"
        ]
        messages_to_compact = messages_from_transcript(raw_messages_to_compact)
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

        started_at = now_utc()
        start_event = {
            "type": "context_compressing",
            "stage": "context_compressing",
            "message": "Compacting session context.",
            "at": started_at.isoformat(),
            "data": {
                "sessionId": session.metadata.session_id,
                "provider": provider_name,
                "model": model_name,
                "focus": str(focus or "").strip(),
            },
        }
        summary = _compact_messages_with_model(self._chat_model(model_config), messages_to_compact, focus=focus)
        summary_message = {
            "role": "summary",
            "content": f"{SUMMARY_MESSAGE_PREFIX}\n\nCompacted conversation summary:\n\n{summary}".rstrip(),
            "metadata": {"source": "context_compaction"},
        }
        marker_metadata = {
            "type": "context_compaction_marker",
            "focus": str(focus or "").strip(),
            "warning": "",
        }
        marker = {
            "role": "divider",
            "content": "Context compacted",
            "metadata": marker_metadata,
        }
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
        finished_at = now_utc()
        done_event = {
            "type": "context_compressed",
            "stage": "context_compressed",
            "message": "Context compacted.",
            "at": finished_at.isoformat(),
            "data": {
                "sessionId": session.metadata.session_id,
                "provider": provider_name,
                "model": model_name,
                "focus": str(focus or "").strip(),
            },
        }
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

    def _chat_model(self, model_config: AppConfig) -> str | BaseChatModel:
        """返回注入的测试模型，或按配置创建真实聊天模型。"""
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
        """根据请求和模型能力创建可用工具列表。"""
        if not request.enable_tools:
            return []
        context = tool_context_for_request(
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
        return filter_disabled_tools(tools, tuple(request.disabled_tools or ()))

    def close(self) -> None:
        """关闭服务持有的 MCP 管理器资源。"""
        manager = self.mcp_manager
        self.mcp_manager = None
        shutdown = getattr(manager, "shutdown", None)
        if callable(shutdown):
            shutdown()


# 上下文压缩模型调用
def _compact_messages_with_model(model: str | BaseChatModel, messages: list[BaseMessage], *, focus: str | None = None) -> str:
    """调用模型把历史消息压缩成一段 summary 文本。"""
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
        text = content_text(getattr(response, "content", response))
    else:
        text_value = getattr(response, "text", None)
        text = text_value() if callable(text_value) else text_value
    return str(text or "").strip()


# 通用文本 helper
def _first_text(*values: Any) -> str:
    """返回一组值里的第一个非空文本。"""
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""
