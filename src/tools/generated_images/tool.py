from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path
from typing import Any

from langchain_core.tools import StructuredTool

from app_config.ai_settings import CODEX_PROVIDER, OPENAI_PROVIDER, resolve_openai_api_key
from app_infra.formatting import normalize_text
from media import MediaStore, MediaStoreError
from model_providers.providers.codex_provider import (
    DEFAULT_CODEX_BASE_URL,
    _codex_default_headers,
    _runtime_codex_credentials,
)


CREATE_IMAGE_ARTIFACT_TOOL_NAME = "create_image_artifact"
GENERATED_ARTIFACTS_TOOLSET = "generated_artifacts"
API_IMAGE_MODEL = "gpt-image-2"
DEFAULT_QUALITY = "medium"
DEFAULT_SIZE = "1024x1024"
MAX_INPUT_IMAGES = 4
VALID_MODES = {"generate", "edit", "auto"}
VALID_SIZES = {"1536x1024", "1024x1024", "1024x1536"}
VALID_QUALITIES = {"low", "medium", "high", "auto"}


def create_tools(
    *,
    media_store: MediaStore | None = None,
    session_id: str = "",
    provider_name: str = "",
    model: str = "",
    image_generation: dict[str, Any] | None = None,
    attachments: list[dict[str, Any]] | None = None,
) -> list[StructuredTool]:
    if media_store is None or normalize_text(provider_name).lower() not in {OPENAI_PROVIDER, CODEX_PROVIDER}:
        return []
    return [
        StructuredTool(
            name=CREATE_IMAGE_ARTIFACT_TOOL_NAME,
            description=(
                "Create or edit a downloadable generated image artifact for the user when they ask for an image, "
                "diagram, visual, cover, or image edit. Use this instead of code execution, SVG, or local file writes."
            ),
            args_schema=create_image_artifact_parameters(),
            func=lambda **kwargs: create_image_artifact(
                dict(kwargs),
                media_store=media_store,
                session_id=session_id,
                provider_name=provider_name,
                model=model,
                image_generation=image_generation,
                attachments=attachments,
            ),
        )
    ]


def create_image_artifact_parameters() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "prompt": {
                "type": "string",
                "description": "Complete image generation or image edit instruction.",
            },
            "mode": {
                "type": "string",
                "enum": ["generate", "edit", "auto"],
                "default": "auto",
                "description": "Use edit when transforming provided input images; otherwise generate.",
            },
            "input_artifact_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional image artifact IDs from current attachments to use as edit/reference inputs.",
            },
        },
        "required": ["prompt"],
        "additionalProperties": False,
    }


def create_image_artifact(
    args: dict[str, Any],
    *,
    media_store: MediaStore,
    session_id: str = "",
    provider_name: str = "",
    model: str = "",
    image_generation: dict[str, Any] | None = None,
    attachments: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    prompt = normalize_text(args.get("prompt"))
    mode = normalize_text(args.get("mode") or "auto").lower()
    if mode not in VALID_MODES:
        mode = "auto"
    if not prompt:
        return {"success": False, "error": "prompt is required.", "code": "prompt_required"}
    config = dict(image_generation or {})
    size = _normalize_size(config.get("size"))
    quality = _normalize_quality(config.get("quality"))
    input_ids = _image_input_artifact_ids(args.get("input_artifact_ids") or args.get("inputArtifactIds"))
    if not input_ids:
        input_ids = _image_attachment_ids(list(attachments or []))
    if len(input_ids) > MAX_INPUT_IMAGES:
        return {
            "success": False,
            "error": f"At most {MAX_INPUT_IMAGES} input images are supported.",
            "code": "too_many_input_images",
        }
    provider = normalize_text(provider_name).lower()
    try:
        if provider == OPENAI_PROVIDER:
            result = _generate_with_openai(
                media_store,
                prompt=prompt,
                mode=mode,
                input_artifact_ids=input_ids,
                size=size,
                quality=quality,
                host_model=model,
                session_id=session_id,
            )
        elif provider == CODEX_PROVIDER:
            result = _generate_with_codex(
                media_store,
                prompt=prompt,
                mode=mode,
                input_artifact_ids=input_ids,
                size=size,
                quality=quality,
                host_model=model,
                session_id=session_id,
            )
        else:
            return {
                "success": False,
                "error": "Image generation is not configured for the current provider.",
                "code": "unsupported_provider",
            }
    except MediaStoreError as error:
        return {"success": False, "error": str(error), "code": "media_error"}
    if not result.get("success"):
        return result
    artifact = result["artifact"]
    return {
        "success": True,
        "changed": True,
        "summary": f"Generated {artifact.get('fileName') or 'image'}.",
        "artifact": artifact,
        "artifacts": [artifact],
    }


def _generate_with_openai(
    media_store: MediaStore,
    *,
    prompt: str,
    mode: str,
    input_artifact_ids: list[str],
    size: str,
    quality: str,
    host_model: str,
    session_id: str,
) -> dict[str, Any]:
    if not resolve_openai_api_key().value:
        return {
            "success": False,
            "error": "OPENAI_API_KEY is required for OpenAI image generation.",
            "code": "openai_api_key_required",
        }
    from openai import OpenAI

    client = OpenAI(api_key=resolve_openai_api_key().value)
    try:
        if input_artifact_ids or mode == "edit":
            response = _openai_image_edit(client, media_store, prompt, input_artifact_ids, size=size, quality=quality)
        else:
            response = client.images.generate(model=API_IMAGE_MODEL, prompt=prompt, size=size, n=1, quality=quality)
    except Exception as error:
        return {"success": False, "error": f"OpenAI image generation failed: {error}", "code": "api_error"}
    image_b64 = _image_b64_from_openai_response(response)
    if not image_b64:
        return {"success": False, "error": "OpenAI returned no image data.", "code": "empty_response"}
    artifact = media_store.create_generated_image(
        image_b64,
        session_id=session_id,
        provider=OPENAI_PROVIDER,
        model=host_model,
        file_format="png",
        metadata={
            "createdBy": CREATE_IMAGE_ARTIFACT_TOOL_NAME,
            "imageBackend": "openai",
            "imageModel": API_IMAGE_MODEL,
            "size": size,
            "quality": quality,
            "mode": mode,
        },
    )
    return {"success": True, "artifact": artifact.to_dict()}


def _generate_with_codex(
    media_store: MediaStore,
    *,
    prompt: str,
    mode: str,
    input_artifact_ids: list[str],
    size: str,
    quality: str,
    host_model: str,
    session_id: str,
) -> dict[str, Any]:
    credentials = _runtime_codex_credentials()
    if not credentials.access_token:
        return {
            "success": False,
            "error": "Codex OAuth is not connected. Open Settings > AI Provider and connect Codex OAuth.",
            "code": "codex_auth_required",
        }
    if not host_model:
        return {"success": False, "error": "A host model is required for Codex image generation.", "code": "model_required"}
    from openai import OpenAI

    client = OpenAI(
        api_key=credentials.access_token,
        base_url=(credentials.base_url or DEFAULT_CODEX_BASE_URL).rstrip("/"),
        default_headers=_codex_default_headers(credentials),
    )
    prompt_content: list[dict[str, Any]] = [{"type": "input_text", "text": prompt}]
    for artifact_id in input_artifact_ids:
        prompt_content.append({"type": "input_image", "image_url": media_store.data_url_for_artifact(artifact_id)})
    image_b64 = _collect_codex_image(client, host_model=host_model, prompt_content=prompt_content, size=size, quality=quality)
    if not image_b64:
        return {"success": False, "error": "Codex response contained no image result.", "code": "empty_response"}
    artifact = media_store.create_generated_image(
        image_b64,
        session_id=session_id,
        provider=CODEX_PROVIDER,
        model=host_model,
        file_format="png",
        metadata={
            "createdBy": CREATE_IMAGE_ARTIFACT_TOOL_NAME,
            "imageBackend": "codex-oauth",
            "imageModel": API_IMAGE_MODEL,
            "size": size,
            "quality": quality,
            "mode": mode,
        },
    )
    return {"success": True, "artifact": artifact.to_dict()}


def _collect_codex_image(
    client: Any,
    *,
    host_model: str,
    prompt_content: list[dict[str, Any]],
    size: str,
    quality: str,
) -> str:
    image_b64 = ""
    tool: dict[str, Any] = {
        "type": "image_generation",
        "model": API_IMAGE_MODEL,
        "size": size,
        "quality": quality,
        "output_format": "png",
        "background": "opaque",
        "partial_images": 1,
    }
    with client.responses.stream(
        model=host_model,
        store=False,
        instructions="Use the image_generation tool to fulfill the user's image request.",
        input=[{"type": "message", "role": "user", "content": prompt_content}],
        tools=[tool],
        tool_choice={"type": "allowed_tools", "mode": "required", "tools": [{"type": "image_generation"}]},
    ) as stream:
        for event in stream:
            event_type = getattr(event, "type", "")
            if event_type == "response.output_item.done":
                item = getattr(event, "item", None)
                result = getattr(item, "result", None) if getattr(item, "type", None) == "image_generation_call" else None
                if isinstance(result, str) and result:
                    image_b64 = result
            elif event_type == "response.image_generation_call.partial_image":
                partial = getattr(event, "partial_image_b64", None)
                if isinstance(partial, str) and partial:
                    image_b64 = partial
        final = stream.get_final_response()
    for item in getattr(final, "output", None) or []:
        result = getattr(item, "result", None) if getattr(item, "type", None) == "image_generation_call" else None
        if isinstance(result, str) and result:
            image_b64 = result
    return image_b64


def _openai_image_edit(
    client: Any,
    media_store: MediaStore,
    prompt: str,
    input_artifact_ids: list[str],
    *,
    size: str,
    quality: str,
) -> Any:
    if not input_artifact_ids:
        return client.images.generate(model=API_IMAGE_MODEL, prompt=prompt, size=size, n=1, quality=quality)
    with ExitStack() as stack:
        images = [stack.enter_context(Path(media_store.path_for(artifact_id)).open("rb")) for artifact_id in input_artifact_ids]
        return client.images.edit(model=API_IMAGE_MODEL, prompt=prompt, image=images, size=size, n=1, quality=quality)


def _image_b64_from_openai_response(response: Any) -> str:
    data = getattr(response, "data", None) or []
    if not data:
        return ""
    first = data[0]
    b64 = getattr(first, "b64_json", None)
    return b64 if isinstance(b64, str) else ""


def _image_input_artifact_ids(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [normalize_text(item) for item in value if normalize_text(item)]


def _image_attachment_ids(attachments: list[dict[str, Any]]) -> list[str]:
    ids: list[str] = []
    for attachment in attachments:
        if not isinstance(attachment, dict):
            continue
        kind = normalize_text(attachment.get("kind")).lower()
        artifact_id = normalize_text(attachment.get("id") or attachment.get("artifactId"))
        if kind == "image" and artifact_id:
            ids.append(artifact_id)
    return ids


def _normalize_size(value: Any) -> str:
    normalized = normalize_text(value)
    return normalized if normalized in VALID_SIZES else DEFAULT_SIZE


def _normalize_quality(value: Any) -> str:
    normalized = normalize_text(value).lower()
    return normalized if normalized in VALID_QUALITIES else DEFAULT_QUALITY
