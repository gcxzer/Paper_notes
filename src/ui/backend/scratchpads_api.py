from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app_config.secrets import LOCAL_STATE_DIR
from app_infra.formatting import normalize_text
from app_infra.files import atomic_write_json


DEFAULT_SCRATCHPADS_PATH = LOCAL_STATE_DIR / "scratchpads.json"


def read_scratchpads(*, path: str | Path | None = None) -> dict[str, Any]:
    scratchpads_path = Path(path) if path is not None else DEFAULT_SCRATCHPADS_PATH
    try:
        raw = json.loads(scratchpads_path.read_text(encoding="utf-8"))
    except Exception:
        raw = {}
    return normalize_scratchpads(raw)


def write_scratchpads(payload: Any, *, path: str | Path | None = None) -> dict[str, Any]:
    scratchpads_path = Path(path) if path is not None else DEFAULT_SCRATCHPADS_PATH
    normalized = normalize_scratchpads(payload)
    atomic_write_json(scratchpads_path, normalized)
    return normalized


def normalize_scratchpads(payload: Any) -> dict[str, Any]:
    raw = payload if isinstance(payload, dict) else {}
    raw_pads = raw.get("pads") if isinstance(raw.get("pads"), list) else []
    pads: list[dict[str, Any]] = []
    seen: set[str] = set()

    for index, raw_pad in enumerate(raw_pads):
        if not isinstance(raw_pad, dict):
            continue
        pad_id = normalize_text(raw_pad.get("id")) or f"pad-{index + 1}"
        if pad_id in seen:
            continue
        seen.add(pad_id)
        title = normalize_text(raw_pad.get("title")) or f"Pad {len(pads) + 1}"
        pads.append({
            "id": pad_id,
            "title": title,
            "customTitle": bool(raw_pad.get("customTitle", False)),
            "content": str(raw_pad.get("content") or ""),
            "updatedAt": normalize_text(raw_pad.get("updatedAt")),
            "createdAt": normalize_text(raw_pad.get("createdAt")),
        })

    active_id = normalize_text(raw.get("activeId"))
    if active_id not in seen:
        active_id = pads[0]["id"] if pads else ""
    return {"activeId": active_id, "pads": pads}
