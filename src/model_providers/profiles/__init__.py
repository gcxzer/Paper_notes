"""说明：导出模型 profile 注册表。

作用：让设置页和运行时读取内置/自定义模型能力描述。
"""

from model_providers.profiles.builtin import DEFAULT_FALLBACK_CONTEXT_LENGTH
from model_providers.profiles.registry import (
    capabilities_for_provider_model,
    get_provider_profile,
    list_provider_profiles,
    model_options_for_provider,
    normalize_provider_profile_name,
    register_provider_profile,
    resolve_context_length_for_model,
)
from model_providers.profiles.types import (
    ModelCapabilities,
    ModelOption,
    ModelProviderProfile,
)

__all__ = [
    "DEFAULT_FALLBACK_CONTEXT_LENGTH",
    "ModelCapabilities",
    "ModelOption",
    "ModelProviderProfile",
    "capabilities_for_provider_model",
    "get_provider_profile",
    "list_provider_profiles",
    "model_options_for_provider",
    "normalize_provider_profile_name",
    "register_provider_profile",
    "resolve_context_length_for_model",
]
