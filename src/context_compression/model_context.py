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
}

_CODEX_OAUTH_CONTEXT_FALLBACK: dict[str, int] = {
    "gpt-5.3-codex": 272_000,
    "gpt-5.4-mini": 400_000,
    "gpt-5.5": 400_000,
    "gpt-5.4": 272_000,
}

_ANTHROPIC_CONTEXT_FALLBACK: dict[str, int] = {
    "claude-opus-4-7": 1_000_000,
    "claude-sonnet-4-6": 1_000_000,
    "claude-haiku-4-5": 200_000,
}

_GEMINI_CONTEXT_FALLBACK: dict[str, int] = {
    "gemini-3-flash-preview": 1_048_576,
    "gemini-3-pro-preview": 1_048_576,
}

_DEEPSEEK_CONTEXT_FALLBACK: dict[str, int] = {
    "deepseek-v4-flash": 1_000_000,
    "deepseek-v4-pro": 1_000_000,
}


# Legacy aliases are kept only so old sessions or hand-written requests can
# resolve a reasonable context window after the UI model list has moved on.
_OPENAI_LEGACY_CONTEXT_FALLBACK: dict[str, int] = {
    "gpt-5": 400_000,
    "gpt-4.1": 1_047_576,
    "gpt-4": 128_000,
}

_CODEX_OAUTH_LEGACY_CONTEXT_FALLBACK: dict[str, int] = {
    "gpt-5": 272_000,
}

_ANTHROPIC_LEGACY_CONTEXT_FALLBACK: dict[str, int] = {
    "claude-opus-4-6": 1_000_000,
}

_DEEPSEEK_LEGACY_CONTEXT_FALLBACK: dict[str, int] = {
    "deepseek-chat": 1_000_000,
    "deepseek-reasoner": 1_000_000,
}

_GEMINI_LEGACY_CONTEXT_FALLBACK: dict[str, int] = {
    "gemini-3.1-pro-preview": 1_048_576,
    "gemini-3.1-flash-lite": 1_048_576,
    "gemini-2.5-pro": 1_048_576,
    "gemini-2.5-flash-lite": 1_048_576,
    "gemini-2.5-flash": 1_048_576,
}


def resolve_context_length_for_model(provider: object, model: object) -> int:
    provider_name = str(provider or "").strip().lower().replace("_", "-")
    model_name = str(model or "").strip().lower()
    if provider_name in {"codex", "codex-oauth", "openai-codex"}:
        return _lookup_context_length(model_name, _CODEX_OAUTH_CONTEXT_FALLBACK, _CODEX_OAUTH_LEGACY_CONTEXT_FALLBACK)
    if provider_name in {"openai", "api-key", "openai-api-key"}:
        return _lookup_context_length(model_name, _OPENAI_CONTEXT_FALLBACK, _OPENAI_LEGACY_CONTEXT_FALLBACK)
    if provider_name in {"anthropic", "claude"}:
        return _lookup_context_length(model_name, _ANTHROPIC_CONTEXT_FALLBACK, _ANTHROPIC_LEGACY_CONTEXT_FALLBACK)
    if provider_name in {"gemini", "google", "google-gemini", "google-ai-studio"}:
        return _lookup_context_length(model_name, _GEMINI_CONTEXT_FALLBACK, _GEMINI_LEGACY_CONTEXT_FALLBACK)
    if provider_name in {"deepseek", "deep-seek"}:
        return _lookup_context_length(model_name, _DEEPSEEK_CONTEXT_FALLBACK, _DEEPSEEK_LEGACY_CONTEXT_FALLBACK)
    return _lookup_context_length(model_name, _OPENAI_CONTEXT_FALLBACK, _OPENAI_LEGACY_CONTEXT_FALLBACK)


def _lookup_context_length(model_name: str, *tables: dict[str, int]) -> int:
    merged = {key: value for table in tables for key, value in table.items()}
    for key, value in sorted(merged.items(), key=lambda item: len(item[0]), reverse=True):
        if key in model_name:
            return value
    return DEFAULT_FALLBACK_CONTEXT_LENGTH
