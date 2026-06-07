from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from tools.paper_notes.impl.formatting import normalize_text
from tools.paper_notes.impl.paths import ANNOTATIONS_DIR
from tools.paper_notes.impl.storage import atomic_write_json


def safe_annotation_id(note_id: str) -> str:
    safe_id = re.sub(r"[^a-z0-9\u4e00-\u9fff._-]+", "-", normalize_text(note_id), flags=re.IGNORECASE)
    return safe_id.strip("-._")


def annotation_path_for(note_id: str, base_dir: Path = ANNOTATIONS_DIR) -> Path | None:
    safe_id = safe_annotation_id(note_id)
    if not safe_id:
        return None
    return base_dir / f"{safe_id}.json"


def read_annotations(note_id: str, base_dir: Path = ANNOTATIONS_DIR) -> dict[str, Any] | None:
    annotations_path = annotation_path_for(note_id, base_dir)
    if annotations_path is None:
        return None
    try:
        return _without_annotation_text(json.loads(annotations_path.read_text(encoding="utf-8")))
    except FileNotFoundError:
        return {"annotations": []}
    except json.JSONDecodeError:
        return {"annotations": []}


def write_annotations(note_id: str, annotations: Any, base_dir: Path = ANNOTATIONS_DIR) -> dict[str, Any] | None:
    annotations_path = annotation_path_for(note_id, base_dir)
    if annotations_path is None:
        return None
    payload = _without_annotation_text({"annotations": annotations if isinstance(annotations, list) else []})
    base_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_json(annotations_path, payload)
    return payload


def _without_annotation_text(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {"annotations": []}
    annotations = payload.get("annotations")
    if not isinstance(annotations, list):
        return {"annotations": []}
    cleaned = []
    for annotation in annotations:
        if not isinstance(annotation, dict):
            continue
        next_annotation = dict(annotation)
        next_annotation.pop("text", None)
        cleaned.append(next_annotation)
    return {"annotations": cleaned}
