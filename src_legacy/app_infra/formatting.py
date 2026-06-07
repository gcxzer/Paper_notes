from __future__ import annotations

import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote


def normalize_text(value: Any) -> str:
    return str(value or "").strip()


def get_today_label() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def iso_now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def base36(value: int) -> str:
    chars = "0123456789abcdefghijklmnopqrstuvwxyz"
    if value == 0:
        return "0"
    result = ""
    while value:
        value, remainder = divmod(value, 36)
        result = chars[remainder] + result
    return result


def safe_file_name(file_name: str) -> str:
    original = Path(file_name or "Untitled Paper.pdf").name
    ext = Path(original).suffix.lower() or ".pdf"
    base = original[: -len(Path(original).suffix)] if Path(original).suffix else original
    base = re.sub(r'[\\/:*?"<>|#%{}^~\[\]`]+', "", base)
    base = re.sub(r"\s+", " ", base).strip()
    return f"{base or 'Untitled Paper'}{ext}"


def note_title_from_pdf(file_name: str) -> str:
    title = Path(file_name).stem
    title = re.sub(r"[-_]+", " ", title).strip()
    return title or "Untitled PDF"


def note_id_from_title(title: str) -> str:
    slug = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "-", normalize_text(title).lower(), flags=re.IGNORECASE)
    slug = slug.strip("-")[:80]
    stamp = int(time.time() * 1000)
    return f"pdf-{slug or stamp}-{base36(stamp)}"


def finite_number(value: Any, fallback: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return fallback
    if number != number or number in (float("inf"), float("-inf")):
        return fallback
    return number


def resource_href(prefix: str, file_name: str) -> str:
    return f"{prefix}/{quote(file_name)}"
