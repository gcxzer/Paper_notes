"""说明：实现 OpenAI 聊天模型 provider。

作用：负责按配置创建 OpenAI chat model，并处理模型能力相关参数。
"""

from __future__ import annotations

from typing import Any

from langchain_openai import ChatOpenAI

from model_providers.core.types import ModelProviderConfig, model_kwargs
from model_providers.providers.credentials import with_resolved_api_key


OPENAI_OPTIONS = {
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
    "max_tokens": "max_completion_tokens",
    "model_kwargs": "model_kwargs",
    "n": "n",
    "organization": "organization",
    "output_version": "output_version",
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


def create_openai_chat_model(config: ModelProviderConfig) -> Any:
    return ChatOpenAI(**with_resolved_api_key(model_kwargs(config, OPENAI_OPTIONS), "openai"))
