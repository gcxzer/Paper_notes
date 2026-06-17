from __future__ import annotations

import errno
import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Any

__all__ = [
    "ANNOTATIONS_DIR",
    "ASSETS_DIR",
    "HTML_DIR",
    "HTML_HREF_PREFIX",
    "HOST",
    "LOCAL_STATE_DIR",
    "MAX_BODY_SIZE",
    "NODE_MODULES_DIR",
    "NOTES_PATH",
    "PAPERS_DIR",
    "PAPERS_HREF_PREFIX",
    "PORT",
    "PROJECT_ROOT",
    "PUBLIC_DIR",
    "RESOURCES_DIR",
    "atomic_replace",
    "atomic_write_json",
    "atomic_write_text",
    "is_relative_to",
]

PROJECT_ROOT = Path(__file__).resolve().parents[2]
LOCAL_STATE_DIR = PROJECT_ROOT / ".paper-notes"
PUBLIC_DIR = PROJECT_ROOT / "src" / "ui" / "frontend"
NODE_MODULES_DIR = PROJECT_ROOT / "node_modules"
ASSETS_DIR = PROJECT_ROOT / "assets"

HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "4173"))
MAX_BODY_SIZE = 200 * 1024 * 1024

RESOURCES_DIR = PROJECT_ROOT / "resources"
PAPERS_DIR = RESOURCES_DIR / "Papers"
HTML_DIR = RESOURCES_DIR / "Paper-html"
ANNOTATIONS_DIR = RESOURCES_DIR / "Paper-annotations"
NOTES_PATH = PROJECT_ROOT / "notes.json"

PAPERS_HREF_PREFIX = "resources/Papers"
HTML_HREF_PREFIX = "resources/Paper-html"

_LOCKS: dict[Path, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


def is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def atomic_replace(tmp_path: str | Path, target: str | Path) -> str:
    target_str = str(target)
    real_path = os.path.realpath(target_str) if os.path.islink(target_str) else target_str
    try:
        os.replace(str(tmp_path), real_path)
    except OSError as error:
        if error.errno not in {errno.EBUSY, errno.EXDEV}:
            raise
        _replace_bind_mount_file(tmp_path, real_path)
    return real_path


def atomic_write_text(path: str | Path, text: str, *, encoding: str = "utf-8") -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with _lock_for(target):
        fd, tmp_path = tempfile.mkstemp(dir=str(target.parent), prefix=f".{target.stem}_", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding=encoding) as file:
                file.write(text)
                file.flush()
                os.fsync(file.fileno())
            atomic_replace(tmp_path, target)
        except BaseException:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise


def atomic_write_json(path: str | Path, data: Any, *, indent: int = 2) -> None:
    text = json.dumps(data, ensure_ascii=False, indent=indent) + "\n"
    atomic_write_text(path, text)


def _lock_for(path: Path) -> threading.Lock:
    resolved = path.resolve()
    with _LOCKS_GUARD:
        if resolved not in _LOCKS:
            _LOCKS[resolved] = threading.Lock()
        return _LOCKS[resolved]


def _replace_bind_mount_file(tmp_path: str | Path, target: str | Path) -> None:
    tmp = Path(tmp_path)
    target_path = Path(target)
    with tmp.open("rb") as source:
        fd = os.open(str(target_path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            with os.fdopen(fd, "wb") as destination:
                while True:
                    chunk = source.read(1024 * 1024)
                    if not chunk:
                        break
                    destination.write(chunk)
                destination.flush()
                os.fsync(destination.fileno())
        except BaseException:
            try:
                os.close(fd)
            except OSError:
                pass
            raise
    os.unlink(tmp)
