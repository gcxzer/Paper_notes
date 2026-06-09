from __future__ import annotations

from model_providers.profiles.types import ModelCapabilities, ModelOption, ModelProviderProfile


OPENAI_PROVIDER = "openai"
CODEX_PROVIDER = "codex-oauth"
ANTHROPIC_PROVIDER = "anthropic"
GEMINI_PROVIDER = "gemini"
DEEPSEEK_PROVIDER = "deepseek"

DEFAULT_FALLBACK_CONTEXT_LENGTH = 256_000

OPENAI_CONTEXT_WINDOWS: dict[str, int] = {
    "gpt-5.5": 1_050_000,
    "gpt-5.4-nano": 400_000,
    "gpt-5.4-mini": 400_000,
    "gpt-5.4": 1_050_000,
}

CODEX_CONTEXT_WINDOWS: dict[str, int] = {
    "gpt-5.3-codex": 258_000,
    "gpt-5.3-codex-spark": 128_000,
    "gpt-5.4-mini": 258_000,
    "gpt-5.5": 258_000,
    "gpt-5.4": 258_000,
}

ANTHROPIC_CONTEXT_WINDOWS: dict[str, int] = {
    "claude-opus-4-7": 1_000_000,
    "claude-sonnet-4-6": 1_000_000,
    "claude-haiku-4-5": 200_000,
}

GEMINI_CONTEXT_WINDOWS: dict[str, int] = {
    "gemini-3-flash-preview": 1_048_576,
    "gemini-3-pro-preview": 1_048_576,
}

DEEPSEEK_CONTEXT_WINDOWS: dict[str, int] = {
    "deepseek-v4-flash": 1_000_000,
    "deepseek-v4-pro": 1_000_000,
}

CONTEXT_WINDOW_TABLES_BY_PROVIDER: dict[str, dict[str, int]] = {
    OPENAI_PROVIDER: OPENAI_CONTEXT_WINDOWS,
    CODEX_PROVIDER: CODEX_CONTEXT_WINDOWS,
    ANTHROPIC_PROVIDER: ANTHROPIC_CONTEXT_WINDOWS,
    GEMINI_PROVIDER: GEMINI_CONTEXT_WINDOWS,
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

ANTHROPIC_CAPABILITIES = ModelCapabilities(
    supports_tools=True,
    supports_vision=True,
    supports_image_generation=False,
    supports_web_search=True,
    image_input_mode="native",
    context_window=ANTHROPIC_CONTEXT_WINDOWS["claude-sonnet-4-6"],
)

GEMINI_CAPABILITIES = ModelCapabilities(
    supports_tools=True,
    supports_vision=True,
    supports_image_generation=False,
    supports_web_search=True,
    image_input_mode="native",
    context_window=GEMINI_CONTEXT_WINDOWS["gemini-3-flash-preview"],
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
        ModelOption("gpt-5.3-codex", "GPT-5.3 Codex", "5.3 codex", "Codex-optimized", CODEX_CAPABILITIES.with_context_window(CODEX_CONTEXT_WINDOWS["gpt-5.3-codex"])),
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
                supports_web_search=False,
                supports_reasoning_off=False,
                image_input_mode="unsupported",
                context_window=CODEX_CONTEXT_WINDOWS["gpt-5.3-codex-spark"],
            ),
        ),
    ),
)

ANTHROPIC_PROFILE = ModelProviderProfile(
    name=ANTHROPIC_PROVIDER,
    display_name="Anthropic",
    auth_type="api_key",
    description="Uses an Anthropic API key with LangChain's Anthropic chat model.",
    default_model="claude-sonnet-4-6",
    aliases=("claude",),
    default_capabilities=ANTHROPIC_CAPABILITIES,
    models=(
        ModelOption("claude-opus-4-7", "Claude Opus 4.7", "Opus 4.7", "Most capable Claude model for complex reasoning, coding, and vision", ANTHROPIC_CAPABILITIES.with_context_window(ANTHROPIC_CONTEXT_WINDOWS["claude-opus-4-7"])),
        ModelOption("claude-sonnet-4-6", "Claude Sonnet 4.6", "Sonnet 4.6", "Balanced Claude model for everyday agent work", ANTHROPIC_CAPABILITIES.with_context_window(ANTHROPIC_CONTEXT_WINDOWS["claude-sonnet-4-6"])),
        ModelOption("claude-haiku-4-5-20251001", "Claude Haiku 4.5", "Haiku 4.5", "Fastest Claude model with strong tool and vision support", ANTHROPIC_CAPABILITIES.with_context_window(ANTHROPIC_CONTEXT_WINDOWS["claude-haiku-4-5"])),
    ),
)

GEMINI_PROFILE = ModelProviderProfile(
    name=GEMINI_PROVIDER,
    display_name="Google Gemini",
    auth_type="api_key",
    description="Uses a Google AI Studio Gemini API key with LangChain's Gemini chat model.",
    default_model="gemini-3-flash-preview",
    aliases=("google", "google-gemini", "google-ai-studio"),
    default_capabilities=GEMINI_CAPABILITIES,
    models=(
        ModelOption("gemini-3-flash-preview", "Gemini 3 Flash Preview", "3 Flash", "Frontier Gemini 3 model balanced for speed and intelligence", GEMINI_CAPABILITIES.with_context_window(GEMINI_CONTEXT_WINDOWS["gemini-3-flash-preview"])),
        ModelOption("gemini-3-pro-preview", "Gemini 3 Pro Preview", "3 Pro", "Most capable Gemini 3 model for complex reasoning and agentic work", GEMINI_CAPABILITIES.with_context_window(GEMINI_CONTEXT_WINDOWS["gemini-3-pro-preview"])),
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

BUILTIN_PROFILES = (OPENAI_PROFILE, CODEX_PROFILE, ANTHROPIC_PROFILE, GEMINI_PROFILE, DEEPSEEK_PROFILE)
