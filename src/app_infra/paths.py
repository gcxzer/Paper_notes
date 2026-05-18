from __future__ import annotations

import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PUBLIC_DIR = PROJECT_ROOT / "src" / "ui" / "frontend"
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


def is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False
