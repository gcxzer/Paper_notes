from __future__ import annotations

from typing import Any

from langchain_anthropic import ChatAnthropic

from model_providers.core.types import ModelProviderConfig, model_kwargs
from model_providers.providers.credentials import with_resolved_api_key


ANTHROPIC_OPTIONS = {
    "anthropic_proxy": "anthropic_proxy",
    "base_url": "base_url",
    "betas": "betas",
    "context_management": "context_management",
    "default_headers": "default_headers",
    "effort": "effort",
    "inference_geo": "inference_geo",
    "max_retries": "max_retries",
    "max_tokens": "max_tokens_to_sample",
    "mcp_servers": "mcp_servers",
    "model_kwargs": "model_kwargs",
    "output_config": "output_config",
    "reuse_last_container": "reuse_last_container",
    "stop": "stop",
    "stop_sequences": "stop",
    "stream_usage": "stream_usage",
    "streaming": "streaming",
    "temperature": "temperature",
    "thinking": "thinking",
    "timeout": "timeout",
    "top_k": "top_k",
    "top_p": "top_p",
}


def create_anthropic_chat_model(config: ModelProviderConfig) -> Any:
    kwargs = model_kwargs(config, ANTHROPIC_OPTIONS)
    kwargs["model_name"] = kwargs.pop("model")
    kwargs = with_resolved_api_key(kwargs, "anthropic")
    return ChatAnthropic(**kwargs)
