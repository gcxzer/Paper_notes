from __future__ import annotations

import html
import re
import sys
from typing import Any
from urllib.parse import unquote

from backend.core import normalize_text
from backend.paths import HTML_DIR, PROJECT_ROOT, is_relative_to
from backend.storage import atomic_write_text


def create_paper_note_html(title: str, date: str, file_name: str) -> str:
    safe_title = html.escape(title, quote=True)
    safe_date = html.escape(date, quote=True)
    safe_file_name = html.escape(file_name, quote=True)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{safe_title}</title>
  <script src="/scripts/shared/theme.js"></script>
  <link rel="stylesheet" href="/styles/note.css">
</head>
<body>
  <main class="note">
    <header class="note-section">
      <p class="eyebrow note-eyebrow">Paper Note</p>
      <h1>{safe_title}</h1>
      <p class="meta note-meta">{safe_date} · {safe_file_name}</p>
    </header>

    <div class="note-workspace">
      <aside class="note-menu" aria-label="Note sections">
        <nav data-note-menu></nav>
      </aside>

      <section class="note-body"></section>
    </div>
  </main>
  <script src="/scripts/note/app.js"></script>
</body>
</html>"""


def update_note_html_title(note: dict[str, Any], next_title: str) -> None:
    html_href = normalize_text(note.get("htmlHref"))
    if not html_href:
        return
    html_path = (PROJECT_ROOT / unquote(html_href)).resolve()
    if not is_relative_to(html_path, HTML_DIR.resolve()):
        return
    try:
        safe_title = html.escape(next_title, quote=True)
        content = html_path.read_text(encoding="utf-8")
        content = re.sub(r"<title>[\s\S]*?</title>", f"<title>{safe_title}</title>", content, count=1, flags=re.IGNORECASE)
        content = re.sub(r"<h1>[\s\S]*?</h1>", f"<h1>{safe_title}</h1>", content, count=1, flags=re.IGNORECASE)
        atomic_write_text(html_path, content)
    except Exception as error:
        print(f"Could not update note HTML title for {note.get('id')}: {error}", file=sys.stderr)
