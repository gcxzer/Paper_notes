from __future__ import annotations

from model_providers.profiles.types import ModelCapabilities, ModelOption, ModelProviderProfile


OPENAI_PROVIDER = "openai"
CODEX_PROVIDER = "codex-oauth"
DEEPSEEK_PROVIDER = "deepseek"

DEFAULT_FALLBACK_CONTEXT_LENGTH = 256_000

OPENAI_CONTEXT_WINDOWS: dict[str, int] = {
    "gpt-5.5": 1_050_000,
    "gpt-5.4-nano": 400_000,
    "gpt-5.4-mini": 400_000,
    "gpt-5.4": 1_050_000,
}

CODEX_CONTEXT_WINDOWS: dict[str, int] = {
    "gpt-5.3-codex-spark": 128_000,
    "gpt-5.4-mini": 258_000,
    "gpt-5.5": 258_000,
    "gpt-5.4": 258_000,
}

DEEPSEEK_CONTEXT_WINDOWS: dict[str, int] = {
    "deepseek-v4-flash": 1_000_000,
    "deepseek-v4-pro": 1_000_000,
}

CONTEXT_WINDOW_TABLES_BY_PROVIDER: dict[str, dict[str, int]] = {
    OPENAI_PROVIDER: OPENAI_CONTEXT_WINDOWS,
    CODEX_PROVIDER: CODEX_CONTEXT_WINDOWS,
    DEEPSEEK_PROVIDER: DEEPSEEK_CONTEXT_WINDOWS,
}


OPENAI_CAPABILITIES = ModelCapabilities(
    supports_tools=True,
    supports_vision=True,
    supports_image_generation=True,
    supports_image_artifact_generation=True,
    supports_web_search=True,
    image_input_mode="native",
    context_window=OPENAI_CONTEXT_WINDOWS["gpt-5.5"],
)

CODEX_CAPABILITIES = ModelCapabilities(
    supports_tools=True,
    supports_vision=True,
    supports_image_generation=False,
    supports_image_artifact_generation=True,
    supports_web_search=True,
    image_input_mode="native",
    context_window=CODEX_CONTEXT_WINDOWS["gpt-5.5"],
)

DEEPSEEK_CAPABILITIES = ModelCapabilities(
    supports_tools=True,
    supports_vision=False,
    supports_image_generation=False,
    supports_web_search=False,
    image_input_mode="unsupported",
    context_window=DEEPSEEK_CONTEXT_WINDOWS["deepseek-v4-flash"],
)


OPENAI_PROFILE = ModelProviderProfile(
    name=OPENAI_PROVIDER,
    display_name="OpenAI API key",
    auth_type="api_key",
    description="Uses a local OpenAI API key with LangChain's OpenAI chat model.",
    default_model="gpt-5.5",
    default_capabilities=OPENAI_CAPABILITIES,
    models=(
        ModelOption("gpt-5.5", "GPT-5.5", "5.5", "Best quality", OPENAI_CAPABILITIES.with_context_window(OPENAI_CONTEXT_WINDOWS["gpt-5.5"])),
        ModelOption("gpt-5.4", "GPT-5.4", "5.4", "Balanced", OPENAI_CAPABILITIES.with_context_window(OPENAI_CONTEXT_WINDOWS["gpt-5.4"])),
        ModelOption("gpt-5.4-mini", "GPT-5.4 mini", "5.4 mini", "Faster, lower cost", OPENAI_CAPABILITIES.with_context_window(OPENAI_CONTEXT_WINDOWS["gpt-5.4-mini"])),
        ModelOption("gpt-5.4-nano", "GPT-5.4 nano", "5.4 nano", "Fastest, lowest cost", OPENAI_CAPABILITIES.with_context_window(OPENAI_CONTEXT_WINDOWS["gpt-5.4-nano"])),
    ),
)

CODEX_PROFILE = ModelProviderProfile(
    name=CODEX_PROVIDER,
    display_name="Codex OAuth",
    auth_type="oauth_device_code",
    description="Uses a local ChatGPT/Codex OAuth token through the Codex backend.",
    default_model="gpt-5.5",
    aliases=("codex", "openai-codex"),
    default_capabilities=CODEX_CAPABILITIES,
    models=(
        ModelOption("gpt-5.5", "GPT-5.5", "5.5", "Best Codex OAuth default", CODEX_CAPABILITIES.with_context_window(CODEX_CONTEXT_WINDOWS["gpt-5.5"])),
        ModelOption("gpt-5.4-mini", "GPT-5.4 mini", "5.4 mini", "Faster Codex model", CODEX_CAPABILITIES.with_context_window(CODEX_CONTEXT_WINDOWS["gpt-5.4-mini"])),
        ModelOption("gpt-5.4", "GPT-5.4", "5.4", "Codex CLI family", CODEX_CAPABILITIES.with_context_window(CODEX_CONTEXT_WINDOWS["gpt-5.4"])),
        ModelOption(
            "gpt-5.3-codex-spark",
            "GPT-5.3 Codex Spark",
            "5.3 spark",
            "Ultra-fast Codex research preview",
            ModelCapabilities(
                supports_tools=True,
                supports_vision=False,
                supports_image_generation=False,
                supports_image_artifact_generation=False,
                supports_web_search=True,
                supports_reasoning_off=False,
                image_input_mode="unsupported",
                context_window=CODEX_CONTEXT_WINDOWS["gpt-5.3-codex-spark"],
            ),
        ),
    ),
)

DEEPSEEK_PROFILE = ModelProviderProfile(
    name=DEEPSEEK_PROVIDER,
    display_name="DeepSeek",
    auth_type="api_key",
    description="Uses a DeepSeek API key with LangChain's DeepSeek chat model.",
    default_model="deepseek-v4-flash",
    default_capabilities=DEEPSEEK_CAPABILITIES,
    models=(
        ModelOption("deepseek-v4-flash", "DeepSeek V4 Flash", "V4 Flash", "Default DeepSeek V4 model for fast chat and agent work", DEEPSEEK_CAPABILITIES.with_context_window(DEEPSEEK_CONTEXT_WINDOWS["deepseek-v4-flash"])),
        ModelOption("deepseek-v4-pro", "DeepSeek V4 Pro", "V4 Pro", "Higher-quality DeepSeek V4 model for stronger reasoning", DEEPSEEK_CAPABILITIES.with_context_window(DEEPSEEK_CONTEXT_WINDOWS["deepseek-v4-pro"])),
    ),
)

BUILTIN_PROFILES = (OPENAI_PROFILE, CODEX_PROFILE, DEEPSEEK_PROFILE)
