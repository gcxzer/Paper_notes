"""说明：实现 DeepSeek 聊天模型 provider。

作用：把 DeepSeek 配置转换成 LangChain 可用的 chat model。
"""

from __future__ import annotations

from typing import Any

from langchain_deepseek import ChatDeepSeek

from model_providers.core.types import ModelProviderConfig, model_kwargs
from model_providers.providers.credentials import with_resolved_api_key


DEEPSEEK_OPTIONS = {
    "base_url": "base_url",
    "context_management": "context_management",
    "default_headers": "default_headers",
    "default_query": "default_query",
    "disabled_params": "disabled_params",
    "extra_body": "extra_body",
    "frequency_penalty": "frequency_penalty",
    "include": "include",
    "include_response_headers": "include_response_headers",
    "logit_bias": "logit_bias",
    "logprobs": "logprobs",
    "max_retries": "max_retries",
    "max_tokens": "max_tokens",
    "model_kwargs": "model_kwargs",
    "n": "n",
    "organization": "organization",
    "presence_penalty": "presence_penalty",
    "reasoning": "reasoning",
    "reasoning_effort": "reasoning_effort",
    "seed": "seed",
    "service_tier": "service_tier",
    "stop_sequences": "stop_sequences",
    "store": "store",
    "stream_usage": "stream_usage",
    "streaming": "streaming",
    "temperature": "temperature",
    "timeout": "timeout",
    "tiktoken_model_name": "tiktoken_model_name",
    "top_logprobs": "top_logprobs",
    "top_p": "top_p",
    "truncation": "truncation",
    "use_previous_response_id": "use_previous_response_id",
    "use_responses_api": "use_responses_api",
    "verbosity": "verbosity",
}


def create_deepseek_chat_model(config: ModelProviderConfig) -> Any:
    return ChatDeepSeek(**with_resolved_api_key(_deepseek_model_kwargs(config), "deepseek"))


def _deepseek_model_kwargs(config: ModelProviderConfig) -> dict[str, Any]:
    kwargs = model_kwargs(config, DEEPSEEK_OPTIONS)
    thinking = config.options.get("thinking")
    if thinking is not None:
        extra_body = dict(kwargs.get("extra_body") or {})
        extra_body["thinking"] = thinking
        kwargs["extra_body"] = extra_body
    return kwargs
