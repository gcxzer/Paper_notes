from __future__ import annotations

from app_config.ai_settings import CODEX_PROVIDER, OPENAI_PROVIDER
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
        ModelOption("gpt-5.2-codex", "GPT-5.2 Codex", "5.2 codex", "Older Codex-compatible"),
        ModelOption("gpt-5.1-codex-max", "GPT-5.1 Codex Max", "5.1 max", "Long-running tasks"),
        ModelOption("gpt-5.1-codex-mini", "GPT-5.1 Codex mini", "5.1 mini", "Smaller Codex model"),
    ),
)

BUILTIN_PROFILES = (OPENAI_PROFILE, CODEX_PROFILE)
