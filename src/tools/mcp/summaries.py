from __future__ import annotations

from fnmatch import fnmatchcase
from typing import Any

from tools.mcp.content import (
    file_name_from_resource_uri,
    is_safe_mcp_file_mime,
    is_safe_mcp_pdf_mime,
    mcp_file_summary,
    mcp_image_summary,
    mcp_pdf_summary,
    summarize_blob,
    summarize_media,
)
from tools.mcp.names import mcp_tool_name
from tools.mcp.security import sanitize_mcp_description, sanitize_mcp_schema_descriptions
from tools.mcp.utils import first_field, get_field, json_safe_value


def mcp_tool_read_only(tool: Any) -> bool:
    annotations = mcp_tool_annotations(tool)
    return annotations.get("readOnlyHint") is True


def mcp_tool_annotations(tool: Any) -> dict[str, Any]:
    raw_annotations = first_field(tool, "annotations")
    payload: dict[str, Any] = {}
    title = first_field(tool, "title") or annotation_value(raw_annotations, "title")
    if title is not None and str(title).strip():
        payload["title"] = str(title).strip()
    for output_key, names in (
        ("readOnlyHint", ("readOnlyHint", "read_only_hint")),
        ("destructiveHint", ("destructiveHint", "destructive_hint")),
        ("idempotentHint", ("idempotentHint", "idempotent_hint")),
        ("openWorldHint", ("openWorldHint", "open_world_hint")),
    ):
        value = annotation_value(raw_annotations, *names)
        if value is not None:
            payload[output_key] = bool(value)
    return payload


def annotation_value(annotations: Any, *names: str) -> Any:
    if annotations is None:
        return None
    for name in names:
        value = get_field(annotations, name)
        if value is not None:
            return value
    return None


def mcp_tool_risk(annotations: dict[str, Any], *, read_only: bool) -> str:
    if read_only:
        return "read"
    if annotations.get("destructiveHint") is True:
        return "destructive"
    return "write"


def mcp_tool_output_schema(tool: Any, *, warnings: list[dict[str, Any]] | None = None) -> dict[str, Any] | None:
    schema = first_field(tool, "outputSchema", "output_schema")
    if not isinstance(schema, dict) or not schema:
        return None
    return sanitize_mcp_schema_descriptions(
        json_safe_value(schema),
        warnings=warnings if warnings is not None else [],
        surface="tool_output_schema",
    )


def server_supports_capability(server: Any, capability: str) -> bool:
    capabilities = get_field(getattr(server, "initialize_result", None), "capabilities")
    if capabilities is None:
        return False
    value = get_field(capabilities, capability)
    return value is not None


def server_status_details(server: Any) -> dict[str, Any]:
    status_details = getattr(server, "status_details", None)
    if callable(status_details):
        try:
            return dict(status_details())
        except Exception:
            pass
    next_retry_at = float(getattr(server, "next_retry_at", 0.0) or 0.0)
    state = str(getattr(server, "state", "connected" if getattr(server, "session", None) else "disconnected") or "")
    return {
        "state": state,
        "failureCount": int(getattr(server, "failure_count", 0) or 0),
        "nextRetryAt": next_retry_at if next_retry_at > 0 else None,
        "circuitOpen": bool(getattr(server, "circuit_open", False)),
    }


def server_tool_filter_allows(server: Any, tool_name: str) -> bool:
    name = str(tool_name or "").strip()
    if not name:
        return False
    include_patterns = server_tool_filter_patterns(server, "includeTools")
    exclude_patterns = server_tool_filter_patterns(server, "excludeTools")
    if include_patterns and not matches_tool_filter(name, include_patterns):
        return False
    return not matches_tool_filter(name, exclude_patterns)


def server_tool_filter_patterns(server: Any, field: str) -> list[str]:
    value = (server.server or {}).get(field)
    if value is None and field == "includeTools":
        value = (server.server or {}).get("include_tools")
    if value is None and field == "excludeTools":
        value = (server.server or {}).get("exclude_tools")
    if not isinstance(value, list):
        return []
    return [str(pattern or "").strip() for pattern in value if str(pattern or "").strip()]


def matches_tool_filter(tool_name: str, patterns: list[str]) -> bool:
    return any(fnmatchcase(tool_name, pattern) for pattern in patterns)


def mcp_utility_metadata(server: Any, utility_name: str) -> dict[str, Any]:
    return {
        "mcp": True,
        "mcpUtility": True,
        "serverId": server.id,
        "serverName": server.name,
        "utilityName": utility_name,
    }


def tool_summary_from_definition(definition: Any) -> dict[str, Any]:
    metadata = definition.metadata or {}
    warnings = metadata.get("securityWarnings") if isinstance(metadata.get("securityWarnings"), list) else None
    return mcp_tool_summary_payload(
        name=str(metadata.get("originalToolName") or metadata.get("utilityName") or definition.name),
        generated_name=definition.name,
        description=definition.description,
        read_only=definition.read_only,
        server_id=str(metadata.get("serverId") or ""),
        server_name=str(metadata.get("serverName") or ""),
        annotations=metadata.get("mcpAnnotations"),
        has_output_schema=bool(metadata.get("mcpHasOutputSchema")),
        warnings=warnings,
    )


def mcp_tool_summary_payload(
    *,
    name: str,
    generated_name: str,
    description: str,
    read_only: bool,
    server_id: str,
    server_name: str,
    annotations: Any = None,
    has_output_schema: bool = False,
    warnings: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    payload = {
        "name": name,
        "generatedName": generated_name,
        "description": description,
        "readOnly": bool(read_only),
        "mutating": not bool(read_only),
        "serverId": server_id,
        "serverName": server_name,
    }
    attach_mcp_tool_metadata_summary(payload, annotations, has_output_schema)
    if warnings:
        payload["securityWarnings"] = warnings
    return payload


def attach_mcp_tool_metadata_summary(
    payload: dict[str, Any],
    annotations: Any,
    has_output_schema: bool = False,
) -> None:
    if isinstance(annotations, dict) and annotations:
        payload["annotations"] = dict(annotations)
        title = annotations.get("title")
        if title:
            payload["title"] = str(title)
        for key in ("readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint"):
            if key in annotations:
                payload[key] = bool(annotations.get(key))
    if has_output_schema:
        payload["hasOutputSchema"] = True


def server_tool_summaries(server: Any) -> list[dict[str, Any]]:
    tools = [
        tool_summary(server, tool, mcp_tool_name(server.id, getattr(tool, "name", "")))
        for tool in server.tools
        if server_tool_filter_allows(server, str(getattr(tool, "name", "") or ""))
    ]
    if server_supports_capability(server, "resources"):
        if server_tool_filter_allows(server, "list_resources"):
            tools.append(utility_tool_summary(server, "list_resources"))
        if server_tool_filter_allows(server, "read_resource"):
            tools.append(utility_tool_summary(server, "read_resource"))
    if server_supports_capability(server, "prompts"):
        if server_tool_filter_allows(server, "list_prompts"):
            tools.append(utility_tool_summary(server, "list_prompts"))
        if server_tool_filter_allows(server, "get_prompt"):
            tools.append(utility_tool_summary(server, "get_prompt"))
    return tools


def utility_tool_summary(server: Any, utility_name: str) -> dict[str, Any]:
    return {
        "name": utility_name,
        "generatedName": mcp_tool_name(server.id, utility_name),
        "description": f"MCP utility {utility_name} for {server.name}.",
        "readOnly": True,
        "mutating": False,
        "serverId": server.id,
        "serverName": server.name,
    }


def resource_summary(resource: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for output_key, field_names in (
        ("uri", ("uri",)),
        ("name", ("name",)),
        ("description", ("description",)),
        ("mimeType", ("mimeType", "mime_type")),
        ("size", ("size",)),
    ):
        value = first_field(resource, *field_names)
        if value is not None:
            payload[output_key] = str(value) if output_key != "size" else value
    return payload


def resource_content_summary(
    content: Any,
    *,
    server_id: str = "",
    media_store: Any = None,
    tool_name: str = "",
    resource_uri: str = "",
    artifacts: list[dict[str, Any]] | None = None,
    media_errors: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    uri = first_field(content, "uri")
    if uri is not None:
        payload["uri"] = str(uri)
    mime_type = first_field(content, "mimeType", "mime_type")
    if mime_type is not None:
        payload["mimeType"] = str(mime_type)
    text = first_field(content, "text")
    if text is not None:
        if is_safe_mcp_file_mime(str(mime_type or "")):
            previous_artifact_count = len(artifacts or [])
            payload["text"] = mcp_file_summary(
                text,
                str(mime_type or ""),
                encoded=False,
                server_id=server_id,
                media_store=media_store,
                tool_name=tool_name,
                resource_uri=str(uri or resource_uri or ""),
                file_name=file_name_from_resource_uri(str(uri or resource_uri or "")),
                artifacts=artifacts,
                media_errors=media_errors,
            )
            artifact = artifacts[-1] if artifacts and len(artifacts) > previous_artifact_count else None
            if artifact:
                payload["artifact"] = artifact
            return payload
        payload["text"] = str(text)
        return payload
    blob = first_field(content, "blob")
    if blob is not None:
        if str(mime_type or "").lower().startswith("image/"):
            previous_artifact_count = len(artifacts or [])
            summary = mcp_image_summary(
                blob,
                str(mime_type or ""),
                server_id=server_id,
                media_store=media_store,
                tool_name=tool_name,
                resource_uri=str(uri or resource_uri or ""),
                file_name=file_name_from_resource_uri(str(uri or resource_uri or "")),
                artifacts=artifacts,
                media_errors=media_errors,
            )
            payload["blob"] = summary
            artifact = artifacts[-1] if artifacts and len(artifacts) > previous_artifact_count else None
            if artifact:
                payload["artifact"] = artifact
            return payload
        if is_safe_mcp_pdf_mime(str(mime_type or "")):
            previous_artifact_count = len(artifacts or [])
            payload["blob"] = mcp_pdf_summary(
                blob,
                str(mime_type or ""),
                server_id=server_id,
                media_store=media_store,
                tool_name=tool_name,
                resource_uri=str(uri or resource_uri or ""),
                file_name=file_name_from_resource_uri(str(uri or resource_uri or "")),
                artifacts=artifacts,
                media_errors=media_errors,
            )
            artifact = artifacts[-1] if artifacts and len(artifacts) > previous_artifact_count else None
            if artifact:
                payload["artifact"] = artifact
            return payload
        if is_safe_mcp_file_mime(str(mime_type or "")):
            previous_artifact_count = len(artifacts or [])
            payload["blob"] = mcp_file_summary(
                blob,
                str(mime_type or ""),
                encoded=True,
                server_id=server_id,
                media_store=media_store,
                tool_name=tool_name,
                resource_uri=str(uri or resource_uri or ""),
                file_name=file_name_from_resource_uri(str(uri or resource_uri or "")),
                artifacts=artifacts,
                media_errors=media_errors,
            )
            artifact = artifacts[-1] if artifacts and len(artifacts) > previous_artifact_count else None
            if artifact:
                payload["artifact"] = artifact
            return payload
        payload["blob"] = summarize_blob(blob)
    return payload


def prompt_summary(prompt: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    name = first_field(prompt, "name")
    if name is not None:
        payload["name"] = str(name)
    description = first_field(prompt, "description")
    if description is not None:
        payload["description"] = str(description)
    arguments = first_field(prompt, "arguments")
    if arguments:
        payload["arguments"] = [prompt_argument_summary(argument) for argument in arguments]
    return payload


def prompt_argument_summary(argument: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    name = first_field(argument, "name")
    if name is not None:
        payload["name"] = str(name)
    description = first_field(argument, "description")
    if description is not None:
        payload["description"] = str(description)
    required = first_field(argument, "required")
    if required is not None:
        payload["required"] = bool(required)
    return payload


def prompt_message_summary(
    message: Any,
    *,
    server_id: str = "",
    media_store: Any = None,
    tool_name: str = "",
    artifacts: list[dict[str, Any]] | None = None,
    media_errors: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    role = first_field(message, "role")
    if role is not None:
        payload["role"] = str(role)
    content = first_field(message, "content")
    payload["content"] = prompt_content_summary(
        content,
        server_id=server_id,
        media_store=media_store,
        tool_name=tool_name,
        artifacts=artifacts,
        media_errors=media_errors,
    )
    return payload


def prompt_content_summary(
    content: Any,
    *,
    server_id: str = "",
    media_store: Any = None,
    tool_name: str = "",
    artifacts: list[dict[str, Any]] | None = None,
    media_errors: list[dict[str, Any]] | None = None,
) -> Any:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return [
            prompt_content_summary(
                item,
                server_id=server_id,
                media_store=media_store,
                tool_name=tool_name,
                artifacts=artifacts,
                media_errors=media_errors,
            )
            for item in content
        ]
    text = first_field(content, "text")
    if text is not None:
        return str(text)
    resource = first_field(content, "resource")
    if resource is not None:
        return {
            "resource": resource_content_summary(
                resource,
                server_id=server_id,
                media_store=media_store,
                tool_name=tool_name,
                artifacts=artifacts,
                media_errors=media_errors,
            )
        }
    data = first_field(content, "data")
    mime_type = first_field(content, "mimeType", "mime_type")
    if data is not None and mime_type is not None:
        if str(mime_type).lower().startswith("image/"):
            return mcp_image_summary(
                data,
                str(mime_type),
                server_id=server_id,
                media_store=media_store,
                tool_name=tool_name,
                artifacts=artifacts,
                media_errors=media_errors,
            )
        if is_safe_mcp_pdf_mime(str(mime_type)):
            return mcp_pdf_summary(
                data,
                str(mime_type),
                server_id=server_id,
                media_store=media_store,
                tool_name=tool_name,
                artifacts=artifacts,
                media_errors=media_errors,
            )
        if is_safe_mcp_file_mime(str(mime_type)):
            return mcp_file_summary(
                data,
                str(mime_type),
                encoded=True,
                server_id=server_id,
                media_store=media_store,
                tool_name=tool_name,
                artifacts=artifacts,
                media_errors=media_errors,
            )
        return summarize_media(data, str(mime_type))
    if isinstance(content, dict):
        return {str(key): json_safe_value(value) for key, value in content.items()}
    return str(content)


def tool_summary(server: Any, tool: Any, generated_name: str) -> dict[str, Any]:
    read_only = mcp_tool_read_only(tool)
    annotations = mcp_tool_annotations(tool)
    warnings: list[dict[str, Any]] = []
    raw_description = str(getattr(tool, "description", "") or "")
    description = sanitize_mcp_description(
        raw_description,
        surface="tool_description",
        warnings=warnings,
        fallback=f"MCP tool {getattr(tool, 'name', '') or generated_name} from {server.name}.",
    )
    return mcp_tool_summary_payload(
        name=str(getattr(tool, "name", "") or ""),
        generated_name=generated_name,
        description=description,
        read_only=read_only,
        server_id=server.id,
        server_name=server.name,
        annotations=annotations,
        has_output_schema=mcp_tool_output_schema(tool, warnings=warnings) is not None,
        warnings=warnings,
    )


__all__ = [
    "mcp_tool_annotations",
    "mcp_tool_output_schema",
    "mcp_tool_read_only",
    "mcp_tool_risk",
    "mcp_utility_metadata",
    "prompt_message_summary",
    "prompt_summary",
    "resource_content_summary",
    "resource_summary",
    "server_status_details",
    "server_supports_capability",
    "server_tool_filter_allows",
    "server_tool_summaries",
    "tool_summary_from_definition",
]
