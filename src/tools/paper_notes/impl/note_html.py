from __future__ import annotations

import html
import re
import sys
from typing import Any
from urllib.parse import unquote

from tools.paper_notes.impl.formatting import normalize_text
from tools.paper_notes.impl.paths import HTML_DIR, PROJECT_ROOT, is_relative_to
from tools.paper_notes.impl.storage import atomic_write_text


def create_paper_note_html(
    title: str,
    date: str,
    file_name: str,
    outline: list[dict[str, Any]] | None = None,
) -> str:
    safe_title = html.escape(title, quote=True)
    safe_date = html.escape(date, quote=True)
    safe_file_name = html.escape(file_name, quote=True)
    note_body = render_note_outline(outline or [])
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{safe_title}</title>
  <script src="/scripts/shared/theme.js"></script>
  <script src="/scripts/shared/button-feedback.js?v=button-press-v1"></script>
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

      <section class="note-body">{note_body}</section>
    </div>
  </main>
  <script src="/scripts/note/app.js"></script>
</body>
</html>"""


def render_note_outline(outline: list[dict[str, Any]]) -> str:
    headings: list[str] = []
    counters = [0, 0, 0]
    for item in outline:
        if not isinstance(item, dict):
            continue
        text = normalize_text(item.get("title"))
        if not text:
            continue
        try:
            level = int(item.get("level", 1))
        except (TypeError, ValueError):
            level = 1
        level = min(max(level, 1), 3)
        counters[level - 1] += 1
        for index in range(level, len(counters)):
            counters[index] = 0
        for index in range(level - 1):
            if counters[index] == 0:
                counters[index] = 1
        number = ".".join(str(value) for value in counters[:level] if value)
        heading_text = text if _starts_with_outline_number(text) else f"{number}. {text}"
        tag_level = level + 1
        headings.append(f"\n        <h{tag_level}>{html.escape(heading_text)}</h{tag_level}>")
    return "".join(headings) + "\n      " if headings else ""


def _starts_with_outline_number(value: str) -> bool:
    return bool(re.match(r"^(?:\d+(?:\.\d+)*|[IVXLC]+)\.?\s+", value, flags=re.IGNORECASE))


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
