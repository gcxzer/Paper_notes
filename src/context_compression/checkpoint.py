from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path

from context_compression.types import ContextCompressionCheckpoint
from app_infra.storage import atomic_write_json


class ContextCompressionCheckpointStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self._lock = threading.Lock()

    def load(self, session_id: str) -> ContextCompressionCheckpoint | None:
        path = self.path_for(session_id)
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        checkpoint = ContextCompressionCheckpoint.from_dict(data)
        if checkpoint.session_id and checkpoint.session_id != session_id:
            return None
        checkpoint.session_id = session_id
        return checkpoint

    def save(self, checkpoint: ContextCompressionCheckpoint) -> ContextCompressionCheckpoint:
        with self._lock:
            if not checkpoint.updated_at:
                checkpoint.updated_at = datetime.now().astimezone().isoformat(timespec="seconds")
            atomic_write_json(self.path_for(checkpoint.session_id), checkpoint.to_dict())
        return checkpoint

    def delete(self, session_id: str) -> None:
        path = self.path_for(session_id)
        with self._lock:
            if path.exists():
                path.unlink()

    def path_for(self, session_id: str) -> Path:
        safe_session_id = "".join(ch for ch in str(session_id) if ch.isalnum() or ch in {"_", "-"})
        return self.root / f"{safe_session_id}.json"
