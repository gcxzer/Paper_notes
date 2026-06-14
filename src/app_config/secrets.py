from __future__ import annotations

import os
import re
import tempfile
import threading
from pathlib import Path
from typing import Mapping


PROJECT_ROOT = Path(__file__).resolve().parents[2]
LOCAL_STATE_DIR = PROJECT_ROOT / ".paper-notes"
DEFAULT_SECRETS_PATH = LOCAL_STATE_DIR / "secrets.env"
DEFAULT_ENV_PATHS = (
    PROJECT_ROOT / ".env.local",
    PROJECT_ROOT / ".env",
)

_ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_LOCKS: dict[Path, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


def default_secrets_path() -> Path:
    override = os.environ.get("PAPER_NOTES_SECRETS_PATH", "").strip()
    return Path(override).expanduser() if override else DEFAULT_SECRETS_PATH


def default_env_paths() -> tuple[Path, ...]:
    override = os.environ.get("PAPER_NOTES_ENV_PATHS", "").strip()
    if not override:
        return DEFAULT_ENV_PATHS
    return tuple(Path(part).expanduser() for part in override.split(os.pathsep) if part.strip())


def parse_env_file(path: str | Path) -> dict[str, str]:
    env_path = Path(path)
    if not env_path.exists():
        return {}
    try:
        text = env_path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        text = env_path.read_text(encoding="latin-1")
    return parse_env_text(text)


def parse_env_text(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        key, separator, value = line.partition("=")
        if not separator:
            continue
        key = key.strip()
        if not _ENV_NAME_RE.match(key):
            continue
        values[key] = _parse_env_value(value)
    return values


def write_env_values(path: str | Path, updates: Mapping[str, str | None]) -> None:
    target = Path(path)
    cleaned_updates = {_normalize_env_name(key): value for key, value in updates.items()}
    target.parent.mkdir(parents=True, exist_ok=True)
    _secure_dir(target.parent)

    with _lock_for(target):
        lines = target.read_text(encoding="utf-8").splitlines() if target.exists() else []
        rendered: list[str] = []
        seen: set[str] = set()

        for line in lines:
            key = _line_env_name(line)
            if not key or key not in cleaned_updates:
                rendered.append(line)
                continue
            seen.add(key)
            value = cleaned_updates[key]
            if value is None:
                continue
            rendered.append(f"{key}={_quote_env_value(value)}")

        for key, value in cleaned_updates.items():
            if key in seen or value is None:
                continue
            rendered.append(f"{key}={_quote_env_value(value)}")

        text = "\n".join(rendered).rstrip()
        if text:
            text += "\n"
        _atomic_write_text(target, text)
        _secure_file(target)


def _parse_env_value(raw_value: str) -> str:
    value = raw_value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1]
        if raw_value.strip().startswith('"'):
            value = value.replace(r"\n", "\n").replace(r"\"", '"').replace(r"\\", "\\")
        return value
    hash_index = value.find(" #")
    if hash_index >= 0:
        value = value[:hash_index].rstrip()
    return value


def _line_env_name(line: str) -> str:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return ""
    if stripped.startswith("export "):
        stripped = stripped[len("export "):].lstrip()
    key, separator, _value = stripped.partition("=")
    key = key.strip()
    return key if separator and _ENV_NAME_RE.match(key) else ""


def _quote_env_value(value: str) -> str:
    text = str(value).strip()
    if not text:
        return ""
    if re.search(r"\s|#|['\"\\\\]", text):
        escaped = text.replace("\\", "\\\\").replace('"', r"\"").replace("\n", r"\n")
        return f'"{escaped}"'
    return text


def _normalize_env_name(key: str) -> str:
    normalized = str(key).strip().upper()
    if not _ENV_NAME_RE.match(normalized):
        raise ValueError(f"Invalid environment variable name: {key}")
    return normalized


def _lock_for(path: Path) -> threading.Lock:
    resolved = path.resolve()
    with _LOCKS_GUARD:
        if resolved not in _LOCKS:
            _LOCKS[resolved] = threading.Lock()
        return _LOCKS[resolved]


def _atomic_write_text(path: Path, text: str) -> None:
    fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.stem}_", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            file.write(text)
            file.flush()
            os.fsync(file.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _secure_dir(path: Path) -> None:
    try:
        os.chmod(path, 0o700)
    except OSError:
        pass


def _secure_file(path: Path) -> None:
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
