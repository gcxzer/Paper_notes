from __future__ import annotations

# Media artifact lookup, path resolution, and registration helpers for note images.

from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from app_infra.formatting import normalize_text
from app_infra.files import PROJECT_ROOT


def _artifact_to_payload(artifact: Any) -> dict[str, Any]:
    if artifact is None:
        return {}
    to_dict = getattr(artifact, "to_dict", None)
    if callable(to_dict):
        payload = to_dict()
        return payload if isinstance(payload, dict) else {}
    return artifact if isinstance(artifact, dict) else {}

def _artifact_payload(media_store: Any | None, artifact_id: str) -> dict[str, Any]:
    if media_store is None:
        return {"id": artifact_id}
    public_artifact = getattr(media_store, "public_artifact", None)
    if callable(public_artifact):
        try:
            payload = public_artifact(artifact_id)
        except Exception:
            return {"id": artifact_id}
        return payload if isinstance(payload, dict) else {"id": artifact_id}
    return {"id": artifact_id}


def _resolve_image_artifact_payload(media_store: Any | None, artifact_ref: str) -> dict[str, Any]:
    ref = normalize_text(artifact_ref)
    if not ref:
        return {}

    direct = _artifact_payload(media_store, ref)
    if normalize_text(direct.get("url")) and normalize_text(direct.get("kind") or "image") == "image":
        return direct

    candidate_paths = _candidate_media_paths(ref, media_store)
    find_by_path = getattr(media_store, "find_by_path", None)
    if callable(find_by_path):
        for candidate in candidate_paths:
            try:
                artifact = find_by_path(candidate)
            except Exception:
                artifact = None
            payload = _artifact_to_payload(artifact)
            if normalize_text(payload.get("url")) and normalize_text(payload.get("kind") or "image") == "image":
                return payload

    public_artifact = getattr(media_store, "public_artifact", None)
    if callable(public_artifact):
        for artifact_id in _candidate_artifact_ids(ref):
            try:
                payload = public_artifact(artifact_id)
            except Exception:
                payload = {}
            if (
                isinstance(payload, dict)
                and normalize_text(payload.get("url"))
                and normalize_text(payload.get("kind") or "image") == "image"
            ):
                return payload
    return {}


def _candidate_artifact_ids(ref: str) -> list[str]:
    candidates = [ref]
    parsed = urlparse(ref)
    raw_path = unquote(parsed.path if parsed.scheme == "file" else ref)
    path = Path(raw_path)
    if path.name:
        candidates.append(path.stem)
        candidates.append(path.name)
    seen: set[str] = set()
    result: list[str] = []
    for candidate in candidates:
        normalized = normalize_text(candidate)
        if normalized and normalized not in seen:
            result.append(normalized)
            seen.add(normalized)
    return result


def _candidate_media_paths(ref: str, media_store: Any | None) -> list[Path]:
    parsed = urlparse(ref)
    if parsed.scheme and parsed.scheme != "file":
        return []
    raw_path = unquote(parsed.path if parsed.scheme == "file" else ref)
    path = Path(raw_path).expanduser()
    candidates: list[Path] = []
    if path.is_absolute():
        candidates.append(path.resolve())
    else:
        candidates.append((PROJECT_ROOT / path).resolve())
        root = getattr(media_store, "root", None)
        if root is not None:
            media_root = Path(root).resolve()
            candidates.append((media_root / path).resolve())
            if path.parts and path.parts[0] not in {"generated", "uploads"}:
                candidates.append((media_root / "generated" / path).resolve())
                candidates.append((media_root / "uploads" / path).resolve())
    seen: set[str] = set()
    result: list[Path] = []
    for candidate in candidates:
        key = str(candidate)
        if key not in seen:
            result.append(candidate)
            seen.add(key)
    return result


def _attach_artifact(
    payload: dict[str, Any],
    *,
    media_store: Any | None,
    path_key: str,
    source: str,
    metadata: dict[str, Any],
) -> None:
    if media_store is None or not isinstance(payload, dict):
        return
    image_path = payload.get(path_key)
    if not image_path:
        return
    register_existing = getattr(media_store, "register_existing", None)
    if not callable(register_existing):
        return
    try:
        artifact = register_existing(
            image_path,
            source=source,
            metadata={key: value for key, value in metadata.items() if value is not None and value != ""},
        )
    except Exception:
        return
    artifact_payload = _artifact_to_payload(artifact)
    payload["artifact"] = artifact_payload
    payload["artifact_id"] = artifact_payload.get("id", "")
    payload["preview_url"] = artifact_payload.get("url", "")
    payload["download_url"] = artifact_payload.get("downloadUrl", "")
