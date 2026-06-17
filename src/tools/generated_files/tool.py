"""说明：实现 create_file_artifact 工具。

作用：把模型生成的文本、Markdown、JSON、CSV 或 HTML 保存成可下载 artifact。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from langchain_core.tools import StructuredTool

from app_infra.artifact_generation import GENERATED_TEXT_MIME_KINDS
from app_infra.formatting import normalize_text
from media import MediaStore, MediaStoreError
from tools.generated_artifacts.payloads import generated_artifact_success_payload


CREATE_FILE_ARTIFACT_TOOL_NAME = "create_file_artifact"
GENERATED_ARTIFACTS_TOOLSET = "generated_artifacts"


def create_tools(
    *,
    media_store: MediaStore | None = None,
    session_id: str = "",
    provider_name: str = "",
    model: str = "",
    file_generation: dict[str, Any] | None = None,
) -> list[StructuredTool]:
    if media_store is None:
        return []
    return [
        StructuredTool(
            name=CREATE_FILE_ARTIFACT_TOOL_NAME,
            description=(
                "Create a downloadable text file artifact for the user when they ask for a generated, saved, "
                "exported, or downloadable text file. Use this instead of code execution or local file writes."
            ),
            args_schema=create_file_artifact_parameters(),
            func=lambda **kwargs: create_file_artifact(
                dict(kwargs),
                media_store=media_store,
                session_id=session_id,
                provider_name=provider_name,
                model=model,
                file_generation=file_generation,
            ),
        )
    ]


def create_file_artifact_parameters() -> dict[str, Any]:
    return {
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
    }


def create_file_artifact(
    args: dict[str, Any],
    *,
    media_store: MediaStore,
    session_id: str = "",
    provider_name: str = "",
    model: str = "",
    file_generation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    file_name = normalize_text(args.get("file_name") or args.get("fileName"))
    mime_type = normalize_text(args.get("mime_type") or args.get("mimeType")).lower()
    file_name, mime_type = _apply_forced_generation_format(file_name, mime_type, dict(file_generation or {}))
    content = args.get("content")
    error = _validate_file_request(file_name=file_name, mime_type=mime_type, content=content)
    if error:
        return {"success": False, **error}
    try:
        artifact = media_store.create_generated_file(
            str(content),
            file_name=file_name,
            mime_type=mime_type,
            session_id=session_id,
            provider=provider_name,
            model=model,
            metadata={"createdBy": CREATE_FILE_ARTIFACT_TOOL_NAME, "requestedFileName": file_name},
        )
    except MediaStoreError as error:
        return {"success": False, "error": str(error), "code": "artifact_create_failed"}
    return generated_artifact_success_payload(f"Created {artifact.file_name}.", artifact)


def _validate_file_request(*, file_name: str, mime_type: str, content: Any) -> dict[str, str]:
    if not file_name:
        return {"error": "file_name is required.", "code": "file_name_required"}
    path = Path(file_name)
    if file_name != path.name or "/" in file_name or "\\" in file_name or ".." in path.parts:
        return {"error": "file_name must be a safe file name without path segments.", "code": "unsafe_file_name"}
    if file_name.startswith("."):
        return {"error": "file_name must not be hidden.", "code": "unsafe_file_name"}
    if mime_type not in GENERATED_TEXT_MIME_KINDS:
        return {"error": "mime_type is not allowed for generated files.", "code": "unsupported_mime_type"}
    if not isinstance(content, str) or not content:
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
