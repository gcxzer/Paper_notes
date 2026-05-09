from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Any


_LOCKS: dict[Path, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


def _lock_for(path: Path) -> threading.Lock:
    resolved = path.resolve()
    with _LOCKS_GUARD:
        if resolved not in _LOCKS:
            _LOCKS[resolved] = threading.Lock()
        return _LOCKS[resolved]


def atomic_replace(tmp_path: str | Path, target: str | Path) -> str:
    target_str = str(target)
    real_path = os.path.realpath(target_str) if os.path.islink(target_str) else target_str
    os.replace(str(tmp_path), real_path)
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
