from __future__ import annotations

from typing import Any

import pytest

from app_config.secrets import write_env_values
from model_providers.core.types import ModelProviderConfig
from model_providers.providers import deepseek_provider, openai_provider


API_ENV_NAMES = (
    "DEEPSEEK_API_KEY",
    "OPENAI_API_KEY",
)


def _isolate_provider_env(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    for name in API_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("PAPER_NOTES_ENV_PATHS", str(tmp_path / "missing.env"))
    monkeypatch.setenv("PAPER_NOTES_SECRETS_PATH", str(tmp_path / "secrets.env"))


def _capture_constructor(monkeypatch: pytest.MonkeyPatch, module: Any, name: str) -> dict[str, Any]:
    captured: dict[str, Any] = {}

    class FakeChatModel:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)

    monkeypatch.setattr(module, name, FakeChatModel)
    return captured


def test_openai_provider_passes_local_api_key(monkeypatch, tmp_path):
    _isolate_provider_env(monkeypatch, tmp_path)
    write_env_values(tmp_path / "secrets.env", {"OPENAI_API_KEY": "sk-local-openai"})
    captured = _capture_constructor(monkeypatch, openai_provider, "ChatOpenAI")

    openai_provider.create_openai_chat_model(ModelProviderConfig("openai", "gpt-test", {}))

    assert captured["model"] == "gpt-test"
    assert captured["api_key"] == "sk-local-openai"


def test_openai_provider_passes_reasoning_options(monkeypatch, tmp_path):
    _isolate_provider_env(monkeypatch, tmp_path)
    write_env_values(tmp_path / "secrets.env", {"OPENAI_API_KEY": "sk-local-openai"})
    captured = _capture_constructor(monkeypatch, openai_provider, "ChatOpenAI")

    openai_provider.create_openai_chat_model(ModelProviderConfig(
        "openai",
        "gpt-test",
        {
            "use_responses_api": True,
            "output_version": "responses/v1",
            "reasoning": {"effort": "none"},
        },
    ))

    assert captured["use_responses_api"] is True
    assert captured["output_version"] == "responses/v1"
    assert captured["reasoning"] == {"effort": "none"}


def test_deepseek_provider_passes_local_api_key(monkeypatch, tmp_path):
    _isolate_provider_env(monkeypatch, tmp_path)
    write_env_values(tmp_path / "secrets.env", {"DEEPSEEK_API_KEY": "sk-local-deepseek"})
    captured = _capture_constructor(monkeypatch, deepseek_provider, "ChatDeepSeek")

    deepseek_provider.create_deepseek_chat_model(ModelProviderConfig("deepseek", "deepseek-test", {}))

    assert captured["model"] == "deepseek-test"
    assert captured["api_key"] == "sk-local-deepseek"


def test_deepseek_provider_passes_thinking_option_in_extra_body(monkeypatch, tmp_path):
    _isolate_provider_env(monkeypatch, tmp_path)
    write_env_values(tmp_path / "secrets.env", {"DEEPSEEK_API_KEY": "sk-local-deepseek"})
    captured = _capture_constructor(monkeypatch, deepseek_provider, "ChatDeepSeek")

    deepseek_provider.create_deepseek_chat_model(ModelProviderConfig(
        "deepseek",
        "deepseek-v4-flash",
        {
            "thinking": {"type": "disabled"},
            "extra_body": {"response_format": {"type": "json_object"}},
        },
    ))

    assert captured["extra_body"] == {
        "response_format": {"type": "json_object"},
        "thinking": {"type": "disabled"},
    }
