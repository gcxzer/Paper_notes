from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class ImageArtifact:
    id: str
    source: str
    mime_type: str
    file_name: str
    path: str
    url: str
    download_url: str
    width: int = 0
    height: int = 0
    size: int = 0
    provider: str = ""
    model: str = ""
    created_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    kind: str = "image"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "source": self.source,
            "mimeType": self.mime_type,
            "fileName": self.file_name,
            "path": self.path,
            "url": self.url,
            "downloadUrl": self.download_url,
            "width": self.width,
            "height": self.height,
            "size": self.size,
            "provider": self.provider,
            "model": self.model,
            "createdAt": self.created_at,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ImageArtifact":
        return cls(
            id=str(payload.get("id") or ""),
            kind=str(payload.get("kind") or "image"),
            source=str(payload.get("source") or ""),
            mime_type=str(payload.get("mimeType") or payload.get("mime_type") or ""),
            file_name=str(payload.get("fileName") or payload.get("file_name") or ""),
            path=str(payload.get("path") or ""),
            url=str(payload.get("url") or ""),
            download_url=str(payload.get("downloadUrl") or payload.get("download_url") or ""),
            width=int(payload.get("width") or 0),
            height=int(payload.get("height") or 0),
            size=int(payload.get("size") or 0),
            provider=str(payload.get("provider") or ""),
            model=str(payload.get("model") or ""),
            created_at=str(payload.get("createdAt") or payload.get("created_at") or ""),
            metadata=dict(payload.get("metadata") or {}),
        )

    @property
    def filesystem_path(self) -> Path:
        return Path(self.path)
