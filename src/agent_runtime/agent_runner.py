from __future__ import annotations

from agent_runtime.agent_loop import run_agent_loop
from agent_runtime.types import AgentEventSink, AgentRunRequest, AgentRunResult, ToolExecutor
from model_providers.base import ModelProvider


class AgentRunner:
    def __init__(
        self,
        model_provider: ModelProvider,
        *,
        tool_executor: ToolExecutor | None = None,
        event_sink: AgentEventSink | None = None,
    ) -> None:
        self.model_provider = model_provider
        self.tool_executor = tool_executor
        self.event_sink = event_sink

    def run(self, request: AgentRunRequest) -> AgentRunResult:
        return run_agent_loop(
            self.model_provider,
            request,
            tool_executor=self.tool_executor,
            event_sink=self.event_sink,
        )
