from __future__ import annotations

from typing import Protocol

from model_providers.types import ModelRequest, ModelResponse, ModelStreamEventSink


class ModelProvider(Protocol):
    name: str

    def generate(self, request: ModelRequest) -> ModelResponse:
        """Generate a normalized model response for an agent turn."""

    def stream_generate(
        self,
        request: ModelRequest,
        event_sink: ModelStreamEventSink | None = None,
    ) -> ModelResponse:
        """Generate a normalized response while emitting provider stream events."""
