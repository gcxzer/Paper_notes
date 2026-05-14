from __future__ import annotations

from typing import Any

from app_config.ai_settings import CODEX_PROVIDER, OPENAI_PROVIDER, resolve_ai_settings, resolve_model_for_provider
from model_providers.codex.auth import DEFAULT_CODEX_BASE_URL, CodexAuthStore, codex_default_headers
from model_providers.openai.provider import _create_streaming_response
from model_providers.responses_adapter import web_search_metadata_from_response
from tools.web_search.common import searched_at, search_error, search_prompt


class OpenAINativeWebSearch:
    """Wrapper for OpenAI Responses native web_search, retained for tests and experiments."""

    def __call__(
        self,
        *,
        query: str,
        limit: int = 5,
        allowed_domains: list[str] | None = None,
        recency_days: int | None = None,
        include_summary: bool = True,
    ) -> dict[str, Any]:
        settings = resolve_ai_settings()
        provider = OPENAI_PROVIDER if settings.api_key else ""
        client = None
        model = ""
        use_stream = False

        if settings.api_key:
            from openai import OpenAI

            client = OpenAI(api_key=settings.api_key)
            model = resolve_model_for_provider(OPENAI_PROVIDER).value or "gpt-5.4-mini"
        else:
            credentials = CodexAuthStore().runtime_credentials()
            if credentials.access_token:
                from openai import OpenAI

                provider = CODEX_PROVIDER
                use_stream = True
                model = resolve_model_for_provider(CODEX_PROVIDER).value or "gpt-5.4-mini"
                client = OpenAI(
                    api_key=credentials.access_token,
                    base_url=(credentials.base_url or DEFAULT_CODEX_BASE_URL).rstrip("/"),
                    default_headers=codex_default_headers(credentials.access_token),
                )

        if client is None:
            return search_error(
                "Native Web Search requires an OpenAI API key or connected Codex OAuth.",
                "web_search_provider_required",
                query=query,
            )

        payload = {
            "model": model,
            "input": search_prompt(
                query,
                limit=limit,
                allowed_domains=allowed_domains or [],
                recency_days=recency_days,
                include_summary=include_summary,
            ),
            "tools": [{"type": "web_search"}],
            "tool_choice": "auto",
            "include": ["web_search_call.action.sources"],
            "store": False,
        }
        response = (
            _create_streaming_response(client, payload)
            if use_stream
            else client.responses.create(**payload)
        )
        metadata = web_search_metadata_from_response(response)
        answer = str(getattr(response, "output_text", "") or "").strip()
        sources = metadata.get("web_search_sources") or []
        if isinstance(sources, list):
            sources = sources[:limit]
        else:
            sources = []
        citations = metadata.get("web_search_citations") or []
        return {
            "success": True,
            "query": query,
            "answer": answer if include_summary else "",
            "sources": sources,
            "citations": citations,
            "searched_at": searched_at(),
            "provider": provider,
        }
