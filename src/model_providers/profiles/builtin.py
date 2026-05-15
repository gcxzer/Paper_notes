from __future__ import annotations

from app_config.ai_settings import ANTHROPIC_PROVIDER, CODEX_PROVIDER, DEEPSEEK_PROVIDER, GEMINI_PROVIDER, OPENAI_PROVIDER
from model_providers.profiles.types import ModelCapabilities, ModelOption, ModelProviderProfile


OPENAI_CAPABILITIES = ModelCapabilities(
    supports_tools=True,
    supports_vision=True,
    supports_image_generation=True,
    supports_web_search=True,
    image_input_mode="native",
)

CODEX_CAPABILITIES = ModelCapabilities(
    supports_tools=True,
    supports_vision=True,
    supports_image_generation=False,
    supports_web_search=True,
    image_input_mode="native",
)

ANTHROPIC_CAPABILITIES = ModelCapabilities(
    supports_tools=True,
    supports_vision=True,
    supports_image_generation=False,
    supports_web_search=True,
    image_input_mode="native",
)

GEMINI_CAPABILITIES = ModelCapabilities(
    supports_tools=True,
    supports_vision=True,
    supports_image_generation=False,
    supports_web_search=True,
    image_input_mode="native",
)

DEEPSEEK_CAPABILITIES = ModelCapabilities(
    supports_tools=True,
    supports_vision=False,
    supports_image_generation=False,
    supports_web_search=False,
    image_input_mode="unsupported",
)


OPENAI_PROFILE = ModelProviderProfile(
    name=OPENAI_PROVIDER,
    display_name="OpenAI API key",
    auth_type="api_key",
    description="Uses a local OpenAI API key with the public Responses API.",
    default_model="gpt-5.5",
    default_capabilities=OPENAI_CAPABILITIES,
    models=(
        ModelOption("gpt-5.5", "GPT-5.5", "5.5", "Best quality"),
        ModelOption("gpt-5.4", "GPT-5.4", "5.4", "Balanced"),
        ModelOption("gpt-5.4-mini", "GPT-5.4 mini", "5.4 mini", "Faster, lower cost"),
        ModelOption("gpt-5.4-nano", "GPT-5.4 nano", "5.4 nano", "Fastest, lowest cost"),
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
        ModelOption("gpt-5.5", "GPT-5.5", "5.5", "Best Codex OAuth default"),
        ModelOption("gpt-5.4-mini", "GPT-5.4 mini", "5.4 mini", "Faster Codex model"),
        ModelOption("gpt-5.4", "GPT-5.4", "5.4", "Codex CLI family"),
        ModelOption("gpt-5.3-codex", "GPT-5.3 Codex", "5.3 codex", "Codex-optimized"),
    ),
)

ANTHROPIC_PROFILE = ModelProviderProfile(
    name=ANTHROPIC_PROVIDER,
    display_name="Anthropic",
    auth_type="api_key",
    description="Uses an Anthropic API key with the native Claude Messages API.",
    default_model="claude-sonnet-4-6",
    aliases=("claude",),
    default_capabilities=ANTHROPIC_CAPABILITIES,
    models=(
        ModelOption("claude-opus-4-7", "Claude Opus 4.7", "Opus 4.7", "Most capable Claude model for complex reasoning, coding, and vision"),
        ModelOption("claude-sonnet-4-6", "Claude Sonnet 4.6", "Sonnet 4.6", "Balanced Claude model for everyday agent work"),
        ModelOption("claude-haiku-4-5-20251001", "Claude Haiku 4.5", "Haiku 4.5", "Fastest Claude model with strong tool and vision support"),
    ),
)

GEMINI_PROFILE = ModelProviderProfile(
    name=GEMINI_PROVIDER,
    display_name="Google Gemini",
    auth_type="api_key",
    description="Uses a Google AI Studio Gemini API key with the native Gemini API.",
    default_model="gemini-3-flash-preview",
    aliases=("google", "google-gemini", "google-ai-studio"),
    default_capabilities=GEMINI_CAPABILITIES,
    models=(
        ModelOption("gemini-3-flash-preview", "Gemini 3 Flash Preview", "3 Flash", "Frontier Gemini 3 model balanced for speed and intelligence"),
        ModelOption("gemini-3-pro-preview", "Gemini 3 Pro Preview", "3 Pro", "Most capable Gemini 3 model for complex reasoning and agentic work"),
    ),
)

DEEPSEEK_PROFILE = ModelProviderProfile(
    name=DEEPSEEK_PROVIDER,
    display_name="DeepSeek",
    auth_type="api_key",
    description="Uses a DeepSeek API key with the OpenAI-compatible chat completions API.",
    default_model="deepseek-v4-flash",
    default_capabilities=DEEPSEEK_CAPABILITIES,
    models=(
        ModelOption("deepseek-v4-flash", "DeepSeek V4 Flash", "V4 Flash", "Default DeepSeek V4 model for fast chat and agent work"),
        ModelOption("deepseek-v4-pro", "DeepSeek V4 Pro", "V4 Pro", "Higher-quality DeepSeek V4 model for stronger reasoning"),
    ),
)

BUILTIN_PROFILES = (OPENAI_PROFILE, CODEX_PROFILE, ANTHROPIC_PROFILE, GEMINI_PROFILE, DEEPSEEK_PROFILE)
