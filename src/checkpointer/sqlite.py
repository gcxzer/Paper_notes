from __future__ import annotations

import atexit
import sqlite3
import threading
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver

from app_config.config import PROJECT_ROOT


DEFAULT_CHECKPOINT_PATH = PROJECT_ROOT / ".paper-notes" / "checkpoints.sqlite"

_CACHE: dict[Path, tuple[sqlite3.Connection, SqliteSaver]] = {}
_LOCK = threading.Lock()


def create_sqlite_checkpointer(path: str | Path = DEFAULT_CHECKPOINT_PATH) -> SqliteSaver:
    db_path = Path(path).expanduser().resolve()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK:
        cached = _CACHE.get(db_path)
        if cached is not None:
            return cached[1]
        connection = sqlite3.connect(str(db_path), check_same_thread=False)
        saver = SqliteSaver(connection)
        _CACHE[db_path] = (connection, saver)
        return saver


def close_sqlite_checkpointers() -> None:
    with _LOCK:
        cached = list(_CACHE.values())
        _CACHE.clear()
    for connection, _saver in cached:
        connection.close()


atexit.register(close_sqlite_checkpointers)


__all__ = ["DEFAULT_CHECKPOINT_PATH", "close_sqlite_checkpointers", "create_sqlite_checkpointer"]
