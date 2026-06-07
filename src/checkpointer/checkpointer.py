from __future__ import annotations

from pathlib import Path
from typing import Any

from app_config import AppConfig, load_app_config
from checkpointer.sqlite import DEFAULT_CHECKPOINT_PATH, create_sqlite_checkpointer


def create_checkpointer(app_config: AppConfig | None = None) -> Any:
    config = _checkpointer_config(app_config or load_app_config())
    kind = str(config.get("type") or "sqlite").strip().lower()
    if kind != "sqlite":
        raise ValueError(f"Unsupported checkpointer type: {kind}")
    path = config.get("path") or DEFAULT_CHECKPOINT_PATH
    return create_sqlite_checkpointer(Path(path))


def _checkpointer_config(app_config: AppConfig) -> dict[str, Any]:
    config = app_config.get("checkpointer", {})
    if config is None:
        return {}
    if not isinstance(config, dict):
        raise ValueError("Config section must be an object: checkpointer")
    return dict(config)


__all__ = ["create_checkpointer"]
