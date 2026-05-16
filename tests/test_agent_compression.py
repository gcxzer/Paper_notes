from __future__ import annotations

import json

from context_compression import (
    DEFAULT_FALLBACK_CONTEXT_LENGTH,
    MINIMUM_CONTEXT_LENGTH,
    SUMMARY_PREFIX,
    ContextCompressionConfig,
    ContextCompressor,
    LLMContextSummaryProvider,
    build_context_summary_prompt,
    estimate_messages_tokens_rough,
    estimate_request_tokens_rough,
    prune_old_tool_results,
    resolve_context_length_for_model,
    truncate_tool_call_args_json,
)
from model_providers.types import ModelRequest, ModelResponse


class FakeSummaryProvider:
    name = "fake-summary"

    def __init__(self, response: str) -> None:
        self.response = response
        self.requests: list[ModelRequest] = []

    def generate(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        return ModelResponse(content=self.response)


def test_rough_token_estimator_counts_short_text_and_images():
    messages = [
        {"role": "user", "content": "hello"},
        {"role": "user", "content": [{"type": "input_text", "text": "see"}, {"type": "image_url"}]},
    ]

    assert estimate_messages_tokens_rough(messages) >= 1_600


def test_request_token_estimator_includes_instructions_and_tools():
    messages = [{"role": "user", "content": "short"}]
    plain = estimate_request_tokens_rough(messages)
    with_request_context = estimate_request_tokens_rough(
        messages,
        instructions="system " * 200,
        tools=[{"type": "function", "function": {"name": "big", "description": "x" * 2000}}],
    )

    assert with_request_context > plain + 400


def test_compression_defaults_use_project_thresholds():
    config = ContextCompressionConfig()

    assert config.context_length == DEFAULT_FALLBACK_CONTEXT_LENGTH
    assert config.protect_first_n == 3
    assert config.protect_last_n == 3
    assert config.resolved_threshold_tokens() == 230_400
    assert config.resolved_threshold_tokens(context_length=272_000) == 244_800
    assert config.resolved_tail_token_budget(context_length=272_000) == 48_960
    assert config.minimum_context_length == MINIMUM_CONTEXT_LENGTH
    assert config.summary_min_tokens == 2_000
    assert config.summary_tokens_ceiling == 12_000
    assert config.summary_failure_cooldown_seconds == 600


def test_context_length_resolution_uses_hermes_provider_fallbacks():
    assert resolve_context_length_for_model("codex-oauth", "gpt-5.5") == 258_000
    assert resolve_context_length_for_model("codex-oauth", "gpt-5.4-mini") == 258_000
    assert resolve_context_length_for_model("codex-oauth", "gpt-5.4") == 258_000
    assert resolve_context_length_for_model("codex-oauth", "gpt-5.3-codex-spark") == 128_000
    assert resolve_context_length_for_model("openai", "gpt-5.5") == 1_050_000
    assert resolve_context_length_for_model("openai", "gpt-5.4-mini") == 400_000
    assert resolve_context_length_for_model("anthropic", "claude-opus-4-7") == 1_000_000
    assert resolve_context_length_for_model("anthropic", "claude-sonnet-4-6") == 1_000_000
    assert resolve_context_length_for_model("anthropic", "claude-haiku-4-5-20251001") == 200_000
    assert resolve_context_length_for_model("gemini", "gemini-3.1-pro-preview") == 1_048_576
    assert resolve_context_length_for_model("gemini", "gemini-2.5-flash-lite") == 1_048_576
    assert resolve_context_length_for_model("deepseek", "deepseek-v4-flash") == 1_000_000
    assert resolve_context_length_for_model("deepseek", "deepseek-v4-pro") == 1_000_000
    assert resolve_context_length_for_model("openai", "unknown-model") == DEFAULT_FALLBACK_CONTEXT_LENGTH


def test_compressor_leaves_short_context_unchanged():
    messages = [{"role": "user", "content": "short"}]
    compressor = ContextCompressor(ContextCompressionConfig(max_estimated_tokens=1, min_messages=4))

    result = compressor.compress(messages)

    assert result.stats.compressed is False
    assert result.messages == messages


def test_compressor_summarizes_middle_and_keeps_latest_user_message():
    messages = [{"role": "user", "content": "first question"}]
    for index in range(8):
        messages.append({"role": "assistant", "content": f"old answer {index} " + ("x" * 200)})
        messages.append({"role": "user", "content": f"old followup {index} " + ("y" * 200)})
    messages.append({"role": "user", "content": "latest task should remain active"})
    calls = []

    def summary_provider(turns, focus_topic=None, *, current_summary="", max_output_tokens=None):
        calls.append({
            "turns": turns,
            "focus_topic": focus_topic,
            "current_summary": current_summary,
            "max_output_tokens": max_output_tokens,
        })
        return "## Active Task\nlatest task should remain active"

    compressor = ContextCompressor(ContextCompressionConfig(
        max_estimated_tokens=1,
        min_messages=4,
        protect_first_n=1,
        protect_last_n=2,
        tail_token_budget=16,
    ), summary_provider=summary_provider)

    result = compressor.compress(messages)

    assert result.stats.compressed is True
    assert result.messages[0]["content"] == "first question"
    assert result.messages[-1]["content"] == "latest task should remain active"
    assert any(str(message.get("content", "")).startswith(SUMMARY_PREFIX) for message in result.messages)
    assert result.stats.summarized_message_count > 0
    assert calls
    assert calls[0]["max_output_tokens"] >= 2_000


def test_llm_summary_provider_builds_hermes_prompt_and_redacts_output():
    provider = FakeSummaryProvider("## Active Task\nUse sk-proj-secretsecretsecret")
    summary_provider = LLMContextSummaryProvider(provider, model="summary-model")

    summary = summary_provider(
        [{"role": "user", "content": "Please continue", "metadata": {"source": "test"}}],
        focus_topic="memory",
        current_summary="## Goal\nPrevious work",
        max_output_tokens=2_600,
    )

    prompt = provider.requests[0].messages[0]["content"]
    assert provider.requests[0].model == "summary-model"
    assert provider.requests[0].max_output_tokens == 2_600
    assert "CURRENT SUMMARY" in prompt
    assert "NEW TURNS TO INCORPORATE" in prompt
    assert "FOCUS TOPIC" in prompt
    assert "## Pending User Asks" in prompt
    assert "NEVER include API keys" in prompt
    assert summary == "## Active Task\nUse sk-proj-[REDACTED]"


def test_summary_prompt_uses_hermes_sections():
    prompt = build_context_summary_prompt([{"role": "user", "content": "继续"}], target_tokens=2_000)

    for section in (
        "## Active Task",
        "## Goal",
        "## Constraints & Preferences",
        "## Completed Actions",
        "## Active State",
        "## Pending User Asks",
        "## Remaining Work",
        "## Critical Context",
    ):
        assert section in prompt


def test_prune_old_tool_results_summarizes_results_and_keeps_tool_args_valid_json():
    args = json.dumps({"path": "note.md", "content": "x" * 800})
    messages = [
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [{"id": "call_1", "function": {"name": "write_file", "arguments": args}}],
        },
        {"role": "tool", "tool_call_id": "call_1", "content": "result line\n" * 200},
        {"role": "user", "content": "latest"},
    ]

    pruned, count = prune_old_tool_results(
        messages,
        protect_tail_count=1,
        protect_tail_tokens=None,
        large_tool_result_chars=50,
        tool_args_head_chars=40,
    )

    assert count == 1
    assert pruned[1]["content"].startswith("[write_file]")
    truncated_args = pruned[0]["tool_calls"][0]["function"]["arguments"]
    parsed = json.loads(truncated_args)
    assert parsed["content"].endswith("...[truncated]")


def test_truncate_tool_call_args_json_returns_invalid_json_unchanged():
    assert truncate_tool_call_args_json("{not json") == "{not json"


def test_compression_tool_pair_sanitizer_uses_synthetic_missing_result():
    compressor = ContextCompressor()
    sanitized = compressor._sanitize_tool_pairs([
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{
                "id": "call_1",
                "type": "function",
                "function": {"name": "lookup", "arguments": "{}"},
            }],
        },
        {"role": "tool", "tool_call_id": "orphan", "content": "stale"},
    ])

    assert len(sanitized) == 2
    assert sanitized[1]["role"] == "tool"
    assert sanitized[1]["tool_call_id"] == "call_1"
    payload = json.loads(sanitized[1]["content"])
    assert payload["code"] == "missing_tool_result_synthetic"


def test_compression_does_not_merge_summary_into_assistant_tool_call_tail():
    compressor = ContextCompressor()
    messages = [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi"},
        {"role": "user", "content": "old request"},
        {"role": "assistant", "content": "old answer"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{
                "id": "call_1",
                "type": "function",
                "function": {"name": "lookup", "arguments": "{}"},
            }],
        },
        {"role": "tool", "tool_call_id": "call_1", "content": "result"},
    ]

    compressed = compressor._assemble_compressed_messages(
        messages,
        compress_start=3,
        compress_end=4,
        summary="## Active Task\nContinue lookup.",
    )

    assert compressed[3]["role"] == "user"
    assert compressed[3]["metadata"]["context_compressed"] is True
    assert compressed[4]["role"] == "assistant"
    assert compressed[4]["tool_calls"][0]["id"] == "call_1"
    assert compressed[4]["content"] == ""
    assert "context_compressed" not in (compressed[4].get("metadata") or {})
