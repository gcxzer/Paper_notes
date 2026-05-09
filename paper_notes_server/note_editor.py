from __future__ import annotations

import re

from .storage import normalize_text


MAX_NOTE_BODY_CHARS = 80_000


def _section_tag_matches(html: str):
    return re.finditer(r"</?section\b[^>]*>", html, flags=re.IGNORECASE)


def _has_note_body_class(tag: str) -> bool:
    class_match = re.search(r"\bclass\s*=\s*(['\"])(.*?)\1", tag, flags=re.IGNORECASE | re.DOTALL)
    if class_match:
        return "note-body" in class_match.group(2).split()
    return bool(re.search(r"\bclass\s*=\s*[^>\s]*note-body[^>\s]*", tag, flags=re.IGNORECASE))


def note_body_bounds(html: str) -> tuple[int, int, int, int]:
    for match in _section_tag_matches(html):
        tag = match.group(0)
        if tag.startswith("</") or not _has_note_body_class(tag):
            continue

        depth = 1
        body_start = match.end()
        for nested in _section_tag_matches(html[body_start:]):
            nested_tag = nested.group(0)
            if nested_tag.startswith("</"):
                depth -= 1
            else:
                depth += 1
            if depth == 0:
                body_end = body_start + nested.start()
                close_end = body_start + nested.end()
                return match.start(), body_start, body_end, close_end
    raise ValueError("Could not find <section class=\"note-body\"> in this note.")


def extract_note_body_html(note_html: str) -> str:
    _, body_start, body_end, _ = note_body_bounds(note_html)
    return note_html[body_start:body_end].strip()


def replace_note_body_html(note_html: str, replacement_html: str) -> str:
    _, body_start, body_end, _ = note_body_bounds(note_html)
    clean_replacement = normalize_replacement_html(replacement_html)
    return f"{note_html[:body_start]}\n{clean_replacement.rstrip()}\n      {note_html[body_end:]}"


def normalize_replacement_html(value: object) -> str:
    html = str(value or "").strip()
    html = re.sub(r"^```(?:html)?\s*", "", html, flags=re.IGNORECASE)
    html = re.sub(r"\s*```$", "", html)
    if "note-body" in html and "<section" in html.lower():
        try:
            html = extract_note_body_html(html)
        except ValueError:
            pass
    if not html:
        raise ValueError("The note edit draft did not include replacement HTML.")
    return html.strip()
