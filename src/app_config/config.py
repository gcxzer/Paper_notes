from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = PROJECT_ROOT / "config.json"


@dataclass(frozen=True, slots=True)
class AppConfig:
    data: dict[str, Any]
    path: Path | None

    def get(self, dotted_key: str, default: Any = None) -> Any:
        value: Any = self.data
        for part in dotted_key.split("."):
            if not isinstance(value, dict) or part not in value:
                return default
            value = value[part]
        return value


def load_app_config(path: str | Path | None = None) -> AppConfig:
    config_path = _resolve_config_path(path)
    data = _read_json_object(config_path) if config_path.exists() else {}
    return AppConfig(data=data, path=config_path)


def _resolve_config_path(path: str | Path | None) -> Path | None:
    if path is not None:
        return Path(path).expanduser().resolve()
    env_path = os.getenv("PAPER_NOTES_CONFIG")
    if env_path:
        return Path(env_path).expanduser().resolve()
    return CONFIG_PATH


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"Invalid JSON config: {path}") from error
    if not isinstance(payload, dict):
        raise ValueError(f"JSON config must be an object: {path}")
    return payload
