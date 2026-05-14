from __future__ import annotations

import threading
import json
from dataclasses import dataclass, field
from datetime import datetime
import os
from pathlib import Path
from typing import Any

from context_compression import (
    ContextCompressionCheckpoint,
    ContextCompressionCheckpointStore,
    ContextCompressionConfig,
    ContextCompressor,
    LLMContextSummaryProvider,
    estimate_messages_tokens_rough,
    estimate_request_tokens_rough,
    estimate_tokens_rough,
    is_context_overflow_error,
    resolve_context_length_for_model,
)
from agent_memory import MemoryManager, create_local_memory_manager
from agent_prompts import AgentPromptContext, build_agent_instructions
from agent_runtime import AgentEvent, AgentEventSink, AgentRunControl, AgentRunRequest, AgentRunResult, AgentRunner
from agent_sessions import AgentSession, AgentSessionMetadata, AgentSessionStore, SessionNotFoundError
from tool_safety import PaperNotesSnapshotManager, ToolApprovalManager, ToolApprovalNotFoundError, ToolSnapshotError
from app_config.secrets import default_env_paths, default_secrets_path, parse_env_file
from app_config.ai_settings import resolve_ai_settings, resolve_model_for_provider
from media import MediaStore, MediaStoreError
from model_providers import (
    ModelRequest,
    ModelProvider,
    ModelProviderAPIError,
    ModelProviderError,
    ResolvedModelProvider,
    ToolCall,
    normalize_model_provider_name,
    resolve_model_provider,
)
from model_providers.profiles import get_provider_profile
from tools.catalog import ToolCatalog, ToolCatalogSnapshot, ToolSelection
from tools.code_execution import TOOL_NAME as EXECUTE_CODE_TOOL
from tools.code_execution import register_code_execution_tool
from tools.code_execution.tool import schema_with_dynamic_description as execute_code_schema_with_dynamic_description
from tools.executor import ToolExecutorAdapter
from tools.generated_files import TOOL_NAME as CREATE_FILE_ARTIFACT_TOOL, register_generated_file_tool
from tools.generated_images import TOOL_NAME as CREATE_IMAGE_ARTIFACT_TOOL, register_generated_image_tool
from tools.paper_notes import create_paper_notes_registry
from tools.persistent_memory import create_persistent_memory_tool_definition
from tools.persistent_memory.manifest import TOOL_GROUP as PERSISTENT_MEMORY_TOOL_GROUP
from tools.registry import ToolRegistry
from tools.result_storage import ToolResultStore
from tools.session_search import register_session_search_tool
from tools.skills import register_skills_tools
from tools.todo import SessionTodoStore, register_todo_tool
from tools.web_fetch import register_web_fetch_tool
from tools.web_search import register_web_search_tool


MODEL_VISIBLE_ROLES = {"user", "assistant", "tool", "system", "developer"}


@dataclass(slots=True)
class AgentServiceRequest:
    message: Any
    session_id: str | None = None
    request_id: str = ""
    title: str = "New chat"
    note_id: str | None = None
    provider: str = ""
    model: str = ""
    context: AgentPromptContext | dict[str, Any] | None = None
    extra_instructions: str | None = None
    enable_tools: bool = True
    toolset: str | None = None
    enabled_toolsets: list[str] | None = None
    disabled_toolsets: list[str] = field(default_factory=list)
    disabled_tools: list[str] = field(default_factory=list)
    tool_write_modes: dict[str, str] = field(default_factory=dict)
    write_tool_mode: str = "auto"
    max_turns: int = 90
    max_output_tokens: int | None = None
    request_options: dict[str, Any] = field(default_factory=dict)
    attachments: list[dict[str, Any]] = field(default_factory=list)
    image_generation: dict[str, Any] = field(default_factory=dict)
    file_generation: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    edit_latest_user_message: bool = False
    enable_compression: bool = True
    compression_focus: str | None = None
    summarize_on_max_turns: bool = True
    budget_warnings_enabled: bool = True
    stream_events_enabled: bool = True
    event_sink: AgentEventSink | None = field(default=None, repr=False)
    control: AgentRunControl | None = field(default=None, repr=False)

@dataclass(slots=True)
class AgentServiceResult:
    session_id: str
    session: AgentSession
    completed: bool
    response: str | None
    messages: list[dict[str, Any]]
    events: list[AgentEvent] = field(default_factory=list)
    turns: int = 0
    pending_tool_calls: list[ToolCall] = field(default_factory=list)
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
    cancelled: bool = False
    created_session: bool = False

@dataclass(slots=True)
class AgentCompactResult:
    session_id: str
    session: AgentSession
    compressed: bool
    context: "AgentContextStatus"
    events: list[AgentEvent] = field(default_factory=list)
    warning: str | None = None

@dataclass(slots=True)
class AgentContextStatus:
    provider: str
    model: str
    context_length: int
    request_tokens: int
    message_tokens: int
    instruction_tokens: int
    tool_schema_tokens: int
    threshold_tokens: int
    message_count: int
    compaction_enabled: bool
    compression_count: int = 0
    last_compressed_at: str = ""
    summary_available: bool = False
    last_compression_error: str | None = None
    fallback_used: bool = False

    @property
    def percent_full(self) -> int:
        if self.context_length <= 0:
            return 0
        return min(100, max(0, round((self.request_tokens / self.context_length) * 100)))

    @property
    def threshold_percent(self) -> int:
        if self.context_length <= 0:
            return 0
        return min(100, max(0, round((self.threshold_tokens / self.context_length) * 100)))

class AgentService:
    def __init__(
        self,
        *,
        model_provider: ModelProvider | None = None,
        session_store: AgentSessionStore | None = None,
        tool_registry: ToolRegistry | None = None,
        tool_catalog: ToolCatalog | None = None,
        provider_name: str = "",
        provider_kwargs: dict[str, Any] | None = None,
        default_model: str = "",
        use_default_tools: bool = True,
        memory_manager: MemoryManager | None = None,
        use_memory: bool = True,
        memory_path: str | Path | None = None,
        use_session_search: bool = True,
        context_compressor: ContextCompressor | None = None,
        use_compression: bool = True,
        compression_config: ContextCompressionConfig | None = None,
        compression_checkpoint_store: ContextCompressionCheckpointStore | None = None,
        tool_snapshot_manager: PaperNotesSnapshotManager | None = None,
        tool_approval_manager: ToolApprovalManager | None = None,
        tool_result_store: ToolResultStore | None = None,
        media_store: MediaStore | None = None,
    ) -> None:
        self._model_provider = model_provider
        self.session_store = session_store or AgentSessionStore()
        self.media_store = media_store or MediaStore(self.session_store.sessions_root.parent / "media")
        self._tool_context = threading.local()
        custom_tool_registry = tool_registry is not None
        self._use_default_toolsets = use_default_tools and not custom_tool_registry
        self.tool_registry = tool_registry if tool_registry is not None else (
            create_paper_notes_registry(
                media_store=self.media_store,
                paper_image_analyzer=self._analyze_paper_image_tool,
            ) if use_default_tools else ToolRegistry()
        )
        self.memory_manager = self._create_memory_manager(
            memory_manager=memory_manager,
            use_memory=use_memory,
            memory_path=memory_path,
            custom_tool_registry=custom_tool_registry,
        )
        self._register_persistent_memory_tools()
        if use_session_search and self._use_default_toolsets:
            register_session_search_tool(
                self.tool_registry,
                session_store=self.session_store,
                current_session_id_provider=self._current_tool_session_id,
            )
        self.todo_store = (
            SessionTodoStore(self.session_store, current_session_id_provider=self._current_tool_session_id)
            if self._use_default_toolsets
            else None
        )
        self._register_todo_tool()
        if self._use_default_toolsets:
            register_skills_tools(self.tool_registry)
            register_web_search_tool(self.tool_registry)
            register_web_fetch_tool(self.tool_registry)
            register_code_execution_tool(
                self.tool_registry,
                available_tool_names_provider=self._current_tool_available_names,
                cancel_check_provider=self._current_tool_cancelled,
            )
            register_generated_file_tool(
                self.tool_registry,
                media_store=self.media_store,
                session_id_provider=self._current_tool_session_id,
                provider_name_provider=self._current_tool_provider_name,
                model_provider=self._current_tool_model,
                file_generation_provider=self._current_tool_file_generation,
            )
            register_generated_image_tool(
                self.tool_registry,
                media_store=self.media_store,
                session_id_provider=self._current_tool_session_id,
                provider_name_provider=self._current_tool_provider_name,
                model_provider=self._current_tool_model,
                image_generation_provider=self._current_tool_image_generation,
                attachment_provider=self._current_tool_attachments,
            )
        self.tool_catalog = tool_catalog or ToolCatalog(self.tool_registry)
        self.provider_name = provider_name
        self.provider_kwargs = dict(provider_kwargs or {})
        self.default_model = default_model
        self.context_compressor = context_compressor if context_compressor is not None else (
            ContextCompressor(compression_config) if use_compression else None
        )
        self._auto_configure_summary_provider = (
            self.context_compressor is not None
            and getattr(self.context_compressor, "summary_provider", None) is None
        )
        self.compression_checkpoint_store = compression_checkpoint_store or ContextCompressionCheckpointStore(
            self.session_store.sessions_root.parent / "compression"
        )
        self.tool_snapshot_manager = tool_snapshot_manager or PaperNotesSnapshotManager(
            self.session_store.sessions_root.parent / "snapshots"
        )
        self.tool_approval_manager = tool_approval_manager or ToolApprovalManager(
            self.session_store.sessions_root.parent / "approvals"
        )
        self.tool_result_store = tool_result_store or ToolResultStore(
            self.session_store.sessions_root.parent / "logs" / "tool-results"
        )

    def context_status_fuc(
        self,
        *,
        session_id: str | None = None,
        provider: str = "",
        model: str = "",
        context: AgentPromptContext | dict[str, Any] | None = None,
        extra_instructions: str | None = None,
        enable_tools: bool = True,
        toolset: str | None = None,
        enabled_toolsets: list[str] | tuple[str, ...] | None = None,
        disabled_toolsets: list[str] | tuple[str, ...] | None = None,
        note_id: str | None = None,
    ) -> AgentContextStatus:
        """Collect and return a read-only context compression snapshot for a chat session.

        This method computes current model context usage and recent compression state
        without mutating session state. It resolves provider/model selection, loads
        and applies a valid compression checkpoint, rebuilds instruction context
        (tools, memory, todo), and estimates request token usage.
        """
        session = self.session_store.get_session(session_id) if session_id else None
        if session_id and session is None:
            raise SessionNotFoundError(session_id)

        provider_name, model_name = self._resolve_context_status_selection(
            provider=provider,
            model=model,
            metadata=session.metadata if session is not None else None,
        )
        tools = self._tool_schemas_for_selection(
            enable_tools=enable_tools,
            toolset=toolset,
            enabled_toolsets=enabled_toolsets,
            disabled_toolsets=disabled_toolsets,
            disabled_tools=None,
            tool_write_modes=None,
            write_tool_mode="auto",
        )
        raw_messages = _model_visible_messages(session.messages if session is not None else [])
        checkpoint = self._load_valid_compression_checkpoint(
            session.metadata.session_id if session is not None else "",
            raw_messages,
        ) if session is not None else None
        messages, _ = self._model_messages_with_checkpoint(raw_messages, checkpoint)
        messages = _strip_internal_compression_metadata(messages)
        runtime_messages = [_runtime_context_message(
            datetime.now().astimezone(),
            session_id=session.metadata.session_id if session is not None else "",
            provider=provider_name,
            model=model_name,
        )]
        messages_for_estimate = [*runtime_messages, *messages]
        prompt_context = self._context_with_session_title(context, session.metadata) if session is not None else context
        memory_context = self._memory_context_for_status(
            messages,
            session_id=session.metadata.session_id if session is not None else "",
            note_id=note_id or (session.metadata.note_id if session is not None else ""),
        )
        todo_context = self._todo_context(session.metadata.session_id if session is not None else "")
        instructions = build_agent_instructions(
            tools=tools,
            context=prompt_context,
            extra_instructions=extra_instructions,
            model=model_name,
            memory_context=memory_context,
            todo_context=todo_context,
            native_web_search_enabled=False,
        )
        context_length = resolve_context_length_for_model(provider_name, model_name)
        instruction_tokens = estimate_tokens_rough(instructions)
        tool_schema_tokens = estimate_request_tokens_rough([], tools=tools)
        message_tokens = estimate_messages_tokens_rough(messages_for_estimate)
        request_tokens = estimate_request_tokens_rough(messages_for_estimate, instructions=instructions, tools=tools)
        compression_config = self.context_compressor.config if self.context_compressor is not None else ContextCompressionConfig()
        return AgentContextStatus(
            provider=provider_name,
            model=model_name,
            context_length=context_length,
            request_tokens=request_tokens,
            message_tokens=message_tokens,
            instruction_tokens=instruction_tokens,
            tool_schema_tokens=tool_schema_tokens,
            threshold_tokens=compression_config.resolved_threshold_tokens(context_length=context_length),
            message_count=len(messages),
            compaction_enabled=self.context_compressor is not None,
            compression_count=checkpoint.compression_count if checkpoint is not None else 0,
            last_compressed_at=checkpoint.updated_at if checkpoint is not None else "",
            summary_available=checkpoint.summary_available if checkpoint is not None else False,
            last_compression_error=checkpoint.last_error if checkpoint is not None else None,
            fallback_used=checkpoint.fallback_used if checkpoint is not None else False,
        )

    def run(self, request: AgentServiceRequest) -> AgentServiceResult:
        run_started_at = datetime.now().astimezone()
        normalized_attachments = self._normalize_attachments(request.attachments)
        if isinstance(request.message, str) and not request.message.strip() and not normalized_attachments:
            raise ValueError("AgentServiceRequest.message must not be empty.")
        if request.edit_latest_user_message and not request.session_id:
            raise ValueError("editLatestUserMessage requires an existing session.")

        session, created_session = self._get_or_create_session(request)
        if request.edit_latest_user_message:
            if created_session:
                raise ValueError("editLatestUserMessage requires an existing session.")
            previous_attachments = _last_user_message_attachments(session.messages)
            session, removed_count = self.session_store.undo_last_turn(session.metadata.session_id)
            if removed_count <= 0:
                raise ValueError("No user message is available to edit.")
            if not normalized_attachments:
                normalized_attachments = previous_attachments
        selection = self._resolve_model_selection(request, session.metadata)
        self._configure_compression_summary_provider(selection)
        session = self._persist_model_selection(session, request, selection)
        user_message = {
            "role": "user",
            "content": "" if request.message is None else request.message,
            "metadata": dict(request.metadata),
        }
        if normalized_attachments:
            user_message["attachments"] = normalized_attachments
        session = self.session_store.append_message(session.metadata.session_id, user_message)

        tool_snapshot = self._tool_catalog_snapshot(request)
        tools = self._tools_for_request(request, tool_snapshot=tool_snapshot)
        tool_selection_events = _tool_selection_warning_events(tool_snapshot)
        for event in tool_selection_events:
            _emit_service_event(event, request.event_sink)
        note_id = self._note_id_for_request(request, session.metadata)
        memory_context = self._memory_context(request, session.metadata.session_id, note_id=note_id)
        todo_context = self._todo_context(session.metadata.session_id)
        instructions = build_agent_instructions(
            tools=tools,
            context=self._context_with_session_title(request.context, session.metadata),
            extra_instructions=_combine_extra_instructions(
                request.extra_instructions,
                _attachment_instructions(normalized_attachments),
                _generation_mode_instructions(request),
            ),
            model=selection.model,
            memory_context=memory_context,
            todo_context=todo_context,
            native_web_search_enabled=_native_web_search_requested(request.request_options),
        )
        raw_model_messages = _model_visible_messages(session.messages)
        checkpoint = self._load_valid_compression_checkpoint(session.metadata.session_id, raw_model_messages)
        model_messages, checkpoint_applied = self._model_messages_with_checkpoint(raw_model_messages, checkpoint)
        context_length = resolve_context_length_for_model(selection.provider_name, selection.model)
        model_messages, pre_events, compressed_input = self._prepare_model_messages(
            model_messages,
            request,
            session_id=session.metadata.session_id,
            raw_message_count=len(raw_model_messages),
            instructions=instructions,
            tools=tools,
            context_length=context_length,
        )
        compressed_input = compressed_input or checkpoint_applied
        request.request_options = self._model_request_options(
            request,
            session_id=session.metadata.session_id,
            provider_name=selection.provider_name,
            media_store=self.media_store,
        )
        ephemeral_messages = [
            _runtime_context_message(
                run_started_at,
                session_id=session.metadata.session_id,
                provider=selection.provider_name,
                model=selection.model,
            )
        ]
        attachment_context = _attachment_context_message(normalized_attachments, self.media_store)
        if attachment_context:
            ephemeral_messages.append(attachment_context)
        request.request_options["_paper_notes_ephemeral_messages"] = ephemeral_messages

        runner = AgentRunner(
            selection.provider,
            tool_executor=ToolExecutorAdapter(
                self.tool_registry,
                snapshot_manager=self.tool_snapshot_manager,
                approval_manager=self.tool_approval_manager,
                session_id_provider=self._current_tool_session_id,
                request_id=request.request_id,
                write_mode=request.write_tool_mode,
                disabled_tools=sorted({*request.disabled_tools, *tool_snapshot.disabled_tools, *tool_snapshot.hidden_tools}),
                tool_write_modes=tool_snapshot.tool_write_modes,
                event_sink=request.event_sink,
                control=request.control,
                result_store=self.tool_result_store,
            ) if tools else None,
            event_sink=request.event_sink,
        )
        self._set_tool_context(
            session.metadata.session_id,
            provider=selection.provider,
            provider_name=selection.provider_name,
            model=selection.model,
            file_generation=_normalize_file_generation_config(request.file_generation),
            image_generation=_normalize_image_generation_config(request.image_generation),
            attachments=normalized_attachments,
            available_tool_names=_tool_names_from_model_tools(tools),
            control=request.control,
        )
        try:
            run_result, model_messages, retry_events, compressed_input = self._run_with_context_recovery(
                runner,
                request,
                model=selection.model,
                messages=model_messages,
                instructions=instructions,
                tools=tools,
                context_length=context_length,
                compressed_input=compressed_input,
                session_id=session.metadata.session_id,
                raw_message_count=len(raw_model_messages),
            )
        finally:
            self._clear_tool_context()
        self._update_compressor_usage(run_result)
        all_pre_events = [*tool_selection_events, *pre_events, *retry_events]
        if all_pre_events:
            run_result.events = [*all_pre_events, *run_result.events]
        _attach_tool_activity(
            run_result.messages,
            run_result.events,
            session_id=session.metadata.session_id,
        )
        _attach_run_trace(
            run_result.messages,
            run_result.events,
            request_id=request.request_id,
            started_at=run_started_at,
            finished_at=datetime.now().astimezone(),
            status=_run_trace_status(run_result),
            error=run_result.error,
        )
        _attach_work_trace(
            run_result.messages,
            run_result.events,
            status=_run_trace_status(run_result),
        )
        _attach_result_artifacts(run_result.messages, run_result.artifacts)
        persisted_session = self._persist_run_messages(
            session,
            run_result,
            model_input_count=len(model_messages),
            compressed_input=compressed_input,
        )
        self._sync_memory_after_run(request, run_result, persisted_session.metadata, note_id=note_id)
        return _service_result(
            session=persisted_session,
            run_result=run_result,
            created_session=created_session,
        )

    def restore_tool_snapshot(self, *, session_id: str, snapshot_id: str, force: bool = False) -> dict[str, Any]:
        self.session_store.require_session(session_id)
        try:
            return self.tool_snapshot_manager.restore(session_id=session_id, snapshot_id=snapshot_id, force=force)
        except ToolSnapshotError:
            raise

    def redo_tool_snapshot(self, *, session_id: str, snapshot_id: str, force: bool = False) -> dict[str, Any]:
        self.session_store.require_session(session_id)
        try:
            return self.tool_snapshot_manager.redo(session_id=session_id, snapshot_id=snapshot_id, force=force)
        except ToolSnapshotError:
            raise

    def preview_tool_snapshot(self, *, session_id: str, snapshot_id: str, max_chars: int = 16_000) -> dict[str, Any]:
        self.session_store.require_session(session_id)
        try:
            return self.tool_snapshot_manager.preview_diff(
                session_id=session_id,
                snapshot_id=snapshot_id,
                max_chars=max_chars,
            )
        except ToolSnapshotError:
            raise

    def list_tool_snapshots(self, *, session_id: str, limit: int = 50) -> list[dict[str, Any]]:
        self.session_store.require_session(session_id)
        return self.tool_snapshot_manager.list_snapshots(session_id=session_id, limit=limit)

    def cleanup_tool_snapshots(
        self,
        *,
        session_id: str | None = None,
        keep_per_session: int = 50,
        max_age_days: int | None = None,
    ) -> dict[str, Any]:
        if session_id:
            self.session_store.require_session(session_id)
        return self.tool_snapshot_manager.cleanup(
            session_id=session_id,
            keep_per_session=keep_per_session,
            max_age_days=max_age_days,
        )

    def list_tool_approvals(self, *, session_id: str | None = None) -> list[dict[str, Any]]:
        if session_id:
            self.session_store.require_session(session_id)
        return self.tool_approval_manager.list_pending(session_id=session_id)

    def respond_tool_approval(self, *, approval_id: str, action: str, message: str = "") -> dict[str, Any]:
        try:
            record = self.tool_approval_manager.respond(approval_id, action, message=message)
        except ToolApprovalNotFoundError:
            raise
        return record.to_public_dict()

    def compact_session(
        self,
        *,
        session_id: str,
        focus: str | None = None,
        provider: str = "",
        model: str = "",
        context: AgentPromptContext | dict[str, Any] | None = None,
        extra_instructions: str | None = None,
        enable_tools: bool = True,
        toolset: str | None = None,
        enabled_toolsets: list[str] | tuple[str, ...] | None = None,
        disabled_toolsets: list[str] | tuple[str, ...] | None = None,
        note_id: str | None = None,
        event_sink: AgentEventSink | None = None,
    ) -> AgentCompactResult:
        if self.context_compressor is None:
            raise ValueError("Context compression is not enabled.")
        session = self.session_store.require_session(session_id)
        selection = self._resolve_model_selection(
            AgentServiceRequest(message="compact", session_id=session_id, provider=provider, model=model),
            session.metadata,
        )
        self._configure_compression_summary_provider(selection)
        session = self._persist_model_selection(
            session,
            AgentServiceRequest(message="compact", session_id=session_id, provider=provider, model=model),
            selection,
        )
        tools = self._tool_schemas_for_selection(
            enable_tools=enable_tools,
            toolset=toolset,
            enabled_toolsets=enabled_toolsets,
            disabled_toolsets=disabled_toolsets,
            disabled_tools=None,
            tool_write_modes=None,
            write_tool_mode="auto",
        )
        raw_messages = _model_visible_messages(session.messages)
        checkpoint = self._load_valid_compression_checkpoint(session.metadata.session_id, raw_messages)
        model_messages, checkpoint_applied = self._model_messages_with_checkpoint(raw_messages, checkpoint)
        context_length = resolve_context_length_for_model(selection.provider_name, selection.model)
        prompt_context = self._context_with_session_title(context, session.metadata)
        memory_context = self._memory_context_for_status(
            raw_messages,
            session_id=session.metadata.session_id,
            note_id=note_id or session.metadata.note_id or "",
        )
        todo_context = self._todo_context(session.metadata.session_id)
        instructions = build_agent_instructions(
            tools=tools,
            context=prompt_context,
            extra_instructions=extra_instructions,
            model=selection.model,
            memory_context=memory_context,
            todo_context=todo_context,
            native_web_search_enabled=False,
        )
        start_event = AgentEvent(
            "context_compressing",
            "Compacting session context.",
            {
                "session_id": session.metadata.session_id,
                "focus": str(focus or ""),
                "provider": selection.provider_name,
                "model": selection.model,
            },
        )
        _emit_service_event(start_event, event_sink)
        compressed_messages, events, compressed = self._compress_model_messages(
            model_messages,
            AgentServiceRequest(
                message="compact",
                session_id=session_id,
                provider=selection.provider_name,
                model=selection.model,
                compression_focus=focus,
                event_sink=event_sink,
            ),
            session_id=session.metadata.session_id,
            raw_message_count=len(raw_messages),
            instructions=instructions,
            tools=tools,
            context_length=context_length,
            reason="manual",
            force=True,
            max_passes=1,
        )
        del compressed_messages
        context_status = self.context_status_fuc(
            session_id=session.metadata.session_id,
            provider=selection.provider_name,
            model=selection.model,
            context=prompt_context,
            extra_instructions=extra_instructions,
            enable_tools=enable_tools,
            toolset=toolset,
            enabled_toolsets=enabled_toolsets,
            disabled_toolsets=disabled_toolsets,
            note_id=note_id,
        )
        warning = _compact_warning(events, context_status)
        all_events = [start_event, *events]
        if warning and not any(event.type == "context_compression_warning" for event in events):
            warning_event = AgentEvent("context_compression_warning", warning, {"session_id": session.metadata.session_id})
            _emit_service_event(warning_event, event_sink)
            all_events.append(warning_event)
        if compressed or checkpoint_applied:
            session = self.session_store.append_message(
                session.metadata.session_id,
                _context_compaction_marker_message(focus=focus, warning=warning),
            )
        return AgentCompactResult(
            session_id=session.metadata.session_id,
            session=session,
            compressed=compressed or checkpoint_applied,
            context=context_status,
            events=all_events,
            warning=warning,
        )

    def _get_or_create_session(self, request: AgentServiceRequest) -> tuple[AgentSession, bool]:
        if request.session_id:
            session = self.session_store.get_session(request.session_id)
            if session is None:
                raise SessionNotFoundError(request.session_id)
            return session, False

        return self.session_store.create_session(
            title=request.title,
            note_id=request.note_id,
            provider=_clean_provider(request.provider or self.provider_name) or None,
            model=request.model or self.default_model or None,
            metadata=dict(request.metadata),
        ), True

    def _tool_schemas(self, request: AgentServiceRequest) -> list[dict[str, Any]]:
        return self._tool_catalog_snapshot(request).model_tools

    def _tool_catalog_snapshot(self, request: AgentServiceRequest) -> ToolCatalogSnapshot:
        return self._tool_catalog_snapshot_for_selection(
            enable_tools=request.enable_tools,
            toolset=request.toolset,
            enabled_toolsets=request.enabled_toolsets,
            disabled_toolsets=request.disabled_toolsets,
            disabled_tools=request.disabled_tools,
            tool_write_modes=request.tool_write_modes,
            write_tool_mode=request.write_tool_mode,
        )

    def _tools_for_request(
        self,
        request: AgentServiceRequest,
        *,
        tool_snapshot: ToolCatalogSnapshot | None = None,
    ) -> list[dict[str, Any]]:
        tools = (tool_snapshot.model_tools if tool_snapshot is not None else self._tool_schemas(request))
        image_generation = _normalize_image_generation_config(request.image_generation)
        file_generation = _normalize_file_generation_config(request.file_generation)
        next_tools = list(tools)
        if file_generation.get("enabled") and not _has_function_tool(next_tools, CREATE_FILE_ARTIFACT_TOOL):
            next_tools.extend(self.tool_registry.get_definitions({CREATE_FILE_ARTIFACT_TOOL}, quiet=True))
        if image_generation.get("enabled") and not _has_function_tool(next_tools, CREATE_IMAGE_ARTIFACT_TOOL):
            next_tools.extend(self.tool_registry.get_definitions({CREATE_IMAGE_ARTIFACT_TOOL}, quiet=True))
        return self._with_dynamic_execute_code_description(next_tools)

    def _with_dynamic_execute_code_description(self, tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        visible_tool_names = _tool_names_from_model_tools(tools)
        if EXECUTE_CODE_TOOL not in visible_tool_names:
            return tools
        return [
            execute_code_schema_with_dynamic_description(
                tool,
                registry=self.tool_registry,
                visible_tool_names=visible_tool_names,
            )
            for tool in tools
        ]

    def _tool_schemas_for_selection(
        self,
        *,
        enable_tools: bool,
        toolset: str | None = None,
        enabled_toolsets: list[str] | tuple[str, ...] | None = None,
        disabled_toolsets: list[str] | tuple[str, ...] | None = None,
        disabled_tools: list[str] | tuple[str, ...] | None = None,
        tool_write_modes: dict[str, str] | None = None,
        write_tool_mode: str = "auto",
    ) -> list[dict[str, Any]]:
        return self._tool_catalog_snapshot_for_selection(
            enable_tools=enable_tools,
            toolset=toolset,
            enabled_toolsets=enabled_toolsets,
            disabled_toolsets=disabled_toolsets,
            disabled_tools=disabled_tools,
            tool_write_modes=tool_write_modes,
            write_tool_mode=write_tool_mode,
        ).model_tools

    def _tool_catalog_snapshot_for_selection(
        self,
        *,
        enable_tools: bool,
        toolset: str | None = None,
        enabled_toolsets: list[str] | tuple[str, ...] | None = None,
        disabled_toolsets: list[str] | tuple[str, ...] | None = None,
        disabled_tools: list[str] | tuple[str, ...] | None = None,
        tool_write_modes: dict[str, str] | None = None,
        write_tool_mode: str = "auto",
    ) -> ToolCatalogSnapshot:
        if not enable_tools:
            return ToolCatalogSnapshot(groups=tuple(self.tool_catalog.describe_groups()), generation=self.tool_registry.generation)
        selection = ToolSelection.from_values(
            enable_tools=enable_tools,
            toolset=toolset,
            enabled_toolsets=enabled_toolsets,
            disabled_toolsets=disabled_toolsets,
            disabled_tools=disabled_tools,
            tool_write_modes=tool_write_modes,
            write_tool_mode=write_tool_mode,
            default_toolsets=("default",) if self._use_default_toolsets else None,
        )
        return self.tool_catalog.resolve(selection)

    def _filter_tool_names_by_tool_settings(
        self,
        tool_names: set[str],
        *,
        disabled_tools: set[str],
        tool_write_modes: dict[str, str],
    ) -> set[str]:
        if not disabled_tools and not tool_write_modes:
            return tool_names
        selected = set(tool_names)
        selected.difference_update(disabled_tools)
        for name, mode in tool_write_modes.items():
            definition = self.tool_registry.get(name)
            if definition is not None and definition.mutating and mode in {"readonly", "block", "halt"}:
                selected.discard(name)
        return selected

    def _memory_context(self, request: AgentServiceRequest, session_id: str, *, note_id: str) -> str:
        if self.memory_manager is None:
            return ""
        return self.memory_manager.prefetch(
            str(request.message),
            session_id=session_id,
            note_id=note_id,
        )

    def _memory_context_for_status(self, messages: list[dict[str, Any]], *, session_id: str, note_id: str) -> str:
        if self.memory_manager is None or not session_id:
            return ""
        query = _last_user_message_text(messages)
        if not query:
            return ""
        return self.memory_manager.prefetch(query, session_id=session_id, note_id=note_id)

    def _sync_memory_after_run(
        self,
        request: AgentServiceRequest,
        run_result: AgentRunResult,
        metadata: AgentSessionMetadata,
        *,
        note_id: str,
    ) -> None:
        if self.memory_manager is None or not run_result.completed or run_result.cancelled or not run_result.final_response:
            return
        self.memory_manager.sync_turn(
            str(request.message),
            run_result.final_response,
            session_id=metadata.session_id,
            note_id=note_id,
            metadata={
                "source": "agent_service",
                **dict(request.metadata),
            },
        )

    def _prepare_model_messages(
        self,
        messages: list[dict[str, Any]],
        request: AgentServiceRequest,
        *,
        session_id: str,
        raw_message_count: int,
        instructions: str,
        tools: list[dict[str, Any]],
        context_length: int,
    ) -> tuple[list[dict[str, Any]], list[AgentEvent], bool]:
        if self.context_compressor is None or not request.enable_compression:
            return messages, [], False
        return self._compress_model_messages(
            messages,
            request,
            session_id=session_id,
            raw_message_count=raw_message_count,
            instructions=instructions,
            tools=tools,
            context_length=context_length,
            reason="preflight",
            force=False,
            max_passes=self.context_compressor.config.max_preflight_passes,
        )

    def _run_with_context_recovery(
        self,
        runner: AgentRunner,
        request: AgentServiceRequest,
        *,
        model: str,
        messages: list[dict[str, Any]],
        instructions: str,
        tools: list[dict[str, Any]],
        context_length: int,
        compressed_input: bool,
        session_id: str,
        raw_message_count: int,
    ) -> tuple[AgentRunResult, list[dict[str, Any]], list[AgentEvent], bool]:
        retry_events: list[AgentEvent] = []
        attempts = 0
        max_retries = self.context_compressor.config.max_overflow_retries if self.context_compressor else 0
        while True:
            try:
                result = runner.run(AgentRunRequest(
                    model=model,
                    messages=messages,
                    instructions=instructions,
                    tools=tools,
                    max_turns=request.max_turns,
                    max_output_tokens=request.max_output_tokens,
                    request_options=request.request_options,
                    control=request.control,
                    summarize_on_max_turns=request.summarize_on_max_turns,
                    budget_warnings_enabled=request.budget_warnings_enabled,
                    stream_events_enabled=request.stream_events_enabled,
                ))
                return result, messages, retry_events, compressed_input
            except ModelProviderAPIError as error:
                if (
                    self.context_compressor is None
                    or not request.enable_compression
                    or not is_context_overflow_error(error)
                    or attempts >= max_retries
                ):
                    raise
                attempts += 1
                overflow_event = AgentEvent(
                    "context_overflow",
                    "Model provider reported context overflow; compressing and retrying.",
                    {
                        "attempt": attempts,
                        "max_retries": max_retries,
                        "status_code": error.status_code,
                        "context_length": context_length,
                    },
                )
                _emit_service_event(overflow_event, request.event_sink)
                compressed_messages, compression_events, did_compress = self._compress_model_messages(
                    messages,
                    request,
                    session_id=session_id,
                    raw_message_count=raw_message_count,
                    instructions=instructions,
                    tools=tools,
                    context_length=context_length,
                    reason="context_overflow",
                    force=True,
                    max_passes=1,
                    attempt=attempts,
                )
                retry_events.extend([overflow_event, *compression_events])
                if not did_compress:
                    raise
                messages = compressed_messages
                compressed_input = True

    def _compress_model_messages(
        self,
        messages: list[dict[str, Any]],
        request: AgentServiceRequest,
        *,
        session_id: str,
        raw_message_count: int,
        instructions: str,
        tools: list[dict[str, Any]],
        context_length: int,
        reason: str,
        force: bool,
        max_passes: int,
        attempt: int | None = None,
    ) -> tuple[list[dict[str, Any]], list[AgentEvent], bool]:
        if self.context_compressor is None:
            return messages, [], False

        current = messages
        events: list[AgentEvent] = []
        compressed = False
        threshold = self.context_compressor.config.resolved_threshold_tokens(context_length=context_length)
        for pass_index in range(1, max(1, max_passes) + 1):
            current_for_compression = _ensure_raw_transcript_indexes(current)
            before_request_tokens = estimate_request_tokens_rough(
                current_for_compression,
                instructions=instructions,
                tools=tools,
            )
            before_message_count = len(current_for_compression)
            result = self.context_compressor.compress(
                current_for_compression,
                approx_tokens=before_request_tokens,
                focus_topic=request.compression_focus,
                context_length=context_length,
                force=force,
            )
            if not result.stats.compressed:
                current = _strip_internal_compression_metadata(result.messages)
                break

            after_request_tokens = estimate_request_tokens_rough(result.messages, 
                                                                 instructions=instructions, tools=tools)
            event = _compression_event(
                result,
                reason=reason,
                pass_index=pass_index,
                attempt=attempt,
                context_length=context_length,
                before_request_tokens=before_request_tokens,
                after_request_tokens=after_request_tokens,
            )
            _emit_service_event(event, request.event_sink)
            events.append(event)
            for warning_event in _compression_warning_events(result):
                _emit_service_event(warning_event, request.event_sink)
                events.append(warning_event)
            self._save_compression_checkpoint(
                session_id=session_id,
                source_messages=current_for_compression,
                result=result,
                raw_message_count=raw_message_count,
            )
            compressed = True
            current = result.messages
            if force or after_request_tokens < threshold or len(result.messages) >= before_message_count:
                break
        return _strip_internal_compression_metadata(current), events, compressed

    def _model_messages_with_checkpoint(
        self,
        messages: list[dict[str, Any]],
        checkpoint: ContextCompressionCheckpoint | None,
    ) -> tuple[list[dict[str, Any]], bool]:
        if self.context_compressor is None or checkpoint is None:
            return messages, False
        indexed_messages = _with_raw_transcript_indexes(messages)
        compressed = self.context_compressor.apply_checkpoint(indexed_messages, checkpoint)
        if compressed == indexed_messages:
            return messages, False
        return compressed, True

    def _load_valid_compression_checkpoint(
        self,
        session_id: str,
        messages: list[dict[str, Any]],
    ) -> ContextCompressionCheckpoint | None:
        if self.context_compressor is None or not session_id:
            return None
        checkpoint = self.compression_checkpoint_store.load(session_id)
        if checkpoint is None or not checkpoint.summary_available:
            return None
        if checkpoint.compressed_until_message_index <= self.context_compressor.config.protect_first_n:
            return None
        if checkpoint.compressed_until_message_index > len(messages):
            return None
        if checkpoint.source_message_count and len(messages) < checkpoint.source_message_count:
            return None
        return checkpoint

    def _save_compression_checkpoint(
        self,
        *,
        session_id: str,
        source_messages: list[dict[str, Any]],
        result: Any,
        raw_message_count: int,
    ) -> None:
        if self.context_compressor is None or not session_id or not result.summary:
            return
        metadata = dict(result.stats.metadata or {})
        turns_start = int(metadata.get("turns_start") or metadata.get("compress_start") or 0)
        turns_end = int(metadata.get("turns_end") or metadata.get("compress_end") or 0)
        raw_indexes = [
            index
            for index in (
                _internal_raw_transcript_index(message)
                for message in source_messages[max(0, turns_start) : max(0, turns_end)]
            )
            if index is not None
        ]
        existing = self.compression_checkpoint_store.load(session_id)
        previous_until = existing.compressed_until_message_index if existing is not None else 0
        compressed_until = max(previous_until, max(raw_indexes) + 1 if raw_indexes else previous_until)
        if compressed_until <= 0:
            return
        summary_body = self.context_compressor._strip_summary_prefix(result.summary)
        checkpoint = ContextCompressionCheckpoint(
            session_id=session_id,
            previous_summary=summary_body,
            compressed_until_message_index=compressed_until,
            source_message_count=raw_message_count,
            compression_count=int(metadata.get("compression_count") or ((existing.compression_count if existing else 0) + 1)),
            last_error=metadata.get("summary_error"),
            fallback_used=bool(metadata.get("summary_fallback_used")),
            last_savings_pct=float(metadata.get("savings_pct") or 0.0),
            updated_at=datetime.now().astimezone().isoformat(timespec="seconds"),
        )
        self.compression_checkpoint_store.save(checkpoint)

    def _configure_compression_summary_provider(self, selection: ResolvedModelProvider) -> None:
        if self.context_compressor is None or not self._auto_configure_summary_provider:
            return
        summary_provider_name = _compression_setting("PAPER_NOTES_COMPRESSION_PROVIDER")
        summary_model = _compression_setting("PAPER_NOTES_COMPRESSION_MODEL")
        summary_provider = selection.provider
        resolved_summary_model = summary_model or selection.model
        fallback_provider: ModelProvider | None = None
        fallback_model = ""

        if summary_provider_name:
            try:
                normalized = _clean_provider(summary_provider_name)
                if normalized and normalized != selection.provider_name:
                    resolved = self._get_model_provider(provider_name=normalized, model=resolved_summary_model)
                    summary_provider = resolved.provider
                    resolved_summary_model = summary_model or resolved.model
                    fallback_provider = selection.provider
                    fallback_model = selection.model
            except Exception:
                summary_provider = selection.provider
                resolved_summary_model = selection.model
                fallback_provider = None
                fallback_model = ""

        self.context_compressor.summary_provider = LLMContextSummaryProvider(
            summary_provider,
            model=resolved_summary_model,
            fallback_provider=fallback_provider,
            fallback_model=fallback_model,
        )

    def _persist_run_messages(
        self,
        session: AgentSession,
        run_result: AgentRunResult,
        *,
        model_input_count: int,
        compressed_input: bool,
    ) -> AgentSession:
        if not compressed_input:
            return self.session_store.replace_messages(session.metadata.session_id, run_result.messages)

        generated_messages = run_result.messages[model_input_count:]
        persisted = session
        for message in generated_messages:
            persisted = self.session_store.append_message(session.metadata.session_id, message)
        return persisted

    def _update_compressor_usage(self, run_result: AgentRunResult) -> None:
        if self.context_compressor is not None and run_result.usage is not None:
            self.context_compressor.update_from_response(run_result.usage)

    def _resolve_model_selection(
        self,
        request: AgentServiceRequest,
        metadata: AgentSessionMetadata,
    ) -> ResolvedModelProvider:
        model = request.model or metadata.model or self.default_model
        if self._model_provider is not None:
            provider_name = _clean_provider_for_injected(request.provider or metadata.provider or self.provider_name)
            return ResolvedModelProvider(
                provider=self._model_provider,
                provider_name=provider_name or getattr(self._model_provider, "name", "") or self.provider_name,
                model=model,
            )
        provider_name = _clean_provider(request.provider or metadata.provider or self.provider_name)
        return self._get_model_provider(provider_name=provider_name, model=model)

    def _resolve_context_status_selection(
        self,
        *,
        provider: str = "",
        model: str = "",
        metadata: AgentSessionMetadata | None = None,
    ) -> tuple[str, str]:
        settings = resolve_ai_settings()
        provider_name = _clean_provider_for_injected(
            provider or (metadata.provider if metadata is not None else "") or self.provider_name or settings.provider
        )
        provider_name = provider_name or settings.provider
        model_name = str(
            model
            or (metadata.model if metadata is not None else "")
            or self.default_model
            or ""
        ).strip()
        if not model_name:
            if provider_name == settings.provider:
                model_name = settings.model
            model_name = model_name or resolve_model_for_provider(provider_name).value
            model_name = model_name or (get_provider_profile(provider_name).default_model if get_provider_profile(provider_name) else "")
        return provider_name, model_name

    def _get_model_provider(self, *, provider_name: str = "", model: str = "") -> ResolvedModelProvider:
        if self._model_provider is None:
            kwargs = dict(self.provider_kwargs)
            if model and "default_model" not in kwargs:
                kwargs["default_model"] = model
            return resolve_model_provider(provider_name or self.provider_name, model or self.default_model, provider_kwargs=kwargs)
        return ResolvedModelProvider(
            provider=self._model_provider,
            provider_name=provider_name or self.provider_name or getattr(self._model_provider, "name", ""),
            model=model or self.default_model,
        )

    def _persist_model_selection(
        self,
        session: AgentSession,
        request: AgentServiceRequest,
        selection: ResolvedModelProvider,
    ) -> AgentSession:
        provider_changed = bool(selection.provider_name and selection.provider_name != (session.metadata.provider or ""))
        model_changed = bool(selection.model and selection.model != (session.metadata.model or ""))
        requested_change = bool(request.provider or request.model)
        if not requested_change and not provider_changed and not model_changed:
            return session
        return self.session_store.update_session_model(
            session.metadata.session_id,
            provider=selection.provider_name or session.metadata.provider,
            model=selection.model or session.metadata.model,
        )

    @staticmethod
    def _context_with_session_title(
        context: AgentPromptContext | dict[str, Any] | None,
        metadata: AgentSessionMetadata,
    ) -> AgentPromptContext | dict[str, Any] | None:
        if isinstance(context, AgentPromptContext):
            if context.session_title:
                return context
            return AgentPromptContext(
                current_note=context.current_note,
                current_page=context.current_page,
                selection_text=context.selection_text,
                visible_annotations=list(context.visible_annotations),
                session_title=metadata.title,
            )
        if isinstance(context, dict):
            merged = dict(context)
            merged.setdefault("session_title", metadata.title)
            return merged
        return {"session_title": metadata.title}

    def _register_persistent_memory_tools(self) -> None:
        if self.memory_manager is None:
            return
        self.tool_registry.register_group(PERSISTENT_MEMORY_TOOL_GROUP)
        definition = create_persistent_memory_tool_definition(self.memory_manager)
        if self.tool_registry.get(definition.name) is None:
            self.tool_registry.register(definition)

    def _register_todo_tool(self) -> None:
        if self.todo_store is None:
            return
        register_todo_tool(self.tool_registry, store=self.todo_store)

    def _set_tool_context(
        self,
        session_id: str,
        *,
        provider: ModelProvider | None = None,
        provider_name: str = "",
        model: str = "",
        file_generation: dict[str, Any] | None = None,
        image_generation: dict[str, Any] | None = None,
        attachments: list[dict[str, Any]] | None = None,
        available_tool_names: list[str] | tuple[str, ...] | set[str] | None = None,
        control: AgentRunControl | None = None,
    ) -> None:
        self._tool_context.session_id = session_id
        self._tool_context.provider = provider
        self._tool_context.provider_name = provider_name
        self._tool_context.model = model
        self._tool_context.file_generation = dict(file_generation or {})
        self._tool_context.image_generation = dict(image_generation or {})
        self._tool_context.attachments = list(attachments or [])
        self._tool_context.available_tool_names = tuple(str(name) for name in (available_tool_names or ()) if str(name))
        self._tool_context.control = control

    def _clear_tool_context(self) -> None:
        self._tool_context.session_id = ""
        self._tool_context.provider = None
        self._tool_context.provider_name = ""
        self._tool_context.model = ""
        self._tool_context.file_generation = {}
        self._tool_context.image_generation = {}
        self._tool_context.attachments = []
        self._tool_context.available_tool_names = ()
        self._tool_context.control = None

    def _current_tool_session_id(self) -> str:
        return str(getattr(self._tool_context, "session_id", "") or "")

    def _current_tool_provider_name(self) -> str:
        return str(getattr(self._tool_context, "provider_name", "") or "")

    def _current_tool_model(self) -> str:
        return str(getattr(self._tool_context, "model", "") or "")

    def _current_tool_file_generation(self) -> dict[str, Any]:
        value = getattr(self._tool_context, "file_generation", {})
        return dict(value) if isinstance(value, dict) else {}

    def _current_tool_image_generation(self) -> dict[str, Any]:
        value = getattr(self._tool_context, "image_generation", {})
        return dict(value) if isinstance(value, dict) else {}

    def _current_tool_attachments(self) -> list[dict[str, Any]]:
        value = getattr(self._tool_context, "attachments", [])
        return [dict(item) for item in value if isinstance(item, dict)] if isinstance(value, list) else []

    def _current_tool_available_names(self) -> tuple[str, ...]:
        value = getattr(self._tool_context, "available_tool_names", ())
        return tuple(str(name) for name in value) if isinstance(value, (list, tuple, set)) else ()

    def _current_tool_cancelled(self) -> bool:
        control = getattr(self._tool_context, "control", None)
        return bool(getattr(control, "cancelled", False))

    def _normalize_attachments(self, attachments: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        for item in attachments or []:
            if not isinstance(item, dict):
                continue
            artifact_id = str(item.get("id") or item.get("artifactId") or "").strip()
            if not artifact_id:
                continue
            artifact = self.media_store.require_artifact(artifact_id)
            normalized.append(artifact.to_dict())
        return normalized

    def _model_request_options(
        self,
        request: AgentServiceRequest,
        *,
        session_id: str,
        provider_name: str,
        media_store: MediaStore,
    ) -> dict[str, Any]:
        options = dict(request.request_options or {})
        options["_paper_notes_media_store"] = media_store
        options["_paper_notes_session_id"] = session_id
        options["_paper_notes_provider"] = provider_name
        image_generation = _normalize_image_generation_config(request.image_generation)
        if image_generation.get("enabled"):
            options["_paper_notes_image_generation"] = image_generation
        file_generation = _normalize_file_generation_config(request.file_generation)
        if file_generation.get("enabled"):
            options["_paper_notes_file_generation"] = file_generation
        return options

    def _analyze_paper_image_tool(self, args: dict[str, Any]) -> dict[str, Any]:
        artifact_id = str(args.get("artifact_id") or args.get("artifactId") or "").strip()
        if not artifact_id and args.get("path"):
            existing = self.media_store.find_by_path(str(args.get("path") or ""))
            artifact_id = existing.id if existing is not None else ""
        if not artifact_id:
            return {"success": False, "error": "artifact_id is required.", "code": "artifact_id_required"}
        try:
            artifact = self.media_store.require_artifact(artifact_id)
            image_url = self.media_store.data_url_for_artifact(artifact.id)
        except MediaStoreError as error:
            return {"success": False, "error": str(error), "code": "artifact_not_found"}

        provider = getattr(self._tool_context, "provider", None)
        model = str(getattr(self._tool_context, "model", "") or "")
        if provider is None or not model:
            return {"success": False, "error": "No model provider is active.", "code": "provider_unavailable"}
        question = str(args.get("question") or "Analyze this paper image.").strip()
        prompt = (
            "Analyze this image for a local paper-note writing workflow. "
            "Be precise about visible text, figures, axes, equations, and paper-specific interpretation.\n\n"
            f"Question: {question}"
        )
        try:
            response = provider.generate(ModelRequest(
                model=model,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": prompt},
                        {"type": "input_image", "image_url": image_url},
                    ],
                }],
                tools=[],
                request_options={},
            ))
        except ModelProviderError as error:
            return {
                "success": False,
                "artifact": artifact.to_dict(),
                "question": question,
                "error": str(error),
                "code": "image_analysis_provider_error",
            }
        return {
            "success": True,
            "artifact": artifact.to_dict(),
            "question": question,
            "analysis": response.content or "",
        }

    def _todo_context(self, session_id: str) -> str:
        if self.todo_store is None or not session_id:
            return ""
        return self.todo_store.format_for_injection(session_id)

    @staticmethod
    def _create_memory_manager(
        *,
        memory_manager: MemoryManager | None,
        use_memory: bool,
        memory_path: str | Path | None,
        custom_tool_registry: bool,
    ) -> MemoryManager | None:
        if memory_manager is not None:
            return memory_manager
        if not use_memory or custom_tool_registry:
            return None
        return create_local_memory_manager(memory_path)

    @staticmethod
    def _note_id_for_request(request: AgentServiceRequest, metadata: AgentSessionMetadata) -> str:
        return str(request.note_id or metadata.note_id or "")


def _service_result(
    *,
    session: AgentSession,
    run_result: AgentRunResult,
    created_session: bool,
) -> AgentServiceResult:
    return AgentServiceResult(
        session_id=session.metadata.session_id,
        session=session,
        completed=run_result.completed,
        response=run_result.final_response,
        messages=session.messages,
        events=run_result.events,
        turns=run_result.turns,
        pending_tool_calls=run_result.pending_tool_calls,
        artifacts=run_result.artifacts,
        error=run_result.error,
        cancelled=run_result.cancelled,
        created_session=created_session,
    )


def _last_user_message_attachments(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for message in reversed(messages):
        if message.get("role") != "user":
            continue
        attachments = message.get("attachments")
        if not isinstance(attachments, list):
            return []
        return [dict(item) for item in attachments if isinstance(item, dict)]
    return []


def _context_compaction_marker_message(*, focus: str | None = None, warning: str | None = None) -> dict[str, Any]:
    focus_text = str(focus or "").strip()
    warning_text = str(warning or "").strip()
    text = "Context compacted."
    if focus_text:
        text = f"{text} Focus: {focus_text}."
    if warning_text:
        text = f"{text} Note: {warning_text}"
    return {
        "role": "divider",
        "content": text,
        "metadata": {
            "type": "context_compaction_marker",
            "focus": focus_text,
            "warning": warning_text,
        },
    }


def _run_trace_status(run_result: AgentRunResult) -> str:
    if run_result.cancelled:
        return "cancelled"
    if run_result.completed:
        return "completed"
    if run_result.error:
        return "failed"
    if run_result.pending_tool_calls:
        return "pending"
    return "stopped"


def _attach_run_trace(
    messages: list[dict[str, Any]],
    events: list[AgentEvent],
    *,
    request_id: str = "",
    started_at: datetime,
    finished_at: datetime,
    status: str,
    error: str | None = None,
) -> None:
    trace_events = [_public_run_trace_event(event) for event in events if event.type != "model_delta"]
    trace = {
        "requestId": request_id,
        "startedAt": started_at.isoformat(timespec="milliseconds"),
        "finishedAt": finished_at.isoformat(timespec="milliseconds"),
        "durationMs": max(0, int((finished_at - started_at).total_seconds() * 1000)),
        "status": status,
        "error": error or "",
        "events": trace_events,
    }
    for message in reversed(messages):
        if _is_visible_assistant_message(message):
            message["runTrace"] = trace
            return
    for message in reversed(messages):
        if message.get("role") == "assistant":
            message["runTrace"] = trace
            return


def _attach_work_trace(
    messages: list[dict[str, Any]],
    events: list[AgentEvent],
    *,
    status: str,
) -> None:
    items = _work_trace_items_from_events(events)
    if not items:
        return
    trace = {
        "status": status,
        "items": items,
    }
    for message in reversed(messages):
        if _is_visible_assistant_message(message):
            message["workTrace"] = trace
            return
    for message in reversed(messages):
        if message.get("role") == "assistant":
            message["workTrace"] = trace
            return


def _is_visible_assistant_message(message: dict[str, Any]) -> bool:
    if message.get("role") != "assistant":
        return False
    if message.get("tool_calls"):
        return False
    return bool(str(message.get("content") or message.get("text") or "").strip())


def _work_trace_items_from_events(events: list[AgentEvent]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    seen_native: set[tuple[str, str]] = set()
    seen_fallback: set[tuple[str, str]] = set()
    for event in events:
        event_type = event.type
        data = event.data if isinstance(event.data, dict) else {}
        if event_type == "work_trace_item":
            text = str(data.get("text") or event.message or "").strip()
            if not text:
                continue
            item_type = str(data.get("trace_type") or "summary").strip() or "summary"
            key = (item_type, text)
            if key in seen_native:
                continue
            seen_native.add(key)
            items.append({
                "type": item_type,
                "text": text,
                "source": str(data.get("source") or "provider"),
            })
            continue
        if event_type == "tool_call":
            text = _work_trace_tool_detail(str(data.get("name") or "tool"), data)
        elif event_type == "tool_result":
            text = _work_trace_tool_result_detail(str(data.get("name") or "tool"), data)
        elif event_type == "tool_error":
            text = _work_trace_tool_error_detail(str(data.get("name") or "tool"), data)
        elif event_type in {"tool_approval_requested", "tool_calls_pending", "halted", "tool_halted", "cancelled"}:
            text = event.message
        else:
            continue
        text = str(text or "").strip()
        if not text:
            continue
        tool_name = str(data.get("name") or "")
        key = ("skill" if event_type.startswith("tool_") and _is_skill_tool(tool_name) else "tool" if event_type.startswith("tool_") else "status", text)
        if key in seen_fallback:
            continue
        seen_fallback.add(key)
        items.append({
            "type": key[0],
            "text": text,
            "source": "runtime",
        })
    return items


def _work_trace_tool_detail(name: str, data: dict[str, Any]) -> str:
    args = _json_args(data.get("arguments"))
    if name == "skills_list":
        category = str(args.get("category") or "").strip()
        return f"Checking available skills{f' in category {category}' if category else ''}..."
    if name == "skill_view":
        skill_name = str(args.get("name") or "").strip()
        file_path = str(args.get("file_path") or args.get("filePath") or "").strip()
        return f"Loading skill: {skill_name or 'instructions'}{f' -> {file_path}' if file_path else ''}..."
    if name == "paper_notes_search":
        query = str(args.get("query") or "").strip()
        return f"Searching paper notes{f': {query}' if query else ''}..."
    if name == "paper_notes_context":
        return "Reading note context..."
    if name == "create_image_artifact":
        return "Generating image..."
    if name == "paper_notes_read_paper":
        return "Reading paper source..."
    if name in {"paper_notes_edit", "write_note_section", "append_note_section", "replace_note_section", "update_note_metadata"}:
        return "Updating note..."
    if name == "read_note_html":
        return "Reading note HTML..."
    if name == "list_note_sections":
        return "Reading note outline..."
    if name == "persistent_memory":
        return "Checking saved memory..."
    if name == "session_search":
        return "Searching past sessions..."
    if name == "web_search":
        return "Searching the web..."
    if name == "web_fetch":
        return "Reading web page..."
    return f"Using {name}{_argument_suffix(args)}..."


def _work_trace_tool_result_detail(name: str, data: dict[str, Any]) -> str:
    snapshot = data.get("snapshot") if isinstance(data.get("snapshot"), dict) else {}
    changed_files = snapshot.get("changedFiles") if isinstance(snapshot.get("changedFiles"), list) else []
    if changed_files:
        count = len(changed_files)
        return f"Saved {count} file{'s' if count != 1 else ''}."
    return ""


def _work_trace_tool_error_detail(name: str, data: dict[str, Any]) -> str:
    error = str(data.get("error") or data.get("message") or "").strip()
    code = str(data.get("code") or "").strip()
    detail = error or code
    return f"Tool failed: {name}{f' - {detail}' if detail else ''}"


def _json_args(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _is_skill_tool(name: str) -> bool:
    return name in {"skills_list", "skill_view"}


def _argument_suffix(args: dict[str, Any]) -> str:
    formatted = _format_arguments(args)
    return f" ({formatted})" if formatted else ""


def _format_arguments(args: dict[str, Any], *, max_items: int = 4, max_chars: int = 140) -> str:
    if not isinstance(args, dict) or not args:
        return ""
    parts: list[str] = []
    for key in sorted(args):
        value = args.get(key)
        if value in (None, "", [], {}):
            continue
        parts.append(f"{key}: {_short_trace_value(value)}")
        if len(parts) >= max_items:
            break
    text = ", ".join(parts)
    return f"{text[:max_chars - 1]}…" if len(text) > max_chars else text


def _short_trace_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        return f"[{', '.join(_short_trace_value(item) for item in value[:3])}{', …' if len(value) > 3 else ''}]"
    if isinstance(value, dict):
        return "{…}"
    text = str(value or "").strip().replace("\n", " ")
    if len(text) > 46:
        text = f"{text[:45]}…"
    return json.dumps(text, ensure_ascii=False)


_TRACE_INTERNAL_KEYS = {
    "provider_data",
    "codex_reasoning_items",
    "codex_message_items",
    "input",
    "messages",
    "raw",
    "base64",
    "image_url",
    "imageUrl",
}


def _public_run_trace_event(event: AgentEvent) -> dict[str, Any]:
    return {
        "type": event.type,
        "message": event.message,
        "data": _trim_trace_value(_sanitize_trace_data(event.data), max_chars=1600),
    }


def _sanitize_trace_data(value: Any) -> Any:
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            if key in _TRACE_INTERNAL_KEYS:
                continue
            if key == "snapshot" and isinstance(item, dict):
                sanitized[key] = {
                    snapshot_key: item.get(snapshot_key)
                    for snapshot_key in ("snapshotId", "toolName", "changedFiles", "undoable", "changed")
                    if snapshot_key in item
                }
                continue
            sanitized[str(key)] = _sanitize_trace_data(item)
        return sanitized
    if isinstance(value, list):
        return [_sanitize_trace_data(item) for item in value[:20]]
    return value


def _trim_trace_value(value: Any, *, max_chars: int) -> Any:
    if isinstance(value, str):
        return value if len(value) <= max_chars else f"{value[:max_chars]}..."
    if isinstance(value, dict):
        return {key: _trim_trace_value(item, max_chars=max_chars) for key, item in value.items()}
    if isinstance(value, list):
        return [_trim_trace_value(item, max_chars=max_chars) for item in value]
    return value


def _attach_tool_activity(messages: list[dict[str, Any]], events: list[AgentEvent], *, session_id: str) -> None:
    activity = _tool_activity_from_events(events, session_id=session_id)
    if not activity:
        return
    for message in reversed(messages):
        if message.get("role") == "assistant":
            existing = message.get("toolActivity") if isinstance(message.get("toolActivity"), list) else []
            message["toolActivity"] = [*existing, *activity]
            return


def _tool_activity_from_events(events: list[AgentEvent], *, session_id: str) -> list[dict[str, Any]]:
    activities: list[dict[str, Any]] = []
    for event in events:
        if event.type != "tool_result":
            continue
        data = event.data or {}
        snapshot = data.get("snapshot") if isinstance(data.get("snapshot"), dict) else {}
        changed_files = snapshot.get("changedFiles") if isinstance(snapshot.get("changedFiles"), list) else []
        if not changed_files:
            continue
        snapshot_arguments = snapshot.get("arguments") if isinstance(snapshot.get("arguments"), dict) else {}
        note_id = data.get("note_id") or snapshot_arguments.get("note_id") or snapshot_arguments.get("id")
        activities.append({
            "type": "tool_result",
            "name": data.get("name") or snapshot.get("toolName") or "tool",
            "sessionId": session_id,
            "noteId": note_id or "",
            "snapshotId": snapshot.get("snapshotId") or "",
            "changedFiles": changed_files,
            "undoable": bool(snapshot.get("undoable")),
            "writeMode": data.get("write_mode") or data.get("writeMode") or "",
            "changed": bool(data.get("changed") or snapshot.get("changed")),
            "summary": data.get("summary") or "",
            "toolMessage": data.get("message") or "",
            "message": data.get("message") or event.message or "Tool completed.",
        })
    return activities


def _compression_event(
    result: Any,
    *,
    reason: str,
    pass_index: int,
    attempt: int | None,
    context_length: int,
    before_request_tokens: int,
    after_request_tokens: int,
) -> AgentEvent:
    data = {
        "reason": reason,
        "pass": pass_index,
        "context_length": context_length,
        "before_message_count": result.stats.before_message_count,
        "after_message_count": result.stats.after_message_count,
        "before_estimated_tokens": before_request_tokens,
        "after_estimated_tokens": after_request_tokens,
        "message_before_estimated_tokens": result.stats.before_estimated_tokens,
        "message_after_estimated_tokens": result.stats.after_estimated_tokens,
        "pruned_tool_results": result.stats.pruned_tool_results,
        "summarized_message_count": result.stats.summarized_message_count,
    }
    if attempt is not None:
        data["attempt"] = attempt
    return AgentEvent(
        "context_compressed",
        "Compressed long session context before model call.",
        data,
    )


def _compression_warning_events(result: Any) -> list[AgentEvent]:
    metadata = dict(getattr(result.stats, "metadata", {}) or {})
    events: list[AgentEvent] = []
    summary_error = str(metadata.get("summary_error") or "").strip()
    if summary_error:
        events.append(AgentEvent(
            "context_compression_warning",
            f"Compression summary failed: {summary_error}. Inserted a fallback context marker.",
            {
                "code": "summary_failed",
                "summary_error": summary_error,
                "fallback_used": bool(metadata.get("summary_fallback_used")),
                "summary_dropped_count": int(metadata.get("summary_dropped_count") or 0),
            },
        ))
    provider_fallback_error = str(metadata.get("summary_provider_fallback_error") or "").strip()
    if provider_fallback_error:
        events.append(AgentEvent(
            "context_compression_warning",
            "Configured compression model failed; recovered using the current session model.",
            {
                "code": "summary_provider_fallback",
                "summary_provider_fallback_error": provider_fallback_error,
            },
        ))
    compression_count = int(metadata.get("compression_count") or 0)
    if compression_count >= 2:
        events.append(AgentEvent(
            "context_compression_warning",
            f"Session compressed {compression_count} times; context accuracy may degrade. Consider starting a new chat if answers feel stale.",
            {
                "code": "repeated_compression",
                "compression_count": compression_count,
            },
        ))
    return events


def _tool_selection_warning_events(snapshot: ToolCatalogSnapshot) -> list[AgentEvent]:
    events: list[AgentEvent] = []
    if snapshot.unknown_toolsets:
        events.append(AgentEvent(
            "tool_selection_warning",
            "Some requested toolsets are not registered and were ignored.",
            {
                "code": "unknown_toolsets",
                "unknown_toolsets": list(snapshot.unknown_toolsets),
            },
        ))
    if snapshot.unavailable_tools:
        events.append(AgentEvent(
            "tool_selection_warning",
            "Some requested tools are unavailable in this environment and were hidden from the model.",
            {
                "code": "unavailable_tools",
                "unavailable_tools": list(snapshot.unavailable_tools),
            },
        ))
    return events


def _emit_service_event(event: AgentEvent, event_sink: AgentEventSink | None) -> None:
    if event_sink is None:
        return
    event_sink(event)


def _compact_warning(events: list[AgentEvent], context: AgentContextStatus) -> str | None:
    for event in events:
        if event.type == "context_compression_warning" and event.message:
            return event.message
    if context.fallback_used and context.last_compression_error:
        return f"Compression summary failed: {context.last_compression_error}. Inserted a fallback context marker."
    if context.compression_count >= 2:
        return f"Session compressed {context.compression_count} times; context accuracy may degrade."
    return None


def _model_visible_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    visible: list[dict[str, Any]] = []
    for message in messages:
        if str(message.get("role") or "") not in MODEL_VISIBLE_ROLES:
            continue
        copied = dict(message)
        copied.pop("runTrace", None)
        visible.append(copied)
    return visible


def _native_web_search_requested(request_options: dict[str, Any] | None) -> bool:
    if not isinstance(request_options, dict):
        return False
    value = request_options.get(
        "_paper_notes_native_web_search",
        request_options.get("_paper_notes_provider_native_web_search"),
    )
    return value is True


_RAW_TRANSCRIPT_INDEX_KEY = "_paper_notes_raw_transcript_index"


def _with_raw_transcript_indexes(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    indexed: list[dict[str, Any]] = []
    for index, message in enumerate(messages):
        copied = dict(message)
        metadata = dict(copied.get("metadata") or {})
        metadata.setdefault(_RAW_TRANSCRIPT_INDEX_KEY, index)
        copied["metadata"] = metadata
        indexed.append(copied)
    return indexed


def _ensure_raw_transcript_indexes(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if any(_internal_raw_transcript_index(message) is not None for message in messages):
        return [dict(message) for message in messages]
    return _with_raw_transcript_indexes(messages)


def _strip_internal_compression_metadata(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cleaned: list[dict[str, Any]] = []
    for message in messages:
        copied = dict(message)
        metadata = dict(copied.get("metadata") or {})
        metadata.pop(_RAW_TRANSCRIPT_INDEX_KEY, None)
        if metadata:
            copied["metadata"] = metadata
        else:
            copied.pop("metadata", None)
        cleaned.append(copied)
    return cleaned


def _internal_raw_transcript_index(message: dict[str, Any]) -> int | None:
    metadata = message.get("metadata")
    if not isinstance(metadata, dict):
        return None
    value = metadata.get(_RAW_TRANSCRIPT_INDEX_KEY)
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _last_user_message_text(messages: list[dict[str, Any]]) -> str:
    for message in reversed(messages):
        if message.get("role") == "user":
            return str(message.get("content") or "").strip()
    return ""


def _combine_extra_instructions(*parts: str | None) -> str | None:
    cleaned = [str(part or "").strip() for part in parts if str(part or "").strip()]
    return "\n\n".join(cleaned) if cleaned else None


def _generation_mode_instructions(request: AgentServiceRequest) -> str:
    instructions: list[str] = []
    image_generation = _normalize_image_generation_config(request.image_generation)
    if image_generation.get("enabled"):
        instructions.append(
            "The user explicitly enabled image generation for this turn. If the request asks for an image, "
            f"create a downloadable image by calling `{CREATE_IMAGE_ARTIFACT_TOOL}` with `prompt`, `mode`, "
            "and optional `input_artifact_ids`; do not only describe the image. After the tool succeeds, "
            "briefly describe the result and mention the artifact id if useful, but do not write raw download "
            "URLs or sandbox: links; the UI will attach the generated artifact card."
        )
    file_generation = _normalize_file_generation_config(request.file_generation)
    if file_generation.get("enabled"):
        mime_type = _mime_for_file_generation_format(str(file_generation.get("format") or "markdown"))
        instructions.append(
            "The user explicitly enabled file creation for this turn. Create a downloadable file by calling "
            f"`{CREATE_FILE_ARTIFACT_TOOL}` with `file_name`, `mime_type`, and `content`; prefer "
            f"`{mime_type}` unless the user asks for a different allowed text format. Do not only paste the "
            "file contents in chat. After the tool succeeds, briefly describe the file and mention the artifact "
            "id if useful, but do not write raw download URLs or sandbox: links; the UI will attach the file card."
        )
    return "\n".join(instructions)


def _attachment_instructions(attachments: list[dict[str, Any]]) -> str:
    if not attachments:
        return ""
    names = [
        str(item.get("fileName") or item.get("file_name") or item.get("id") or "").strip()
        for item in attachments
        if isinstance(item, dict)
    ]
    visible_names = ", ".join(name for name in names if name)
    suffix = f" Attached file(s): {visible_names}." if visible_names else ""
    return (
        "The user's latest message includes file attachments. When the user asks about \"this file\", "
        "\"the file\", or whether a file has content, interpret that as the attached file(s) first, before "
        f"using paper or note context. Do not answer from the current paper/note context when the question can "
        f"be answered from the attachment context.{suffix}"
    )


def _normalize_image_generation_config(value: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    enabled = bool(value.get("enabled"))
    if not enabled:
        return {"enabled": False}
    size = str(value.get("size") or "1024x1024").strip()
    quality = str(value.get("quality") or "auto").strip()
    image_format = str(value.get("format") or "png").strip().lower()
    action = str(value.get("action") or "auto").strip().lower()
    if size not in {"1024x1024", "1024x1536", "1536x1024", "auto"}:
        size = "1024x1024"
    if quality not in {"auto", "low", "medium", "high"}:
        quality = "auto"
    if image_format not in {"png", "jpeg", "jpg", "webp"}:
        image_format = "png"
    if action not in {"auto", "generate", "edit"}:
        action = "auto"
    return {
        "enabled": True,
        "action": action,
        "size": size,
        "quality": quality,
        "format": "jpeg" if image_format == "jpg" else image_format,
    }


def _normalize_file_generation_config(value: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    enabled = bool(value.get("enabled"))
    if not enabled:
        return {"enabled": False}
    file_format = str(value.get("format") or "markdown").strip().lower()
    if file_format not in {"markdown", "text", "json", "csv", "html"}:
        file_format = "markdown"
    return {
        "enabled": True,
        "format": file_format,
        "mime_type": _mime_for_file_generation_format(file_format),
    }


def _mime_for_file_generation_format(file_format: str) -> str:
    return {
        "markdown": "text/markdown",
        "text": "text/plain",
        "json": "application/json",
        "csv": "text/csv",
        "html": "text/html",
    }.get(str(file_format or "").strip().lower(), "text/markdown")


def _has_function_tool(tools: list[dict[str, Any]], name: str) -> bool:
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        function = tool.get("function")
        if isinstance(function, dict) and function.get("name") == name:
            return True
    return False


def _tool_names_from_model_tools(tools: list[dict[str, Any]]) -> tuple[str, ...]:
    names: list[str] = []
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        function = tool.get("function")
        if not isinstance(function, dict):
            continue
        name = str(function.get("name") or "").strip()
        if name:
            names.append(name)
    return tuple(dict.fromkeys(names))


def _attach_result_artifacts(messages: list[dict[str, Any]], artifacts: list[dict[str, Any]]) -> None:
    if not artifacts:
        return
    for message in reversed(messages):
        if message.get("role") != "assistant":
            continue
        existing = message.get("artifacts") if isinstance(message.get("artifacts"), list) else []
        by_id = {str(item.get("id") or ""): dict(item) for item in existing if isinstance(item, dict)}
        extras: list[dict[str, Any]] = []
        for artifact in artifacts:
            if not isinstance(artifact, dict):
                continue
            artifact_id = str(artifact.get("id") or "")
            if artifact_id and artifact_id in by_id:
                continue
            extras.append(dict(artifact))
        if extras:
            message["artifacts"] = [*existing, *extras]
        return


def _runtime_prompt_context(
    current: datetime,
    *,
    session_id: str = "",
    provider: str = "",
    model: str = "",
) -> dict[str, str]:
    tzinfo = current.tzinfo
    timezone_name = current.tzname() or (str(tzinfo) if tzinfo is not None else "")
    return {
        "current_time": current.isoformat(timespec="seconds"),
        "current_date": current.date().isoformat(),
        "current_weekday": current.strftime("%A"),
        "timezone": timezone_name,
        "session_id": str(session_id or ""),
        "provider": str(provider or ""),
        "model": str(model or ""),
        "platform": "Paper Notes local web app",
    }


def _runtime_context_message(
    current: datetime,
    *,
    session_id: str = "",
    provider: str = "",
    model: str = "",
) -> dict[str, str]:
    return {
        "role": "system",
        "content": _render_runtime_prompt_context(_runtime_prompt_context(
            current,
            session_id=session_id,
            provider=provider,
            model=model,
        )),
        "metadata": {"ephemeral": True, "runtime_context": True},
    }


def _attachment_context_message(attachments: list[dict[str, Any]], media_store: MediaStore) -> dict[str, Any] | None:
    if not attachments:
        return None
    blocks = [
        "# Latest user attachments",
        "The latest user message included these attachments. If the user asks about \"the file\" or whether "
        "it has content, answer from this attachment context first. Do not substitute the current paper, PDF, "
        "HTML note, or note metadata unless the user explicitly asks about those instead.",
        "The attachment was provided by the user in this conversation. You may quote brief snippets from it "
        "when needed to verify upload/read behavior, but avoid reproducing long copyrighted passages verbatim; "
        "summarize instead when a requested excerpt would be too long.",
    ]
    for index, attachment in enumerate(attachments, start=1):
        if not isinstance(attachment, dict):
            continue
        artifact_id = str(attachment.get("id") or attachment.get("artifactId") or "").strip()
        file_name = str(attachment.get("fileName") or attachment.get("file_name") or artifact_id or "attachment").strip()
        mime_type = str(attachment.get("mimeType") or attachment.get("mime_type") or "").strip()
        kind = str(attachment.get("kind") or "").strip()
        text = ""
        if artifact_id:
            try:
                text = media_store.extracted_text_for_artifact(artifact_id).strip()
            except (MediaStoreError, ValueError, OSError):
                text = ""
        blocks.append(f"\n## Attachment {index}: {file_name}")
        blocks.append(f"- id: {artifact_id or 'unknown'}")
        blocks.append(f"- kind: {kind or 'unknown'}")
        blocks.append(f"- mime_type: {mime_type or 'unknown'}")
        if text:
            excerpt = text[:5000].rstrip()
            suffix = "\n...[truncated]" if len(text) > len(excerpt) else ""
            language = _attachment_code_language(file_name=file_name, mime_type=mime_type, kind=kind)
            blocks.append(f"- extracted_text_chars: {len(text)}")
            blocks.append(f"\nExtracted text:\n```{language}\n" + excerpt + suffix + "\n```")
        else:
            blocks.append("- extracted_text_chars: 0")
            blocks.append("No text could be extracted from this attachment.")
    return {
        "role": "system",
        "content": "\n".join(blocks),
        "metadata": {"ephemeral": True, "attachment_context": True},
    }


def _attachment_code_language(*, file_name: str, mime_type: str, kind: str) -> str:
    normalized_name = file_name.lower()
    normalized_mime = mime_type.lower()
    normalized_kind = kind.lower()
    if normalized_name.endswith((".md", ".markdown")) or normalized_mime == "text/markdown":
        return "md"
    if normalized_name.endswith(".json") or normalized_mime == "application/json" or normalized_kind == "json":
        return "json"
    if normalized_name.endswith(".csv") or normalized_mime == "text/csv" or normalized_kind == "csv":
        return "csv"
    if normalized_name.endswith((".html", ".htm")) or normalized_mime == "text/html" or normalized_kind == "html":
        return "html"
    if normalized_name.endswith(".py"):
        return "python"
    if normalized_name.endswith(".js"):
        return "javascript"
    if normalized_name.endswith(".ts"):
        return "typescript"
    if normalized_name.endswith(".css"):
        return "css"
    return "text"


def _render_runtime_prompt_context(runtime_context: dict[str, str]) -> str:
    lines = ["# Runtime context"]
    for label, key in (
        ("Current time", "current_time"),
        ("Current date", "current_date"),
        ("Current weekday", "current_weekday"),
        ("Timezone", "timezone"),
        ("Session", "session_id"),
        ("Provider", "provider"),
        ("Model", "model"),
        ("Platform", "platform"),
    ):
        value = str(runtime_context.get(key) or "").strip()
        if value:
            lines.append(f"- {label}: {value}")
    lines.extend([
        "- Interpret relative dates such as today, tomorrow, yesterday, and this week using this runtime context.",
        "- If the user asks for the current time or date, answer from this runtime context instead of guessing.",
        "- For current external facts such as news, prices, software releases, or web pages, use available web search.",
    ])
    return "\n".join(lines)


def _clean_provider(value: object) -> str:
    return normalize_model_provider_name(value)


def _clean_provider_for_injected(value: object) -> str:
    try:
        return normalize_model_provider_name(value)
    except ValueError:
        return str(value or "").strip()


def _normalize_write_tool_mode(value: object) -> str:
    normalized = str(value or "auto").strip().lower()
    return normalized if normalized in {"auto", "warn", "ask", "readonly", "block", "halt"} else "auto"


def _clean_tool_name(value: object) -> str:
    return str(value or "").strip()


def _compression_setting(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if value:
        return value
    for path in (default_secrets_path(), *default_env_paths()):
        values = parse_env_file(path)
        value = values.get(name, "").strip()
        if value:
            return value
    return ""
