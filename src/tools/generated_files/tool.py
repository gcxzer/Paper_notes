from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from media import MediaStore, MediaStoreError
from media.store import GENERATED_TEXT_MIME_KINDS
from tools.generated_files.manifest import TOOL_NAME, TOOLSET
from tools.registry import ToolRegistry
from tools.types import ToolDefinition
from app_infra.formatting import normalize_text


def register_generated_file_tool(
    registry: ToolRegistry,
    *,
    media_store: MediaStore,
    session_id_provider: Callable[[], str] | None = None,
    provider_name_provider: Callable[[], str] | None = None,
    model_provider: Callable[[], str] | None = None,
    file_generation_provider: Callable[[], dict[str, Any]] | None = None,
) -> None:
    if registry.get(TOOL_NAME) is not None:
        return

    def handler(args: dict[str, Any]) -> dict[str, Any]:
        file_name = normalize_text(args.get("file_name") or args.get("fileName"))
        mime_type = normalize_text(args.get("mime_type") or args.get("mimeType")).lower()
        forced = file_generation_provider() if file_generation_provider is not None else {}
        file_name, mime_type = _apply_forced_generation_format(file_name, mime_type, forced)
        content = args.get("content")
        error = _validate_file_request(file_name=file_name, mime_type=mime_type, content=content)
        if error:
            return {"success": False, **error}
        try:
            artifact = media_store.create_generated_file(
                str(content),
                file_name=file_name,
                mime_type=mime_type,
                session_id=session_id_provider() if session_id_provider is not None else "",
                provider=provider_name_provider() if provider_name_provider is not None else "",
                model=model_provider() if model_provider is not None else "",
                metadata={"createdBy": TOOL_NAME},
            )
        except MediaStoreError as exc:
            return {"success": False, "error": str(exc), "code": "artifact_create_failed"}
        payload = artifact.to_dict()
        return {
            "success": True,
            "changed": True,
            "summary": f"Created {artifact.file_name}.",
            "artifact": payload,
            "artifacts": [payload],
        }

    registry.register(ToolDefinition(
        name=TOOL_NAME,
        description=(
            "Create a downloadable text file artifact for the user. Use this only when the user "
            "explicitly asks for a generated file in this turn."
        ),
        parameters={
            "type": "object",
            "properties": {
                "file_name": {
                    "type": "string",
                    "description": "Safe file name including an extension, for example summary.md or data.json.",
                },
                "mime_type": {
                    "type": "string",
                    "enum": sorted(GENERATED_TEXT_MIME_KINDS),
                    "description": "MIME type matching the requested file format.",
                },
                "content": {
                    "type": "string",
                    "description": "Complete UTF-8 text content to save into the generated file.",
                },
            },
            "required": ["file_name", "mime_type", "content"],
            "additionalProperties": False,
        },
        handler=handler,
        toolset=TOOLSET,
        read_only=False,
        mutating=False,
        risk="write",
        kind="external",
        result_max_chars=4000,
        metadata={"ui_hidden": True},
    ))


def _validate_file_request(*, file_name: str, mime_type: str, content: Any) -> dict[str, str]:
    if not file_name:
        return {"error": "file_name is required.", "code": "file_name_required"}
    if file_name != Path(file_name).name or "/" in file_name or "\\" in file_name or ".." in Path(file_name).parts:
        return {"error": "file_name must be a safe file name without path segments.", "code": "unsafe_file_name"}
    if file_name.startswith("."):
        return {"error": "file_name must not be hidden.", "code": "unsafe_file_name"}
    if mime_type not in GENERATED_TEXT_MIME_KINDS:
        return {"error": "mime_type is not allowed for generated files.", "code": "unsupported_mime_type"}
    if not isinstance(content, str) or content == "":
        return {"error": "content must be a non-empty string.", "code": "empty_content"}
    return {}


def _apply_forced_generation_format(file_name: str, mime_type: str, config: dict[str, Any]) -> tuple[str, str]:
    if not isinstance(config, dict) or not config.get("enabled"):
        return file_name, mime_type
    forced_mime = normalize_text(config.get("mime_type") or config.get("mimeType")).lower()
    if forced_mime not in GENERATED_TEXT_MIME_KINDS:
        return file_name, mime_type
    extension = GENERATED_TEXT_MIME_KINDS[forced_mime][1]
    safe_name = file_name or f"generated{extension}"
    stem = Path(safe_name).stem or "generated"
    return f"{stem}{extension}", forced_mime


__all__ = ["TOOL_NAME", "register_generated_file_tool"]
