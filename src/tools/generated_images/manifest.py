from __future__ import annotations

from tools.toolsets import BUILTIN_TOOL_GROUPS


TOOL_NAME = "create_image_artifact"
TOOLSET = "generated_artifacts"
TOOL_GROUP = BUILTIN_TOOL_GROUPS[TOOLSET]
API_IMAGE_MODEL = "gpt-image-2"
DEFAULT_QUALITY = "medium"
DEFAULT_SIZE = "1024x1024"
MAX_INPUT_IMAGES = 4
VALID_MODES = {"generate", "edit", "auto"}
VALID_SIZES = {"1536x1024", "1024x1024", "1024x1536"}
VALID_QUALITIES = {"low", "medium", "high", "auto"}

def register_tools(registry, **kwargs):
    from tools.generated_images.tool import register_generated_image_tool

    return register_generated_image_tool(registry, **kwargs)


__all__ = [
    "API_IMAGE_MODEL",
    "DEFAULT_QUALITY",
    "DEFAULT_SIZE",
    "MAX_INPUT_IMAGES",
    "TOOL_GROUP",
    "TOOL_NAME",
    "TOOLSET",
    "VALID_MODES",
    "VALID_QUALITIES",
    "VALID_SIZES",
    "register_tools",
]
