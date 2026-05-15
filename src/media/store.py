from __future__ import annotations

import json
import re
import shutil
import uuid
import base64
import binascii
from datetime import datetime
from pathlib import Path
from typing import Any

from app_config.secrets import LOCAL_STATE_DIR
from media.attachment_extractors import (
    attachment_extension_for_mime,
    attachment_kind,
    attachment_mime_for_name,
    ensure_supported_attachment,
    extract_attachment_text,
)
from media.image import (
    data_url_for_bytes,
    extension_for_mime,
    image_dimensions_for_path,
    normalize_upload_image,
    parse_base64_image,
    sniff_image_mime,
)
from media.types import ImageArtifact
from app_infra.formatting import normalize_text
from app_infra.paths import PROJECT_ROOT, is_relative_to
from app_infra.storage import atomic_write_json


class MediaStoreError(ValueError):
    pass


DEFAULT_MAX_ATTACHMENT_BYTES = 30 * 1024 * 1024
_DATA_URL_RE = re.compile(r"^data:(?P<mime>[-\w.]+/[-\w.+]+);base64,(?P<data>.*)$", re.IGNORECASE | re.DOTALL)
GENERATED_TEXT_MIME_KINDS = {
    "text/markdown": ("text", ".md"),
    "text/plain": ("text", ".txt"),
    "application/json": ("json", ".json"),
    "text/csv": ("csv", ".csv"),
    "text/html": ("html", ".html"),
}


class MediaStore:
    def __init__(self, root: str | Path | None = None, *, project_root: str | Path | None = None) -> None:
        self.root = Path(root) if root is not None else LOCAL_STATE_DIR / "media"
        self.project_root = Path(project_root) if project_root is not None else PROJECT_ROOT
        self.manifest_path = self.root / "artifacts.json"

    def create_upload(
        self,
        data: str,
        *,
        file_name: str = "",
        scope: str = "",
        mime_type: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> ImageArtifact:
        raw, declared_mime = _parse_base64_payload(data)
        sniffed_image_mime = sniff_image_mime(raw)
        requested_mime = normalize_text(mime_type or declared_mime or sniffed_image_mime or attachment_mime_for_name(file_name)).lower()
        original_requested_mime = requested_mime
        if sniffed_image_mime:
            data_bytes, requested_mime, width, height = normalize_upload_image(raw, mime_type=sniffed_image_mime)
            artifact_id = self._new_id("img")
            extension = extension_for_mime(requested_mime)
            kind = "image"
            extraction_metadata: dict[str, Any] = {}
        else:
            requested_mime = ensure_supported_attachment(file_name, requested_mime)
            data_bytes = raw
            width = 0
            height = 0
            kind = attachment_kind(requested_mime)
            artifact_id = self._new_id("att")
            extension = attachment_extension_for_mime(requested_mime)
            extracted_text = extract_attachment_text(data_bytes, mime_type=requested_mime, file_name=file_name)
            extraction_metadata = {
                "extractionStatus": "complete",
                "extractedTextChars": len(extracted_text),
            }
            if requested_mime == "text/plain" and original_requested_mime not in {"text/plain", "text/markdown"}:
                extraction_metadata["detectedText"] = True
        safe_scope = _safe_segment(scope or "unsorted")
        safe_name = _safe_file_name(file_name, fallback=f"{artifact_id}{extension}", extension=extension)
        target = self.root / "uploads" / safe_scope / safe_name
        if target.exists():
            target = target.with_name(f"{target.stem}-{artifact_id}{target.suffix}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data_bytes)
        artifact = self._register(
            artifact_id=artifact_id,
            source="upload",
            path=target,
            mime_type=requested_mime,
            file_name=safe_name,
            kind=kind,
            size=len(data_bytes),
            width=width,
            height=height,
            metadata={"storageFileName": target.name, **extraction_metadata, **dict(metadata or {})},
        )
        if kind != "image":
            self._write_extracted_text(artifact.id, extracted_text)
        return artifact

    def create_generated_image(
        self,
        image_data: str,
        *,
        session_id: str = "",
        provider: str = "",
        model: str = "",
        metadata: dict[str, Any] | None = None,
        file_format: str = "png",
    ) -> ImageArtifact:
        raw, mime_type = parse_base64_image(image_data)
        if file_format:
            requested_mime = _mime_for_format(file_format)
            if requested_mime and requested_mime != mime_type:
                mime_type = sniff_image_mime(raw) or mime_type
        artifact_id = self._new_id("gen")
        extension = extension_for_mime(mime_type)
        safe_session = _safe_segment(session_id or "unsorted")
        target = self.root / "generated" / safe_session / f"{artifact_id}{extension}"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        width, height = image_dimensions_for_path(target)
        return self._register(
            artifact_id=artifact_id,
            source="generated",
            path=target,
            mime_type=mime_type,
            file_name=target.name,
            kind="image",
            size=len(raw),
            width=width,
            height=height,
            provider=provider,
            model=model,
            metadata=metadata,
        )

    def create_generated_file(
        self,
        content: str,
        *,
        file_name: str,
        mime_type: str,
        session_id: str = "",
        provider: str = "",
        model: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> ImageArtifact:
        normalized_mime = normalize_text(mime_type).lower()
        kind, extension = GENERATED_TEXT_MIME_KINDS.get(normalized_mime, ("", ""))
        if not kind:
            raise MediaStoreError(f"Unsupported generated file MIME type: {mime_type}")
        text = str(content)
        if not text:
            raise MediaStoreError("Generated file content is required.")
        data = text.encode("utf-8")
        artifact_id = self._new_id("file")
        safe_session = _safe_segment(session_id or "unsorted")
        safe_name = _safe_file_name(file_name, fallback=f"{artifact_id}{extension}", extension=extension)
        target = self.root / "generated" / safe_session / safe_name
        if target.exists():
            target = target.with_name(f"{target.stem}-{artifact_id}{target.suffix}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        artifact = self._register(
            artifact_id=artifact_id,
            source="generated",
            path=target,
            mime_type=normalized_mime,
            file_name=target.name,
            kind=kind,
            size=len(data),
            provider=provider,
            model=model,
            metadata={
                "extractionStatus": "complete",
                "extractedTextChars": len(text),
                **dict(metadata or {}),
            },
        )
        self._write_extracted_text(artifact.id, text)
        return artifact

    def register_existing(
        self,
        path: str | Path,
        *,
        source: str,
        file_name: str = "",
        provider: str = "",
        model: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> ImageArtifact:
        source_path = Path(path).resolve()
        media_root = self.root.resolve()
        if source not in {"pdf_page", "pdf_image"} and not is_relative_to(source_path, media_root):
            raise MediaStoreError(
                f"Local images must be placed under {media_root} before they can be inserted into notes."
            )
        if not source_path.exists() or not source_path.is_file():
            raise MediaStoreError(f"Image file does not exist: {source_path}")
        data = source_path.read_bytes()
        mime_type = sniff_image_mime(data)
        if not mime_type:
            raise MediaStoreError("Registered media file is not a supported image.")
        existing = self.find_by_path(source_path)
        if existing is not None:
            return existing
        artifact_id = self._new_id("img")
        width, height = image_dimensions_for_path(source_path)
        return self._register(
            artifact_id=artifact_id,
            source=source,
            path=source_path,
            mime_type=mime_type,
            file_name=file_name or source_path.name,
            kind="image",
            size=len(data),
            width=width,
            height=height,
            provider=provider,
            model=model,
            metadata=metadata,
        )

    def copy_existing(
        self,
        path: str | Path,
        *,
        source: str,
        scope: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> ImageArtifact:
        source_path = Path(path).resolve()
        data = source_path.read_bytes()
        mime_type = sniff_image_mime(data)
        if not mime_type:
            raise MediaStoreError("Copied media file is not a supported image.")
        artifact_id = self._new_id("img")
        extension = extension_for_mime(mime_type)
        target = self.root / source / _safe_segment(scope or "unsorted") / f"{artifact_id}{extension}"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_path, target)
        width, height = image_dimensions_for_path(target)
        return self._register(
            artifact_id=artifact_id,
            source=source,
            path=target,
            mime_type=mime_type,
            file_name=target.name,
            kind="image",
            size=len(data),
            width=width,
            height=height,
            metadata=metadata,
        )

    def get_artifact(self, artifact_id: str) -> ImageArtifact | None:
        return self._load_manifest().get(str(artifact_id or ""))

    def require_artifact(self, artifact_id: str) -> ImageArtifact:
        artifact = self.get_artifact(artifact_id)
        if artifact is None:
            raise MediaStoreError(f"Media artifact not found: {artifact_id}")
        return artifact

    def find_by_path(self, path: str | Path) -> ImageArtifact | None:
        resolved = str(Path(path).resolve())
        for artifact in self._load_manifest().values():
            try:
                if str(Path(artifact.path).resolve()) == resolved:
                    return artifact
            except OSError:
                continue
        return None

    def path_for(self, artifact_id: str) -> Path:
        artifact = self.require_artifact(artifact_id)
        path = Path(artifact.path).resolve()
        if not path.exists() or not path.is_file():
            raise MediaStoreError(f"Media file is missing: {artifact_id}")
        if not self._is_allowed_media_path(path):
            raise MediaStoreError("Media artifact path is outside allowed storage.")
        return path

    def read_bytes(self, artifact_id: str) -> bytes:
        return self.path_for(artifact_id).read_bytes()

    def data_url_for_artifact(self, artifact_id: str) -> str:
        artifact = self.require_artifact(artifact_id)
        return data_url_for_bytes(self.read_bytes(artifact.id), artifact.mime_type)

    def extracted_text_for_artifact(self, artifact_id: str) -> str:
        artifact = self.require_artifact(artifact_id)
        if artifact.kind == "image":
            return ""
        path = self._extracted_text_path(artifact.id)
        if path.exists():
            try:
                return path.read_text(encoding="utf-8")
            except OSError:
                return ""
        text = extract_attachment_text(self.read_bytes(artifact.id), mime_type=artifact.mime_type, file_name=artifact.file_name)
        self._write_extracted_text(artifact.id, text)
        return text

    def public_artifact(self, artifact_id: str) -> dict[str, Any]:
        return self.require_artifact(artifact_id).to_dict()

    def _register(
        self,
        *,
        artifact_id: str,
        source: str,
        path: Path,
        mime_type: str,
        file_name: str,
        kind: str = "image",
        size: int = 0,
        width: int = 0,
        height: int = 0,
        provider: str = "",
        model: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> ImageArtifact:
        path = path.resolve()
        artifact = ImageArtifact(
            id=artifact_id,
            source=source,
            mime_type=mime_type,
            file_name=file_name,
            path=str(path),
            url=f"/api/media/{artifact_id}",
            download_url=f"/api/media/{artifact_id}/download",
            kind=kind,
            size=size or _path_size(path),
            width=width,
            height=height,
            provider=provider,
            model=model,
            created_at=datetime.now().astimezone().isoformat(timespec="seconds"),
            metadata=dict(metadata or {}),
        )
        manifest = self._load_manifest()
        manifest[artifact.id] = artifact
        self._save_manifest(manifest)
        return artifact

    def _load_manifest(self) -> dict[str, ImageArtifact]:
        if not self.manifest_path.exists():
            return {}
        try:
            payload = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        artifacts = payload.get("artifacts") if isinstance(payload, dict) else None
        if not isinstance(artifacts, dict):
            return {}
        return {
            artifact_id: ImageArtifact.from_dict(artifact)
            for artifact_id, artifact in artifacts.items()
            if isinstance(artifact, dict)
        }

    def _save_manifest(self, manifest: dict[str, ImageArtifact]) -> None:
        atomic_write_json(
            self.manifest_path,
            {"artifacts": {artifact_id: artifact.to_dict() for artifact_id, artifact in manifest.items()}},
        )

    def _new_id(self, prefix: str) -> str:
        return f"{prefix}_{uuid.uuid4().hex[:20]}"

    def _is_allowed_media_path(self, path: Path) -> bool:
        allowed_roots = [
            self.root.resolve(),
            (self.project_root / "resources" / "Paper-pages").resolve(),
            (self.project_root / "resources" / "Paper-images").resolve(),
        ]
        return any(is_relative_to(path, root) for root in allowed_roots)

    def _extracted_text_path(self, artifact_id: str) -> Path:
        return self.root / "extracted" / f"{_safe_segment(artifact_id)}.txt"

    def _write_extracted_text(self, artifact_id: str, text: str) -> None:
        path = self._extracted_text_path(artifact_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def _safe_segment(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", normalize_text(value) or "default").strip(".-")
    return cleaned or "default"


def _safe_file_name(value: str, *, fallback: str, extension: str) -> str:
    name = Path(normalize_text(value)).name if value else fallback
    if not name:
        name = fallback
    name = re.sub(r"[^A-Za-z0-9_. -]+", "-", name).strip(". ")
    if not Path(name).suffix:
        name = f"{name}{extension}"
    return name or fallback


def _mime_for_format(value: str) -> str:
    normalized = normalize_text(value).lower().lstrip(".")
    return {
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "webp": "image/webp",
        "gif": "image/gif",
    }.get(normalized, "")


def _parse_base64_payload(value: str, *, max_bytes: int = DEFAULT_MAX_ATTACHMENT_BYTES) -> tuple[bytes, str]:
    text = str(value or "").strip()
    if not text:
        raise MediaStoreError("Attachment data is required.")
    declared_mime = ""
    match = _DATA_URL_RE.match(text)
    if match:
        declared_mime = match.group("mime").lower()
        text = match.group("data")
    try:
        data = base64.b64decode(text, validate=True)
    except (binascii.Error, ValueError) as error:
        raise MediaStoreError("Attachment data must be valid base64.") from error
    if len(data) > max_bytes:
        raise MediaStoreError("Attachment payload is too large.")
    return data, declared_mime


def _path_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0
