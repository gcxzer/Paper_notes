from __future__ import annotations


# Adapted from Nous Research Hermes Agent.
# Original source: hermes-agent/agent/model_metadata.py
# License: MIT Copyright (c) 2025 Nous Research


DEFAULT_FALLBACK_CONTEXT_LENGTH = 256_000

_OPENAI_CONTEXT_FALLBACK: dict[str, int] = {
    "gpt-5.5": 1_050_000,
    "gpt-5.4-nano": 400_000,
    "gpt-5.4-mini": 400_000,
    "gpt-5.4": 1_050_000,
    "gpt-5": 400_000,
    "gpt-4.1": 1_047_576,
    "gpt-4": 128_000,
}

_CODEX_OAUTH_CONTEXT_FALLBACK: dict[str, int] = {
    "gpt-5.1-codex-max": 272_000,
    "gpt-5.1-codex-mini": 272_000,
    "gpt-5.3-codex": 272_000,
    "gpt-5.2-codex": 272_000,
    "gpt-5.4-mini": 272_000,
    "gpt-5.5": 272_000,
    "gpt-5.4": 272_000,
    "gpt-5.2": 272_000,
    "gpt-5": 272_000,
}


def resolve_context_length_for_model(provider: object, model: object) -> int:
    provider_name = str(provider or "").strip().lower().replace("_", "-")
    model_name = str(model or "").strip().lower()
    if provider_name in {"codex", "codex-oauth", "openai-codex"}:
        return _lookup_context_length(model_name, _CODEX_OAUTH_CONTEXT_FALLBACK)
    if provider_name in {"openai", "api-key", "openai-api-key"}:
        return _lookup_context_length(model_name, _OPENAI_CONTEXT_FALLBACK)
    return _lookup_context_length(model_name, _OPENAI_CONTEXT_FALLBACK)


def _lookup_context_length(model_name: str, table: dict[str, int]) -> int:
    for key, value in sorted(table.items(), key=lambda item: len(item[0]), reverse=True):
        if key in model_name:
            return value
    return DEFAULT_FALLBACK_CONTEXT_LENGTH
