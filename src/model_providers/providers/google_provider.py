from __future__ import annotations

from typing import Any

from langchain_google_genai import ChatGoogleGenerativeAI

from model_providers.core.types import ModelProviderConfig, model_kwargs


GOOGLE_OPTIONS = {
    "additional_headers": "additional_headers",
    "api_version": "api_version",
    "base_url": "client_options",
    "cached_content": "cached_content",
    "client_args": "client_args",
    "client_options": "client_options",
    "convert_system_message_to_human": "convert_system_message_to_human",
    "default_metadata": "default_metadata_input",
    "image_config": "image_config",
    "include_thoughts": "include_thoughts",
    "labels": "labels",
    "location": "location",
    "max_retries": "retries",
    "max_tokens": "max_tokens",
    "media_resolution": "media_resolution",
    "model_kwargs": "model_kwargs",
    "n": "n",
    "project": "project",
    "request_timeout": "request_timeout",
    "response_mime_type": "response_mime_type",
    "response_modalities": "response_modalities",
    "response_schema": "response_schema",
    "safety_settings": "safety_settings",
    "seed": "seed",
    "stop": "stop",
    "stop_sequences": "stop",
    "streaming": "streaming",
    "temperature": "temperature",
    "thinking_budget": "thinking_budget",
    "thinking_level": "thinking_level",
    "timeout": "request_timeout",
    "top_k": "top_k",
    "top_p": "top_p",
    "vertexai": "vertexai",
}


def create_google_chat_model(config: ModelProviderConfig) -> Any:
    return ChatGoogleGenerativeAI(**model_kwargs(config, GOOGLE_OPTIONS))
