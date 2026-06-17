from __future__ import annotations

import copy
import json
from typing import Any

from app_infra.formatting import content_text

__all__ = [
    "generated_artifact_success_payload",
    "latest_assistant_artifacts",
    "message_artifacts",
    "with_generated_artifacts_on_latest_assistant",
]

GENERATED_ARTIFACT_TOOL_NAMES = {"create_file_artifact", "create_image_artifact"}


def generated_artifact_success_payload(summary: str, artifact: Any) -> dict[str, Any]:
    payload = artifact.to_dict() if hasattr(artifact, "to_dict") else dict(artifact)
    return {
        "success": True,
        "changed": True,
        "summary": summary,
        "artifact": payload,
        "artifacts": [payload],
    }


def artifacts_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    artifacts: list[dict[str, Any]] = []
    raw_artifacts = payload.get("artifacts")
    if isinstance(raw_artifacts, list):
        artifacts.extend(dict(item) for item in raw_artifacts if isinstance(item, dict))
    artifact = payload.get("artifact")
    if isinstance(artifact, dict):
        artifact_id = artifact_identity(artifact)
        if not artifact_id or all(artifact_identity(item) != artifact_id for item in artifacts):
            artifacts.append(dict(artifact))
    return artifacts


def artifact_identity(artifact: dict[str, Any]) -> str:
    return str(artifact.get("id") or artifact.get("artifactId") or "")


def generated_artifact_tool_payload(message: dict[str, Any]) -> dict[str, Any]:
    if str(message.get("name") or "") not in GENERATED_ARTIFACT_TOOL_NAMES:
        return {}
    payload = tool_message_payload(message.get("content"))
    return payload if isinstance(payload, dict) else {}


def generated_artifacts_from_tool_message(message: dict[str, Any]) -> list[dict[str, Any]]:
    return artifacts_from_payload(generated_artifact_tool_payload(message))


def tool_message_payload(content: Any) -> dict[str, Any]:
    if isinstance(content, dict):
        return content
    if isinstance(content, list):
        for item in content:
            payload = tool_message_payload(item)
            if payload:
                return payload
        return {}
    if not isinstance(content, str):
        return {}
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def with_generated_artifacts_on_latest_assistant(
    messages: list[dict[str, Any]],
    *,
    start_index: int,
) -> list[dict[str, Any]]:
    if not messages:
        return messages
    artifacts: list[dict[str, Any]] = []
    summaries: list[str] = []
    seen: set[str] = set()
    for message in messages[max(0, start_index):]:
        if message.get("role") != "tool":
            continue
        payload = generated_artifact_tool_payload(message)
        if not payload:
            continue
        summary = content_text(payload.get("summary"))
        if summary.strip():
            summaries.append(summary.strip())
        for artifact in artifacts_from_payload(payload):
            artifact_id = artifact_identity(artifact)
            if artifact_id and artifact_id in seen:
                continue
            if artifact_id:
                seen.add(artifact_id)
            artifacts.append(artifact)
    if not artifacts:
        return messages
    updated = [dict(message) for message in messages]
    for index in range(len(updated) - 1, max(-1, start_index - 1), -1):
        if updated[index].get("role") != "assistant" or updated[index].get("tool_calls"):
            continue
        updated[index] = message_with_response_metadata_artifacts(updated[index], artifacts)
        updated[index] = message_with_generated_artifact_fallback_content(updated[index], summaries, artifacts)
        break
    return updated


def message_artifacts(message: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[Any] = []
    if isinstance(message.get("artifacts"), list):
        candidates.append(message.get("artifacts"))
    metadata = message.get("metadata") if isinstance(message.get("metadata"), dict) else {}
    response_metadata = metadata.get("response_metadata") if isinstance(metadata.get("response_metadata"), dict) else {}
    if isinstance(response_metadata.get("artifacts"), list):
        candidates.append(response_metadata.get("artifacts"))

    artifacts: list[dict[str, Any]] = []
    seen: set[str] = set()
    for candidate in candidates:
        if not isinstance(candidate, list):
            continue
        for artifact in candidate:
            if not isinstance(artifact, dict):
                continue
            artifact_id = artifact_identity(artifact)
            if artifact_id and artifact_id in seen:
                continue
            if artifact_id:
                seen.add(artifact_id)
            artifacts.append(dict(artifact))
    return artifacts


def latest_assistant_artifacts(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for message in reversed(messages):
        if message.get("role") != "assistant":
            continue
        artifacts = message_artifacts(message)
        if artifacts:
            return artifacts
    return []


def message_with_response_metadata_artifacts(message: dict[str, Any], artifacts: list[dict[str, Any]]) -> dict[str, Any]:
    updated = dict(message)
    metadata = dict(updated.get("metadata") if isinstance(updated.get("metadata"), dict) else {})
    response_metadata = dict(metadata.get("response_metadata") if isinstance(metadata.get("response_metadata"), dict) else {})
    existing = response_metadata.get("artifacts")
    merged: list[dict[str, Any]] = [dict(item) for item in existing if isinstance(item, dict)] if isinstance(existing, list) else []
    seen = {artifact_identity(item) for item in merged if isinstance(item, dict)}
    for artifact in artifacts:
        artifact_id = artifact_identity(artifact)
        if artifact_id and artifact_id in seen:
            continue
        if artifact_id:
            seen.add(artifact_id)
        merged.append(dict(artifact))
    response_metadata["artifacts"] = merged
    metadata["response_metadata"] = response_metadata
    updated["metadata"] = metadata
    return updated


def message_with_generated_artifact_fallback_content(
    message: dict[str, Any],
    summaries: list[str],
    artifacts: list[dict[str, Any]],
) -> dict[str, Any]:
    if content_text(message.get("content")).strip():
        return message
    updated = dict(message)
    summary = next((item for item in summaries if item.strip()), "")
    if not summary:
        names = [
            str(artifact.get("fileName") or artifact.get("file_name") or "").strip()
            for artifact in artifacts
            if isinstance(artifact, dict)
        ]
        names = [name for name in names if name]
        summary = f"Created {', '.join(names)}." if names else "Created the requested artifact."
    updated["content"] = summary
    return updated


def copy_artifacts(artifacts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [copy.deepcopy(artifact) for artifact in artifacts if isinstance(artifact, dict)]

