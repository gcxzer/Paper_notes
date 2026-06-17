from __future__ import annotations

# Shared low-level helpers for Paper Notes paths, HTML fragments, and small validation utilities.

import html as html_lib
import re
from difflib import SequenceMatcher
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from app_infra.formatting import normalize_text
from app_infra.paths import PROJECT_ROOT, is_relative_to
from library.store import find_note, read_library

__all__ = [
    "positive_float",
    "positive_int",
    "relative_project_path",
    "resolve_note",
    "safe_served_src",
    "safe_src",
    "sanitize_html_fragment",
    "tool_error",
    "truthy",
]

SAFE_HTML_TAGS = {
    "a",
    "blockquote",
    "code",
    "em",
    "figcaption",
    "figure",
    "h2",
    "h3",
    "h4",
    "img",
    "li",
    "ol",
    "p",
    "pre",
    "strong",
    "table",
    "tbody",
    "td",
    "th",
    "thead",
    "tr",
    "ul",
    "video",
    "source",
}
SAFE_ATTRS_BY_TAG = {
    "a": {"href", "title"},
    "figure": {"class"},
    "h2": {"id"},
    "h3": {"id"},
    "h4": {"id"},
    "img": {"src", "alt", "title", "width", "height", "loading"},
    "video": {"src", "poster", "title", "width", "height", "controls", "loading", "preload"},
    "source": {"src", "type"},
    "td": {"colspan", "rowspan"},
    "th": {"colspan", "rowspan"},
}
BOOLEAN_ATTRS = {"controls"}
DANGEROUS_LINK_SCHEMES = {"javascript", "data", "vbscript"}
def positive_int(value: Any, *, default: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return min(max(parsed, 1), maximum)


def positive_float(value: Any, *, default: float, minimum: float, maximum: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return min(max(parsed, minimum), maximum)


def truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def relative_project_path(path: Path) -> str:
    resolved = Path(path).resolve()
    project_root = PROJECT_ROOT.resolve()
    if is_relative_to(resolved, project_root):
        return str(resolved.relative_to(project_root))
    return str(resolved)


def resolve_note(
    args: dict[str, Any],
    *,
    library_path: Path | None = None,
    allow_similar_id: bool = False,
) -> dict[str, Any]:
    note_id = normalize_text(args.get("note_id") or args.get("id"))
    if not note_id:
        return tool_error("note_id_required", "note_id is required")
    library = read_library(library_path) if library_path is not None else read_library()
    note = find_note(library, note_id)
    if note is None:
        if allow_similar_id:
            similar_note = _similar_note_for_id(library, note_id)
            if similar_note is not None:
                return {
                    "note": similar_note,
                    "requested_note_id": note_id,
                    "note_id_corrected": True,
                }
        return tool_error("note_not_found", f"Note not found: {note_id}", note_id=note_id)
    return {"note": note}


def _similar_note_for_id(library: dict[str, Any], note_id: str) -> dict[str, Any] | None:
    normalized_id = normalize_text(note_id)
    if len(normalized_id) < 12:
        return None
    notes = [note for note in library.get("notes", []) if isinstance(note, dict)]
    prefix_matches: list[dict[str, Any]] = []
    for note in notes:
        candidate_id = normalize_text(note.get("id"))
        if not candidate_id:
            continue
        if abs(len(candidate_id) - len(normalized_id)) <= 4 and (
            candidate_id.startswith(normalized_id) or normalized_id.startswith(candidate_id)
        ):
            prefix_matches.append(note)
    if len(prefix_matches) == 1:
        return prefix_matches[0]

    scored: list[tuple[float, dict[str, Any]]] = []
    for note in notes:
        candidate_id = normalize_text(note.get("id"))
        if not candidate_id:
            continue
        max_len = max(len(candidate_id), len(normalized_id))
        if abs(len(candidate_id) - len(normalized_id)) > max(4, int(max_len * 0.04)):
            continue
        ratio = SequenceMatcher(a=normalized_id, b=candidate_id).ratio()
        if ratio >= 0.97:
            scored.append((ratio, note))
    scored.sort(key=lambda item: item[0], reverse=True)
    if not scored:
        return None
    if len(scored) > 1 and scored[0][0] - scored[1][0] < 0.01:
        return None
    return scored[0][1]


def sanitize_html_fragment(raw_html: str) -> str:
    parser = _SafeHTMLFragmentParser()
    parser.feed(markdown_blockquotes_to_html(str(raw_html or "")))
    parser.close()
    return parser.rendered.strip()


def markdown_blockquotes_to_html(raw_html: str) -> str:
    lines = str(raw_html or "").splitlines(keepends=True)
    output: list[str] = []
    quote_lines: list[str] = []

    def flush_quote() -> None:
        if not quote_lines:
            return
        paragraphs = "\n".join(
            f"<p>{html_lib.escape(paragraph.strip(), quote=False)}</p>"
            for paragraph in "\n".join(quote_lines).split("\n\n")
            if paragraph.strip()
        )
        output.append(f"<blockquote>{paragraphs}</blockquote>")
        quote_lines.clear()

    for line in lines:
        match = re.match(r"^([ \t]{0,3})>[ \t]?(.*?)(\r?\n)?$", line)
        if match:
            quote_lines.append(match.group(2))
            continue
        flush_quote()
        output.append(line)
    flush_quote()
    return "".join(output)


def tool_error(code: str, message: str, **extra: Any) -> dict[str, Any]:
    return {"success": False, "error": message, "code": code, **extra}


class _SafeHTMLFragmentParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.parts: list[str] = []
        self._skip_depth = 0

    @property
    def rendered(self) -> str:
        return "".join(self.parts)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "iframe", "object", "embed"}:
            self._skip_depth += 1
            return
        if self._skip_depth or tag not in SAFE_HTML_TAGS:
            return
        rendered_attrs = self._safe_attrs(tag, attrs)
        suffix = f" {rendered_attrs}" if rendered_attrs else ""
        self.parts.append(f"<{tag}{suffix}>")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "iframe", "object", "embed"} and self._skip_depth:
            self._skip_depth -= 1
            return
        if self._skip_depth or tag not in SAFE_HTML_TAGS:
            return
        self.parts.append(f"</{tag}>")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self.parts.append(html_lib.escape(data, quote=False))

    def handle_entityref(self, name: str) -> None:
        if not self._skip_depth:
            self.parts.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        if not self._skip_depth:
            self.parts.append(f"&#{name};")

    @staticmethod
    def _safe_attrs(tag: str, attrs: list[tuple[str, str | None]]) -> str:
        allowed = SAFE_ATTRS_BY_TAG.get(tag, set())
        rendered: list[str] = []
        for raw_name, raw_value in attrs:
            name = raw_name.lower()
            if name not in allowed:
                continue
            value = normalize_text(raw_value)
            if name == "href":
                value = clean_href(value)
                if not safe_href(value):
                    continue
            if name in {"src", "poster"} and not safe_src(value):
                continue
            if name in BOOLEAN_ATTRS:
                rendered.append(name)
                continue
            if name == "class" and value != "note-figure":
                continue
            if name == "loading" and value not in {"lazy", "eager"}:
                continue
            if name == "preload" and value not in {"none", "metadata", "auto"}:
                continue
            if name in {"width", "height"} and (not value.isdigit() or int(value) <= 0):
                continue
            if name in {"colspan", "rowspan"} and not value.isdigit():
                continue
            rendered.append(f'{name}="{html_lib.escape(value, quote=True)}"')
        return " ".join(rendered)


def safe_href(value: str) -> bool:
    cleaned = normalize_text(value)
    if not cleaned or _has_control_chars(cleaned):
        return False
    parsed = urlparse(cleaned)
    scheme = parsed.scheme.lower()
    return scheme not in DANGEROUS_LINK_SCHEMES


def clean_href(value: str) -> str:
    cleaned = normalize_text(value)
    if not cleaned:
        return ""
    for delimiter in ("（", "）", "【", "】", "《", "》"):
        index = cleaned.find(delimiter)
        if index > -1:
            cleaned = cleaned[:index]
    return cleaned.rstrip(".,!?;:，。！？；：、")


def safe_served_src(value: str) -> bool:
    lowered = normalize_text(value).lower()
    return lowered.startswith(("/api/media/", "/resources/", "resources/", "/assets/", "assets/"))


def safe_src(value: str) -> bool:
    cleaned = normalize_text(value)
    if not cleaned or _has_control_chars(cleaned):
        return False
    parsed = urlparse(cleaned)
    scheme = parsed.scheme.lower()
    if scheme in DANGEROUS_LINK_SCHEMES or scheme in {"http", "https"}:
        return False
    return safe_served_src(cleaned) or _local_media_source_is_in_project(cleaned)


def _local_media_source_is_in_project(value: str) -> bool:
    parsed = urlparse(value)
    if parsed.scheme and parsed.scheme != "file":
        return False
    raw_path = unquote(parsed.path if parsed.scheme == "file" else value)
    if not raw_path:
        return False
    candidate = Path(raw_path).expanduser()
    if not candidate.is_absolute():
        candidate = PROJECT_ROOT / candidate
    try:
        return is_relative_to(candidate.resolve(), PROJECT_ROOT.resolve())
    except OSError:
        return False


def _has_control_chars(value: str) -> bool:
    return any(ord(char) < 32 or ord(char) == 127 for char in value)


