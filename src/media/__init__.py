from __future__ import annotations

from media.store import MediaStore, MediaStoreError
from media.types import ImageArtifact

AttachmentArtifact = ImageArtifact

__all__ = [
    "AttachmentArtifact",
    "ImageArtifact",
    "MediaStore",
    "MediaStoreError",
]
