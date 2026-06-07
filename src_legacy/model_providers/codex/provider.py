from __future__ import annotations

from dataclasses import replace
from typing import Any

from app_config.ai_settings import CODEX_PROVIDER, resolve_model_for_provider
from model_providers.codex.auth import DEFAULT_CODEX_BASE_URL, CodexAuthStore, codex_default_headers
from model_providers.errors import ModelProviderConfigError
from model_providers.types import ModelRequest, ModelResponse, ModelStreamEventSink
from model_providers.openai.provider import OpenAIModelProvider


class CodexModelProvider:
    name = "codex-oauth"

    def __init__(
        self,
        *,
        default_model: str | None = None,
        client: Any | None = None,
        auth_store: CodexAuthStore | None = None,
        base_url: str | None = None,
    ) -> None:
        self.default_model = default_model or resolve_model_for_provider(CODEX_PROVIDER).value
        self.auth_store = auth_store or CodexAuthStore()
        if client is None:
            credentials = self.auth_store.runtime_credentials()
            if not credentials.access_token:
                raise ModelProviderConfigError(
                    "Codex OAuth is not connected. Open Settings > AI Provider and connect Codex OAuth."
                )

            from openai import OpenAI

            client = OpenAI(
                api_key=credentials.access_token,
                base_url=(base_url or credentials.base_url or DEFAULT_CODEX_BASE_URL).rstrip("/"),
                default_headers=codex_default_headers(credentials.access_token),
            )
        self._delegate = OpenAIModelProvider(client=client, default_model=self.default_model)

    def generate(self, request: ModelRequest) -> ModelResponse:
        return self._delegate.generate(self._codex_request(request))

    def stream_generate(
        self,
        request: ModelRequest,
        event_sink: ModelStreamEventSink | None = None,
    ) -> ModelResponse:
        return self._delegate.stream_generate(
            self._codex_request(request),
            event_sink=event_sink,
        )

    def _codex_request(self, request: ModelRequest) -> ModelRequest:
        model = request.model or self.default_model
        if not model:
            raise ModelProviderConfigError("A model is required for Codex OAuth.")
        # The ChatGPT-account Codex backend has a stricter Responses surface than
        # the public API and may reject max_output_tokens.
        return replace(
            request,
            model=model,
            max_output_tokens=None,
            request_options={**request.request_options, "_paper_notes_provider": CODEX_PROVIDER},
        )
