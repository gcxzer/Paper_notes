from __future__ import annotations

import os
import webbrowser
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from openai_codex import ApprovalMode, Codex, CodexConfig, Sandbox

from model_providers.core.types import ModelProviderConfig


CODEX_CONFIG_OPTIONS = {
    "codex_bin",
    "launch_args_override",
    "config_overrides",
    "cwd",
    "env",
    "client_name",
    "client_title",
    "client_version",
    "experimental_api",
}
CODEX_THREAD_OPTIONS = {
    "approval_mode",
    "base_instructions",
    "config",
    "cwd",
    "developer_instructions",
    "ephemeral",
    "model_provider",
    "personality",
    "sandbox",
    "service_name",
    "service_tier",
    "session_start_source",
    "thread_source",
}
CODEX_RUN_OPTIONS = {
    "approval_mode",
    "cwd",
    "effort",
    "output_schema",
    "personality",
    "sandbox",
    "service_tier",
    "summary",
}


class CodexChatModel(BaseChatModel):
    model: str
    options: dict[str, Any] = {}

    @property
    def _llm_type(self) -> str:
        return "openai-codex"

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        del stop, run_manager
        options = {**self.options, **kwargs}
        prompt = _messages_to_prompt(messages)
        codex_config = _codex_config(options)
        thread_options = _thread_options(options, model=self.model)
        run_options = _run_options(options)

        try:
            result = _run_codex_turn(codex_config, thread_options, prompt, run_options)
        except Exception as error:
            if not _should_try_auth_fallback(error):
                raise
            result = _run_with_auth_fallback(codex_config, thread_options, prompt, run_options, options, error)

        content = result.final_response or ""
        generation = ChatGeneration(
            message=AIMessage(content=content),
            generation_info={
                "turn_id": result.id,
                "status": str(result.status),
                "duration_ms": result.duration_ms,
            },
        )
        return ChatResult(generations=[generation], llm_output={"usage": result.usage})


def create_codex_chat_model(config: ModelProviderConfig) -> CodexChatModel:
    return CodexChatModel(model=config.model, options=dict(config.options))


def _run_codex_turn(
    codex_config: CodexConfig | None,
    thread_options: dict[str, Any],
    prompt: str,
    run_options: dict[str, Any],
) -> Any:
    with Codex(codex_config) as codex:
        thread = codex.thread_start(**thread_options)
        return thread.run(prompt, **run_options)


def _run_with_auth_fallback(
    codex_config: CodexConfig | None,
    thread_options: dict[str, Any],
    prompt: str,
    run_options: dict[str, Any],
    options: dict[str, Any],
    original_error: Exception,
) -> Any:
    last_error: Exception = original_error
    for method in _auth_fallbacks(options):
        with Codex(codex_config) as codex:
            try:
                _login_codex(codex, method, options)
                thread = codex.thread_start(**thread_options)
                return thread.run(prompt, **run_options)
            except Exception as error:
                last_error = error
    raise last_error


def _messages_to_prompt(messages: list[BaseMessage]) -> str:
    parts: list[str] = []
    for message in messages:
        role = getattr(message, "type", "message")
        content = message.content
        if isinstance(content, str):
            text = content
        else:
            text = str(content)
        if text:
            parts.append(f"{role}: {text}")
    return "\n\n".join(parts)


def _codex_config(options: dict[str, Any]) -> CodexConfig | None:
    kwargs = {key: options[key] for key in CODEX_CONFIG_OPTIONS if key in options}
    if not kwargs:
        return None
    if "launch_args_override" in kwargs and isinstance(kwargs["launch_args_override"], list):
        kwargs["launch_args_override"] = tuple(str(item) for item in kwargs["launch_args_override"])
    if "config_overrides" in kwargs and isinstance(kwargs["config_overrides"], list):
        kwargs["config_overrides"] = tuple(str(item) for item in kwargs["config_overrides"])
    return CodexConfig(**kwargs)


def _thread_options(options: dict[str, Any], *, model: str) -> dict[str, Any]:
    kwargs = {key: options[key] for key in CODEX_THREAD_OPTIONS if key in options}
    kwargs["model"] = model
    if "approval_mode" in kwargs:
        kwargs["approval_mode"] = _approval_mode(kwargs["approval_mode"])
    if "sandbox" in kwargs:
        kwargs["sandbox"] = _sandbox(kwargs["sandbox"])
    return kwargs


def _run_options(options: dict[str, Any]) -> dict[str, Any]:
    kwargs = {key: options[key] for key in CODEX_RUN_OPTIONS if key in options}
    if "approval_mode" in kwargs:
        kwargs["approval_mode"] = _approval_mode(kwargs["approval_mode"])
    if "sandbox" in kwargs:
        kwargs["sandbox"] = _sandbox(kwargs["sandbox"])
    return kwargs


def _sandbox(value: Any) -> Sandbox:
    if isinstance(value, Sandbox):
        return value
    text = str(value).strip().replace("-", "_")
    try:
        return getattr(Sandbox, text)
    except AttributeError as error:
        raise ValueError(f"Unsupported Codex sandbox: {value}") from error


def _approval_mode(value: Any) -> ApprovalMode:
    if isinstance(value, ApprovalMode):
        return value
    text = str(value).strip().replace("-", "_")
    try:
        return getattr(ApprovalMode, text)
    except AttributeError as error:
        raise ValueError(f"Unsupported Codex approval mode: {value}") from error


def _should_try_auth_fallback(error: Exception) -> bool:
    text = str(error).lower()
    auth_markers = ("auth", "login", "account", "api key", "unauthorized", "credential", "401")
    return any(marker in text for marker in auth_markers)


def _auth_fallbacks(options: dict[str, Any]) -> list[str]:
    raw = options.get("auth_fallbacks", options.get("auth_fallback", ["chatgpt"]))
    if raw is False or raw is None:
        return []
    if isinstance(raw, str):
        return [raw]
    if isinstance(raw, list):
        return [str(item) for item in raw]
    raise ValueError("Codex auth_fallbacks must be a string, list, false, or null.")


def _login_codex(codex: Codex, method: str, options: dict[str, Any]) -> None:
    normalized = method.strip().lower().replace("-", "_")
    if normalized in {"chatgpt", "browser", "browser_login"}:
        handle = codex.login_chatgpt()
        webbrowser.open(handle.auth_url)
        handle.wait()
        return
    if normalized in {"device_code", "chatgpt_device_code"}:
        handle = codex.login_chatgpt_device_code()
        print(f"Open {handle.verification_url} and enter code {handle.user_code}", flush=True)
        handle.wait()
        return
    if normalized in {"api_key", "api_key_env"}:
        env_name = str(options.get("api_key_env", "OPENAI_API_KEY"))
        api_key = os.getenv(env_name)
        if not api_key:
            raise ValueError(f"Codex API key fallback requires {env_name}.")
        codex.login_api_key(api_key)
        return
    raise ValueError(f"Unsupported Codex auth fallback: {method}")
