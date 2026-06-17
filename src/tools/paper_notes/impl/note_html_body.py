from __future__ import annotations

import html as html_lib
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from app_infra.files import HTML_DIR, PROJECT_ROOT, atomic_write_text, is_relative_to
from app_infra.formatting import normalize_text
from tools.paper_notes.impl.artifacts import _artifact_to_payload
from tools.paper_notes.impl.common import (
    positive_int,
    resolve_note,
    safe_served_src,
    safe_src,
    sanitize_html_fragment,
    tool_error,
)

__all__ = [
    "NOTE_SECTION_POSITIONS",
    "added_heading_names",
    "apply_body_update",
    "collect_headings",
    "delete_heading_section",
    "diff_summary",
    "format_note_body_html",
    "image_figure_html",
    "load_note_html_body",
    "note_body_match",
    "note_body_child_indent",
    "note_html_path",
    "prepare_note_section_update",
    "read_note_html_body_document",
    "resolve_media_source_args",
    "resolve_note_html_path",
    "validate_html_document",
    "write_note_html_body",
]

_NOTE_BODY_RE = re.compile(
    r"(?is)(<(?P<tag>section|div|main)\b(?=[^>]*\bclass=[\"'][^\"']*\bnote-body\b[^\"']*[\"'])[^>]*>)"
    r"(?P<body>.*?)"
    r"(</(?P=tag)>)"
)


@dataclass(frozen=True, slots=True)
class LoadedNoteHtmlBody:
    note: dict[str, Any]
    html_path: Path
    document: str
    match: re.Match[str]


def note_html_path(note: dict[str, Any], *, html_dir: Path | None = None) -> Path | None:
    html_href = normalize_text(note.get("htmlHref"))
    if not html_href:
        return None
    base_dir = (html_dir or HTML_DIR).resolve()
    raw_path = Path(unquote(html_href))
    if raw_path.is_absolute():
        html_path = raw_path.resolve()
    elif html_dir is not None:
        parts = raw_path.parts
        if "Paper-html" in parts:
            rel_path = Path(*parts[parts.index("Paper-html") + 1:])
        else:
            rel_path = raw_path
        html_path = (base_dir / rel_path).resolve()
    else:
        html_path = (PROJECT_ROOT / raw_path).resolve()
    if not is_relative_to(html_path, base_dir):
        return None
    return html_path


def note_body_match(document: str) -> re.Match[str] | None:
    return _NOTE_BODY_RE.search(document)


def resolve_note_html_path(
    args: dict[str, Any],
    *,
    library_path: Path | None = None,
    html_dir: Path | None = None,
) -> tuple[dict[str, Any] | None, Path | None, dict[str, Any] | None]:
    note_result = resolve_note(args, library_path=library_path)
    if "error" in note_result:
        return None, None, note_result
    note = note_result["note"]
    html_path = note_html_path(note, html_dir=html_dir)
    if html_path is None:
        return None, None, tool_error("note_html_missing", "Note has no local HTML path.", note_id=note["id"])
    return note, html_path, None


def read_note_html_body_document(
    note: dict[str, Any],
    html_path: Path,
) -> tuple[str, re.Match[str] | None, dict[str, Any] | None]:
    try:
        document = html_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return "", None, tool_error("note_html_not_found", f"HTML note file was not found: {html_path.name}", note_id=note["id"])
    match = note_body_match(document)
    if match is None:
        return "", None, tool_error("note_body_missing", "HTML note does not contain a .note-body element.", note_id=note["id"])
    return document, match, None


def load_note_html_body(
    args: dict[str, Any],
    *,
    library_path: Path | None = None,
    html_dir: Path | None = None,
) -> tuple[LoadedNoteHtmlBody | None, dict[str, Any] | None]:
    note, html_path, path_error = resolve_note_html_path(args, library_path=library_path, html_dir=html_dir)
    if path_error:
        return None, path_error
    assert note is not None
    assert html_path is not None
    document, match, body_error = read_note_html_body_document(note, html_path)
    if body_error:
        return None, body_error
    assert match is not None
    return LoadedNoteHtmlBody(note=note, html_path=html_path, document=document, match=match), None


_HEADING_RE = re.compile(r"(?is)<h([2-4])\b[^>]*>(.*?)</h\1>")
_HEADING_WITH_ATTRS_RE = re.compile(r"(?is)<h([2-4])([^>]*)>(.*?)</h\1>")
_NOTE_BODY_LINE_START_TAGS = (
    "h2",
    "h3",
    "h4",
    "p",
    "ul",
    "ol",
    "li",
    "blockquote",
    "table",
    "thead",
    "tbody",
    "tr",
    "th",
    "td",
    "figure",
    "figcaption",
    "img",
    "video",
    "source",
)
_NOTE_BODY_CONTAINER_TAGS = {
    "ul",
    "ol",
    "blockquote",
    "table",
    "thead",
    "tbody",
    "tr",
    "figure",
    "video",
}
_NOTE_SECTION_POSITIONS = {"append", "prepend", "after_heading", "replace_heading"}

@dataclass(frozen=True, slots=True)
class _NoteSectionUpdate:
    heading: str
    position: str
    current_body: str
    next_body: str
    before_headings: list[dict[str, Any]]
    after_headings: list[dict[str, Any]]


def _validate_html_document(document: str) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    match = note_body_match(document)
    if match is None:
        issues.append({"code": "note_body_missing", "message": "HTML note does not contain .note-body."})
        content_to_validate = document
    else:
        content_to_validate = match.group("body")
    dangerous_patterns = {
        "script_tag": r"(?is)<\s*script\b",
        "style_tag": r"(?is)<\s*style\b",
        "event_handler": r"(?is)\son[a-z]+\s*=",
        "javascript_href": r"(?is)href\s*=\s*['\"]\s*javascript:",
        "data_href": r"(?is)href\s*=\s*['\"]\s*data:",
    }
    for code, pattern in dangerous_patterns.items():
        if re.search(pattern, content_to_validate):
            issues.append({"code": code, "message": f"Unsafe HTML pattern detected: {code}."})
    return issues


def _added_heading_names(before: list[dict[str, Any]], after: list[dict[str, Any]]) -> list[str]:
    before_names = {normalize_text(item.get("heading")).casefold() for item in before}
    return [
        normalize_text(item.get("heading"))
        for item in after
        if normalize_text(item.get("heading")).casefold() not in before_names
    ]


def _diff_summary(before: str, after: str) -> str:
    delta = len(after) - len(before)
    if delta == 0:
        return "No text-length change."
    direction = "Added" if delta > 0 else "Removed"
    return f"{direction} {abs(delta)} HTML body characters."

def _section_fragment(
    *,
    heading: str,
    raw_html: str,
    heading_level: int = 2,
    allow_heading_only: bool = False,
) -> str:
    sanitized = sanitize_html_fragment(raw_html)
    if not sanitized:
        if allow_heading_only and heading:
            return _ensure_heading_ids(f"<h{heading_level}>{html_lib.escape(heading)}</h{heading_level}>")
        return ""
    if _starts_with_heading(sanitized):
        return _ensure_heading_ids(_normalize_leading_matching_heading_level(sanitized, heading, heading_level))
    if not heading:
        return _ensure_heading_ids(sanitized)
    return _ensure_heading_ids(f"<h{heading_level}>{html_lib.escape(heading)}</h{heading_level}>\n{sanitized}")


def _image_figure_html(*, artifact: dict[str, Any], caption: str, alt: str) -> str:
    src = normalize_text(artifact.get("url"))
    if not src:
        src = f"/api/media/{html_lib.escape(normalize_text(artifact.get('id')), quote=True)}"
    rendered_alt = alt or normalize_text(artifact.get("fileName")) or "Generated note image"
    attrs = [
        f'src="{html_lib.escape(src, quote=True)}"',
        f'alt="{html_lib.escape(rendered_alt, quote=True)}"',
        'loading="lazy"',
    ]
    width = positive_int(artifact.get("width"), default=0, maximum=100_000)
    height = positive_int(artifact.get("height"), default=0, maximum=100_000)
    if width:
        attrs.append(f'width="{width}"')
    if height:
        attrs.append(f'height="{height}"')
    parts = [
        '<figure class="note-figure">',
        f"<img {' '.join(attrs)}>",
    ]
    if caption:
        parts.append(f"<figcaption>{html_lib.escape(caption, quote=False)}</figcaption>")
    parts.append("</figure>")
    return "\n".join(parts)

def _resolve_media_source_args(args: dict[str, Any], media_store: Any | None) -> tuple[dict[str, Any], dict[str, Any] | None]:
    raw_html = str(args.get("html") or "")
    if not raw_html:
        return args, None
    if media_store is None:
        if _html_has_unserved_media_source(raw_html):
            return args, tool_error(
                "media_store_unavailable",
                "Image and video sources must be served project media/resources paths or local files under the Paper Notes workspace.",
                note_id=normalize_text(args.get("note_id")),
            )
        return args, None
    rewritten, unresolved = _rewrite_media_sources(raw_html, media_store)
    if unresolved:
        return args, tool_error(
            "image_must_be_in_media_store",
            "Image and video sources must be placed under the Paper Notes workspace before inserting them into notes.",
            note_id=normalize_text(args.get("note_id")),
            unresolved_sources=unresolved[:5],
        )
    if rewritten == raw_html:
        return args, None
    return {**args, "html": rewritten}, None


def _rewrite_media_sources(raw_html: str, media_store: Any) -> tuple[str, list[str]]:
    unresolved: list[str] = []

    def replace(match: re.Match[str]) -> str:
        prefix = match.group("prefix")
        quote = match.group("quote")
        tag = match.group("tag").lower()
        attr = match.group("attr").lower()
        src = html_lib.unescape(match.group("src"))
        if tag == "img" and attr == "src":
            resolved = _media_url_for_image_source(src, media_store)
            if not resolved and not safe_src(src):
                unresolved.append(src)
        else:
            resolved = src
            if not safe_src(src):
                unresolved.append(src)
                resolved = ""
        return f"{prefix}{quote}{html_lib.escape(resolved or src, quote=True)}{quote}"

    rewritten = re.sub(
        r"(?is)(?P<prefix><(?P<tag>img|video|source)\b[^>]*?\b(?P<attr>src|poster)\s*=\s*)(?P<quote>['\"])(?P<src>.*?)(?P=quote)",
        replace,
        raw_html,
    )
    return rewritten, unresolved


def _html_has_unserved_media_source(raw_html: str) -> bool:
    for match in re.finditer(r"(?is)<(?:img|video|source)\b[^>]*?\b(?:src|poster)\s*=\s*(['\"])(.*?)\1", raw_html or ""):
        src = html_lib.unescape(match.group(2))
        if src and not safe_src(src):
            return True
    return False


def _media_url_for_image_source(src: str, media_store: Any) -> str:
    value = normalize_text(src)
    if not value or safe_served_src(value):
        return value

    parsed = urlparse(value)
    if parsed.scheme and parsed.scheme != "file":
        return ""
    raw_path = unquote(parsed.path if parsed.scheme == "file" else value)
    candidate = Path(raw_path).expanduser()
    if not candidate.is_absolute():
        candidate = (PROJECT_ROOT / candidate).resolve()
    else:
        candidate = candidate.resolve()

    root = getattr(media_store, "root", None)
    try:
        media_root = Path(root).resolve() if root is not None else None
    except OSError:
        media_root = None
    if media_root is not None and not is_relative_to(candidate, media_root):
        project_url = _project_served_media_url(candidate)
        return project_url if project_url else ""

    find_by_path = getattr(media_store, "find_by_path", None)
    if callable(find_by_path):
        try:
            artifact = find_by_path(candidate)
        except Exception:
            artifact = None
        payload = _artifact_to_payload(artifact)
        if normalize_text(payload.get("kind") or "image") == "image" and normalize_text(payload.get("url")):
            return normalize_text(payload.get("url"))

    public_artifact = getattr(media_store, "public_artifact", None)
    if callable(public_artifact):
        artifact_id = candidate.stem
        try:
            payload = public_artifact(artifact_id)
        except Exception:
            payload = {}
        if (
            isinstance(payload, dict)
            and normalize_text(payload.get("kind") or "image") == "image"
            and normalize_text(payload.get("url"))
        ):
            return normalize_text(payload.get("url"))
    return ""


def _project_served_media_url(candidate: Path) -> str:
    try:
        resolved = candidate.resolve()
        project_root = PROJECT_ROOT.resolve()
    except OSError:
        return ""
    if not is_relative_to(resolved, project_root):
        return ""
    relative = resolved.relative_to(project_root)
    if not relative.parts or relative.parts[0] not in {"resources", "assets"}:
        return ""
    return "/" + relative.as_posix()


def _starts_with_heading(fragment: str) -> bool:
    return re.match(r"(?is)^\s*<h[2-4]\b", fragment) is not None


def _normalize_leading_matching_heading_level(fragment: str, heading: str, heading_level: int) -> str:
    normalized_heading = normalize_text(heading).casefold()
    if not normalized_heading:
        return fragment
    match = _HEADING_RE.match(fragment.strip())
    if match is None:
        return fragment
    text = normalize_text(_strip_html(match.group(2))).casefold()
    if text != normalized_heading:
        return fragment
    level = max(2, min(4, int(heading_level)))
    return f"<h{level}>{match.group(2)}</h{level}>{fragment.strip()[match.end():]}"


def _apply_body_update(
    current_body: str,
    *,
    fragment: str,
    heading: str,
    position: str,
) -> tuple[str, bool]:
    if position == "append":
        existing = _find_heading_section(current_body, heading)
        if heading and existing is not None:
            _start, end = existing
            return _join_fragments(current_body[:end].strip(), _fragment_without_leading_matching_heading(fragment, heading), current_body[end:].strip()), True
        return _join_fragments(current_body, fragment), True
    if position == "prepend":
        return _join_fragments(fragment, current_body), True

    target = _find_heading_section(current_body, heading)
    if target is None:
        return current_body, False
    start, end = target
    if position == "replace_heading":
        return _join_fragments(current_body[:start].strip(), fragment, current_body[end:].strip()), True
    if position == "after_heading":
        return _join_fragments(current_body[:end].strip(), fragment, current_body[end:].strip()), True
    return current_body, False


def _prepare_note_section_update(
    args: dict[str, Any],
    *,
    document: str,
    match: re.Match[str],
    note_id: str,
    default_position: str = "append",
) -> tuple[_NoteSectionUpdate | None, dict[str, Any] | None]:
    heading = normalize_text(args.get("heading"))
    raw_html = str(args.get("html") or "")
    position = normalize_text(args.get("position") or default_position).lower()
    if position not in _NOTE_SECTION_POSITIONS:
        return None, tool_error(
            "invalid_position",
            "position must be append, prepend, after_heading, or replace_heading.",
            note_id=note_id,
        )

    current_body = match.group("body").strip()
    target_exists = _find_heading_section(current_body, heading) is not None
    fragment = _section_fragment(
        heading=heading,
        raw_html=raw_html,
        heading_level=_heading_level_for(current_body, heading),
        allow_heading_only=position == "replace_heading" and target_exists,
    )
    if not fragment:
        return None, tool_error("empty_html", "html must contain safe note content.", note_id=note_id)

    next_body, changed = _apply_body_update(current_body, fragment=fragment, heading=heading, position=position)
    if not changed:
        return None, tool_error("heading_not_found", f"Could not find heading: {heading}", note_id=note_id)

    next_body = _format_note_body_html(next_body, base_indent=_note_body_child_indent(document, match))
    return _NoteSectionUpdate(
        heading=heading,
        position=position,
        current_body=current_body,
        next_body=next_body,
        before_headings=_collect_headings(current_body),
        after_headings=_collect_headings(next_body),
    ), None


def _delete_heading_section(current_body: str, heading: str) -> tuple[str, bool]:
    target = _find_heading_section(current_body, heading)
    if target is None:
        return current_body, False
    start, end = target
    return _join_fragments(current_body[:start].strip(), current_body[end:].strip()), True


def _fragment_without_leading_matching_heading(fragment: str, heading: str) -> str:
    normalized_heading = normalize_text(heading).casefold()
    if not normalized_heading:
        return fragment
    match = _HEADING_RE.match(fragment.strip())
    if match is None:
        return fragment
    text = normalize_text(_strip_html(match.group(2))).casefold()
    if text != normalized_heading:
        return fragment
    return fragment.strip()[match.end():].strip()


def _find_heading_section(body: str, heading: str) -> tuple[int, int] | None:
    normalized_heading = normalize_text(heading).casefold()
    if not normalized_heading:
        return None
    matches = list(_HEADING_RE.finditer(body))
    for index, match in enumerate(matches):
        text = normalize_text(_strip_html(match.group(2))).casefold()
        if text != normalized_heading:
            continue
        level = int(match.group(1))
        end = len(body)
        for later in matches[index + 1:]:
            if int(later.group(1)) <= level:
                end = later.start()
                break
        return match.start(), end
    return None

def _heading_level_for(body: str, heading: str) -> int:
    normalized_heading = normalize_text(heading).casefold()
    if not normalized_heading:
        return 2
    for match in _HEADING_RE.finditer(body):
        text = normalize_text(_strip_html(match.group(2))).casefold()
        if text == normalized_heading:
            return max(2, min(4, int(match.group(1))))
    return 2

def _join_fragments(*fragments: str) -> str:
    return "\n\n".join(fragment.strip() for fragment in fragments if fragment and fragment.strip())


def _strip_surrounding_blank_lines(value: str) -> str:
    lines = str(value or "").splitlines()
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines)


def _note_body_container_indent(document: str, match: re.Match[str]) -> str:
    line_start = document.rfind("\n", 0, match.start()) + 1
    opening_line = document[line_start:match.start()]
    return re.match(r"[ \t]*", opening_line).group(0)


def _note_body_child_indent(document: str, match: re.Match[str]) -> str:
    for line in match.group("body").splitlines():
        if not line.strip():
            continue
        existing_indent = re.match(r"[ \t]*", line).group(0)
        if existing_indent:
            return existing_indent
        break
    opening_indent = _note_body_container_indent(document, match)
    return f"{opening_indent}  " if opening_indent else ""


def _format_note_body_html(body: str, *, base_indent: str = "") -> str:
    value = _strip_surrounding_blank_lines(body)
    if not value:
        return ""

    preserved: dict[str, str] = {}

    def preserve_pre(match: re.Match[str]) -> str:
        token = f"@@PAPER_NOTES_PRE_BLOCK_{len(preserved)}@@"
        preserved[token] = match.group(0).strip()
        return f"\n{token}\n"

    value = re.sub(r"(?is)<pre\b.*?</pre>", preserve_pre, value)
    line_start_tags = "|".join(re.escape(tag) for tag in _NOTE_BODY_LINE_START_TAGS)
    container_tags = "|".join(re.escape(tag) for tag in sorted(_NOTE_BODY_CONTAINER_TAGS))
    value = re.sub(rf"\s*(<(?:(?:{line_start_tags})\b)[^>]*>)", r"\n\1", value, flags=re.IGNORECASE)
    value = re.sub(rf"\s*(</(?:{container_tags})>)", r"\n\1", value, flags=re.IGNORECASE)

    lines = [line.strip() for line in value.splitlines() if line.strip()]
    if not lines:
        return ""

    formatted: list[str] = []
    indent = 0
    closing_re = re.compile(rf"^</(?:{container_tags})>$", re.IGNORECASE)
    opening_re = re.compile(rf"^<({container_tags})\b[^>]*>$", re.IGNORECASE)
    for line in lines:
        if closing_re.match(line):
            indent = max(0, indent - 1)
        prefix = f"{base_indent}{'  ' * indent}"
        if line in preserved:
            formatted.append(f"{prefix}{preserved[line]}")
        else:
            formatted.append(f"{prefix}{line}")
        opening = opening_re.match(line)
        if opening and not re.search(rf"</{re.escape(opening.group(1))}>$", line, re.IGNORECASE):
            indent += 1
    return "\n".join(formatted)


def _with_surrounding_newlines(body: str, *, trailing_indent: str = "") -> str:
    value = _strip_surrounding_blank_lines(body)
    return f"\n{value}\n{trailing_indent}" if value else ""


def _replace_note_html_body(document: str, match: re.Match[str], body: str) -> str:
    return (
        document[:match.start("body")]
        + _with_surrounding_newlines(body, trailing_indent=_note_body_container_indent(document, match))
        + document[match.end("body"):]
    )


def _write_note_html_body(html_path: Path, document: str, match: re.Match[str], body: str) -> str:
    next_document = _replace_note_html_body(document, match, body)
    atomic_write_text(html_path, next_document)
    return next_document


def _strip_html(value: str) -> str:
    return re.sub(r"<[^>]+>", "", html_lib.unescape(value or ""))


def _ensure_heading_ids(fragment: str) -> str:
    used_ids = set()
    for match in _HEADING_WITH_ATTRS_RE.finditer(fragment):
        existing_id = _extract_id(match.group(2))
        if existing_id:
            used_ids.add(existing_id)

    def replace(match: re.Match[str]) -> str:
        level = match.group(1)
        attrs = match.group(2)
        body = match.group(3)
        if _extract_id(attrs):
            return match.group(0)
        heading_id = _unique_heading_id(_heading_id_from_text(_strip_html(body)), used_ids)
        return f'<h{level} id="{html_lib.escape(heading_id, quote=True)}"{attrs}>{body}</h{level}>'

    return _HEADING_WITH_ATTRS_RE.sub(replace, fragment)


def _extract_id(attrs: str) -> str:
    match = re.search(r"""\bid\s*=\s*["']([^"']+)["']""", attrs or "", re.IGNORECASE)
    return normalize_text(match.group(1)) if match else ""


def _heading_id_from_text(text: str) -> str:
    candidate = re.sub(r"\s+", "-", normalize_text(text).casefold())
    candidate = re.sub(r"[^a-z0-9\u4e00-\u9fff._-]+", "", candidate, flags=re.IGNORECASE).strip("-._")
    return candidate or "section"


def _unique_heading_id(candidate: str, used_ids: set[str]) -> str:
    heading_id = candidate
    suffix = 2
    while heading_id in used_ids:
        heading_id = f"{candidate}-{suffix}"
        suffix += 1
    used_ids.add(heading_id)
    return heading_id


def _collect_headings(body: str) -> list[dict[str, Any]]:
    parser = _HeadingCollector()
    parser.feed(body or "")
    parser.close()
    return parser.headings


class _HeadingCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.headings: list[dict[str, Any]] = []
        self._current: dict[str, Any] | None = None
        self._chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag not in {"h2", "h3", "h4"}:
            return
        attr_map = {name.lower(): value for name, value in attrs if value is not None}
        self._current = {
            "level": int(tag[1]),
            "id": normalize_text(attr_map.get("id")),
        }
        self._chunks = []

    def handle_endtag(self, tag: str) -> None:
        if self._current is None or tag.lower() not in {"h2", "h3", "h4"}:
            return
        text = normalize_text(html_lib.unescape("".join(self._chunks)))
        self.headings.append({**self._current, "heading": text})
        self._current = None
        self._chunks = []

    def handle_data(self, data: str) -> None:
        if self._current is not None:
            self._chunks.append(data)

    def handle_entityref(self, name: str) -> None:
        if self._current is not None:
            self._chunks.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        if self._current is not None:
            self._chunks.append(f"&#{name};")

NOTE_SECTION_POSITIONS = _NOTE_SECTION_POSITIONS
added_heading_names = _added_heading_names
apply_body_update = _apply_body_update
collect_headings = _collect_headings
delete_heading_section = _delete_heading_section
diff_summary = _diff_summary
format_note_body_html = _format_note_body_html
image_figure_html = _image_figure_html
note_body_child_indent = _note_body_child_indent
note_body_container_indent = _note_body_container_indent
prepare_note_section_update = _prepare_note_section_update
replace_note_html_body = _replace_note_html_body
resolve_media_source_args = _resolve_media_source_args
validate_html_document = _validate_html_document
with_surrounding_newlines = _with_surrounding_newlines
write_note_html_body = _write_note_html_body
