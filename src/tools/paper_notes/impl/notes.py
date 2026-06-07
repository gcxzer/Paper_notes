from __future__ import annotations

# Note library, HTML section, metadata, context, and review operations.

import html as html_lib
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from tools.paper_notes.impl.formatting import normalize_text
from tools.paper_notes.impl.paths import HTML_DIR, PROJECT_ROOT, is_relative_to
from tools.paper_notes.impl.storage import atomic_write_text
from tools.paper_notes.impl.library_store import find_note, normalize_tags, read_library, write_library
from tools.paper_notes.impl.library_annotations import read_annotations as read_note_annotations
from tools.paper_notes.impl.artifacts import _artifact_to_payload, _resolve_image_artifact_payload
from tools.paper_notes.impl.common import (
    positive_int,
    resolve_note,
    safe_served_src,
    safe_src,
    sanitize_html_fragment,
    tool_error,
)
from tools.paper_notes.impl.paper import search_paper_text

_NOTE_BODY_RE = re.compile(
    r"(?is)(<(?P<tag>section|div|main)\b(?=[^>]*\bclass=[\"'][^\"']*\bnote-body\b[^\"']*[\"'])[^>]*>)"
    r"(?P<body>.*?)"
    r"(</(?P=tag)>)"
)
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


def _validate_html_document(document: str) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    match = _note_body_match(document)
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
def _note_score(note: dict[str, Any], query: str) -> int:
    score = 0
    title = str(note.get("title") or "").lower()
    summary = str(note.get("summary") or "").lower()
    venue = str(note.get("venue") or "").lower()
    date = str(note.get("date") or "").lower()
    tags = " ".join(str(tag).lower() for tag in note.get("tags", []) if tag)
    haystack = {
        "title": title,
        "tags": tags,
        "summary": summary,
        "venue": venue,
        "date": date,
    }

    if query in title:
        score += 10
    if query in tags:
        score += 6
    if query in summary:
        score += 4
    if query in venue:
        score += 2
    if query in date:
        score += 1
    terms = [
        term for term in re.findall(r"[\w\u4e00-\u9fff]+", query.casefold())
        if term and len(term) > 1
    ]
    for term in terms:
        if term in title:
            score += 5
        if term in tags:
            score += 3
        if term in summary:
            score += 2
        if term in venue or term in date:
            score += 1
    if terms and all(any(term in value for value in haystack.values()) for term in terms):
        score += 2
    return score
def _note_summary(note: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": note.get("id", ""),
        "title": note.get("title", ""),
        "summary": note.get("summary", ""),
        "venue": note.get("venue", ""),
        "date": note.get("date", ""),
        "tags": note.get("tags", []),
        "categoryId": note.get("categoryId", ""),
        "href": note.get("href", ""),
        "htmlHref": note.get("htmlHref", ""),
    }
def _note_detail(note: dict[str, Any], library: dict[str, Any] | None = None) -> dict[str, Any]:
    collection = _collection_metadata(library, note.get("categoryId", "")) if library else {}
    return {
        "id": note.get("id", ""),
        "title": note.get("title", ""),
        "summary": note.get("summary", ""),
        "venue": note.get("venue", ""),
        "date": note.get("date", ""),
        "tags": note.get("tags", []),
        "categoryId": note.get("categoryId", ""),
        **collection,
        "href": note.get("href", ""),
        "htmlHref": note.get("htmlHref", ""),
        "pdfStorageKey": note.get("pdfStorageKey", ""),
    }
def _collection_metadata(library: dict[str, Any] | None, category_id: Any) -> dict[str, str]:
    category = _category_by_id(library, normalize_text(category_id))
    if not category:
        return {"collectionName": "", "collectionPath": ""}
    return {
        "collectionName": normalize_text(category.get("name")),
        "collectionPath": _collection_path(library, normalize_text(category.get("id"))),
    }
def _resolve_collection_id(library: dict[str, Any], value: str) -> str:
    target = _normalize_collection_lookup(value)
    if not target:
        return ""
    for category in _leaf_categories(library):
        if normalize_text(category.get("id")) == value:
            return normalize_text(category.get("id"))
    exact_matches = [
        normalize_text(category.get("id"))
        for category in _leaf_categories(library)
        if _normalize_collection_lookup(category.get("name")) == target
        or _normalize_collection_lookup(_collection_path(library, category.get("id"))) == target
    ]
    return exact_matches[0] if len(exact_matches) == 1 else ""
def _collection_path(library: dict[str, Any] | None, category_id: Any) -> str:
    category = _category_by_id(library, normalize_text(category_id))
    if not category:
        return ""
    parent_id = normalize_text(category.get("parentId"))
    if not parent_id:
        return normalize_text(category.get("name"))
    parent = _category_by_id(library, parent_id)
    return f"{normalize_text(parent.get('name'))} / {normalize_text(category.get('name'))}" if parent else normalize_text(category.get("name"))
def _category_by_id(library: dict[str, Any] | None, category_id: str) -> dict[str, Any] | None:
    if not library or not category_id:
        return None
    return next((category for category in library.get("categories", []) if category.get("id") == category_id), None)
def _leaf_categories(library: dict[str, Any]) -> list[dict[str, Any]]:
    categories = [category for category in library.get("categories", []) if isinstance(category, dict)]
    parent_ids = {normalize_text(category.get("parentId")) for category in categories if normalize_text(category.get("parentId"))}
    return [category for category in categories if normalize_text(category.get("id")) not in parent_ids]
def _normalize_collection_lookup(value: Any) -> str:
    return re.sub(r"\s*/\s*", "/", normalize_text(value).lower())
def _note_html_path(note: dict[str, Any], *, html_dir: Path | None = None) -> Path | None:
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
def _note_body_match(document: str) -> re.Match[str] | None:
    return _NOTE_BODY_RE.search(document)
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

def search_library(args: dict[str, Any], *, library_path: Path | None = None) -> dict[str, Any]:
    query = normalize_text(args.get("query")).lower()
    limit = positive_int(args.get("limit"), default=10, maximum=25)
    library = read_library(library_path) if library_path is not None else read_library()
    notes_source = [note for note in library.get("notes", []) if isinstance(note, dict)]
    if not query or query in {"*", "all"}:
        sorted_notes = sorted(
            notes_source,
            key=lambda note: (
                str(note.get("date") or ""),
                str(note.get("title") or "").lower(),
            ),
            reverse=True,
        )
        notes = [_note_summary(note) for note in sorted_notes[:limit]]
        return {
            "query": query,
            "mode": "list",
            "total": len(notes_source),
            "count": len(notes),
            "notes": notes,
        }

    scored_notes = []
    for note in notes_source:
        score = _note_score(note, query)
        if score > 0:
            scored_notes.append((score, note))

    scored_notes.sort(key=lambda item: (-item[0], str(item[1].get("title") or "").lower()))
    notes = [_note_summary(note) for _, note in scored_notes[:limit]]
    return {
        "query": query,
        "count": len(notes),
        "notes": notes,
    }


def get_note(args: dict[str, Any], *, library_path: Path | None = None) -> dict[str, Any]:
    note_id = normalize_text(args.get("note_id") or args.get("id"))
    if not note_id:
        return {"error": "note_id is required"}

    library = read_library(library_path) if library_path is not None else read_library()
    note = find_note(library, note_id)
    if note is None:
        return {"error": f"Note not found: {note_id}"}
    return {"note": _note_detail(note, library)}


def read_annotations_tool(args: dict[str, Any], *, annotations_dir: Path | None = None) -> dict[str, Any]:
    note_id = normalize_text(args.get("note_id") or args.get("id"))
    if not note_id:
        return {"error": "note_id is required"}

    payload = (
        read_note_annotations(note_id, annotations_dir)
        if annotations_dir is not None
        else read_note_annotations(note_id)
    )
    if payload is None:
        return {"error": "note_id is required"}
    annotations = payload.get("annotations") if isinstance(payload, dict) else []
    return {
        "note_id": note_id,
        "annotations": annotations if isinstance(annotations, list) else [],
    }


def read_note_html(
    args: dict[str, Any],
    *,
    library_path: Path | None = None,
    html_dir: Path | None = None,
) -> dict[str, Any]:
    note_result = resolve_note(args, library_path=library_path)
    if "error" in note_result:
        return note_result
    note = note_result["note"]
    html_path = _note_html_path(note, html_dir=html_dir)
    if html_path is None:
        return tool_error("note_html_missing", "Note has no local HTML path.", note_id=note["id"])
    try:
        document = html_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return tool_error("note_html_not_found", f"HTML note file was not found: {html_path.name}", note_id=note["id"])

    mode = normalize_text(args.get("mode") or "body").lower()
    if mode not in {"body", "full"}:
        return tool_error("invalid_mode", "mode must be body or full.", note_id=note["id"])
    if mode == "body":
        match = _note_body_match(document)
        if match is None:
            return tool_error("note_body_missing", "HTML note does not contain a .note-body element.", note_id=note["id"])
        content = match.group("body").strip()
    else:
        content = document
    return {
        "success": True,
        "note_id": note["id"],
        "mode": mode,
        "html": content,
        "chars": len(content),
    }


def list_note_sections(
    args: dict[str, Any],
    *,
    library_path: Path | None = None,
    html_dir: Path | None = None,
) -> dict[str, Any]:
    payload = read_note_html({**args, "mode": "body"}, library_path=library_path, html_dir=html_dir)
    if not payload.get("success"):
        return payload
    sections = _collect_headings(str(payload.get("html") or ""))
    return {
        "success": True,
        "note_id": payload["note_id"],
        "count": len(sections),
        "sections": sections,
    }

def build_note_context(
    args: dict[str, Any],
    *,
    library_path: Path | None = None,
    annotations_dir: Path | None = None,
    html_dir: Path | None = None,
    papers_dir: Path | None = None,
    paper_text_cache_dir: Path | None = None,
) -> dict[str, Any]:
    note_result = get_note(args, library_path=library_path)
    if "error" in note_result:
        return note_result
    note = note_result["note"]
    sections_payload = list_note_sections(args, library_path=library_path, html_dir=html_dir)
    annotations_payload = read_annotations_tool(args, annotations_dir=annotations_dir)
    query = normalize_text(args.get("query"))
    paper_matches: list[dict[str, Any]] = []
    if query:
        max_matches = positive_int(args.get("max_paper_matches"), default=5, maximum=8)
        paper_payload = search_paper_text(
            {**args, "query": query, "limit": max_matches},
            library_path=library_path,
            papers_dir=papers_dir,
            paper_text_cache_dir=paper_text_cache_dir,
        )
        if paper_payload.get("success"):
            paper_matches = paper_payload.get("matches", [])
    return {
        "success": True,
        "note_id": note["id"],
        "note": note,
        "sections": sections_payload.get("sections", []) if sections_payload.get("success") else [],
        "annotations": annotations_payload.get("annotations", []) if not annotations_payload.get("error") else [],
        "paper_matches": paper_matches,
    }


def validate_note_html(
    args: dict[str, Any],
    *,
    library_path: Path | None = None,
    html_dir: Path | None = None,
) -> dict[str, Any]:
    note_result = resolve_note(args, library_path=library_path)
    if "error" in note_result:
        return note_result
    note = note_result["note"]
    html_path = _note_html_path(note, html_dir=html_dir)
    if html_path is None:
        return tool_error("note_html_missing", "Note has no local HTML path.", note_id=note["id"])
    try:
        document = html_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return tool_error("note_html_not_found", f"HTML note file was not found: {html_path.name}", note_id=note["id"])
    issues = _validate_html_document(document)
    match = _note_body_match(document)
    body = match.group("body") if match else ""
    sections = _collect_headings(body)
    return {
        "success": True,
        "valid": not issues,
        "note_id": note["id"],
        "issues": issues,
        "section_count": len(sections),
        "body_chars": len(body),
        "path": str(html_path),
    }


def preview_note_diff(
    args: dict[str, Any],
    *,
    library_path: Path | None = None,
    html_dir: Path | None = None,
) -> dict[str, Any]:
    note_result = resolve_note(args, library_path=library_path)
    if "error" in note_result:
        return note_result
    note = note_result["note"]
    html_path = _note_html_path(note, html_dir=html_dir)
    if html_path is None:
        return tool_error("note_html_missing", "Note has no local HTML path.", note_id=note["id"])
    try:
        document = html_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return tool_error("note_html_not_found", f"HTML note file was not found: {html_path.name}", note_id=note["id"])
    match = _note_body_match(document)
    if match is None:
        return tool_error("note_body_missing", "HTML note does not contain a .note-body element.", note_id=note["id"])
    heading = normalize_text(args.get("heading"))
    raw_html = str(args.get("html") or "")
    position = normalize_text(args.get("position") or "append").lower()
    if position not in {"append", "prepend", "after_heading", "replace_heading"}:
        return tool_error("invalid_position", "position must be append, prepend, after_heading, or replace_heading.", note_id=note["id"])
    current_body = match.group("body").strip()
    target_exists = _find_heading_section(current_body, heading) is not None
    fragment = _section_fragment(
        heading=heading,
        raw_html=raw_html,
        heading_level=_heading_level_for(current_body, heading),
        allow_heading_only=position == "replace_heading" and target_exists,
    )
    if not fragment:
        return tool_error("empty_html", "html must contain safe note content.", note_id=note["id"])
    next_body, changed = _apply_body_update(current_body, fragment=fragment, heading=heading, position=position)
    if not changed:
        return tool_error("heading_not_found", f"Could not find heading: {heading}", note_id=note["id"])
    next_body = _format_note_body_html(next_body, base_indent=_note_body_child_indent(document, match))
    before_headings = _collect_headings(current_body)
    after_headings = _collect_headings(next_body)
    return {
        "success": True,
        "changed": next_body != current_body,
        "note_id": note["id"],
        "heading": heading,
        "position": position,
        "path": str(html_path),
        "before": {
            "section_count": len(before_headings),
            "body_chars": len(current_body),
        },
        "after": {
            "section_count": len(after_headings),
            "body_chars": len(next_body),
        },
        "added_headings": _added_heading_names(before_headings, after_headings),
        "summary": _diff_summary(current_body, next_body),
        "snapshot_id": "",
    }

def write_note_section(
    args: dict[str, Any],
    *,
    library_path: Path | None = None,
    html_dir: Path | None = None,
    media_store: Any | None = None,
) -> dict[str, Any]:
    args, media_error = _resolve_media_source_args(args, media_store)
    if media_error:
        return media_error
    note_result = resolve_note(args, library_path=library_path)
    if "error" in note_result:
        return note_result
    note = note_result["note"]
    html_path = _note_html_path(note, html_dir=html_dir)
    if html_path is None:
        return tool_error("note_html_missing", "Note has no local HTML path.", note_id=note["id"])
    try:
        document = html_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return tool_error("note_html_not_found", f"HTML note file was not found: {html_path.name}", note_id=note["id"])

    match = _note_body_match(document)
    if match is None:
        return tool_error("note_body_missing", "HTML note does not contain a .note-body element.", note_id=note["id"])

    heading = normalize_text(args.get("heading"))
    raw_html = str(args.get("html") or "")
    position = normalize_text(args.get("position") or "append").lower()
    if position not in {"append", "prepend", "after_heading", "replace_heading"}:
        return tool_error("invalid_position", "position must be append, prepend, after_heading, or replace_heading.", note_id=note["id"])

    current_body = match.group("body").strip()
    target_exists = _find_heading_section(current_body, heading) is not None
    fragment = _section_fragment(
        heading=heading,
        raw_html=raw_html,
        heading_level=_heading_level_for(current_body, heading),
        allow_heading_only=position == "replace_heading" and target_exists,
    )
    if not fragment:
        return tool_error("empty_html", "html must contain safe note content.", note_id=note["id"])

    before_headings = _collect_headings(current_body)
    before = {
        "section_count": len(before_headings),
        "body_chars": len(current_body),
    }
    next_body, changed = _apply_body_update(current_body, fragment=fragment, heading=heading, position=position)
    if not changed:
        return tool_error("heading_not_found", f"Could not find heading: {heading}", note_id=note["id"])
    next_body = _format_note_body_html(next_body, base_indent=_note_body_child_indent(document, match))
    after_headings = _collect_headings(next_body)

    next_document = (
        document[:match.start("body")]
        + _with_surrounding_newlines(next_body, trailing_indent=_note_body_container_indent(document, match))
        + document[match.end("body"):]
    )
    atomic_write_text(html_path, next_document)
    return {
        "success": True,
        "changed": next_document != document,
        "note_id": note["id"],
        "heading": heading,
        "position": position,
        "added_headings": _added_heading_names(before_headings, after_headings),
        "message": f"Updated HTML note section using {position}.",
        "section_count": len(after_headings),
        "html_chars": len(next_document),
        "before": before,
        "after": {
            "section_count": len(after_headings),
            "body_chars": len(next_body),
        },
    }


def append_note_section(
    args: dict[str, Any],
    *,
    library_path: Path | None = None,
    html_dir: Path | None = None,
    media_store: Any | None = None,
) -> dict[str, Any]:
    return write_note_section({**args, "position": "append"}, library_path=library_path, html_dir=html_dir, media_store=media_store)


def replace_note_section(
    args: dict[str, Any],
    *,
    library_path: Path | None = None,
    html_dir: Path | None = None,
    media_store: Any | None = None,
) -> dict[str, Any]:
    return write_note_section({**args, "position": "replace_heading"}, library_path=library_path, html_dir=html_dir, media_store=media_store)


def delete_note_section(
    args: dict[str, Any],
    *,
    library_path: Path | None = None,
    html_dir: Path | None = None,
) -> dict[str, Any]:
    note_result = resolve_note(args, library_path=library_path)
    if "error" in note_result:
        return note_result
    note = note_result["note"]
    html_path = _note_html_path(note, html_dir=html_dir)
    if html_path is None:
        return tool_error("note_html_missing", "Note has no local HTML path.", note_id=note["id"])
    heading = normalize_text(args.get("heading"))
    if not heading:
        return tool_error("heading_required", "heading is required.", note_id=note["id"])
    try:
        document = html_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return tool_error("note_html_not_found", f"HTML note file was not found: {html_path.name}", note_id=note["id"])

    match = _note_body_match(document)
    if match is None:
        return tool_error("note_body_missing", "HTML note does not contain a .note-body element.", note_id=note["id"])

    current_body = match.group("body").strip()
    before = {
        "section_count": len(_collect_headings(current_body)),
        "body_chars": len(current_body),
    }
    next_body, changed = _delete_heading_section(current_body, heading)
    if not changed:
        return tool_error("heading_not_found", f"Could not find heading: {heading}", note_id=note["id"])
    next_body = _format_note_body_html(next_body, base_indent=_note_body_child_indent(document, match))

    next_document = (
        document[:match.start("body")]
        + _with_surrounding_newlines(next_body, trailing_indent=_note_body_container_indent(document, match))
        + document[match.end("body"):]
    )
    atomic_write_text(html_path, next_document)
    return {
        "success": True,
        "changed": next_document != document,
        "note_id": note["id"],
        "heading": heading,
        "message": "Deleted HTML note section.",
        "section_count": len(_collect_headings(next_body)),
        "html_chars": len(next_document),
        "before": before,
        "after": {
            "section_count": len(_collect_headings(next_body)),
            "body_chars": len(next_body),
        },
    }


def insert_note_image(
    args: dict[str, Any],
    *,
    library_path: Path | None = None,
    html_dir: Path | None = None,
    media_store: Any | None = None,
) -> dict[str, Any]:
    note_result = resolve_note(args, library_path=library_path)
    if "error" in note_result:
        return note_result
    note = note_result["note"]
    html_path = _note_html_path(note, html_dir=html_dir)
    if html_path is None:
        return tool_error("note_html_missing", "Note has no local HTML path.", note_id=note["id"])
    if media_store is None:
        return tool_error("media_store_unavailable", "Media store is not available.", note_id=note["id"])

    artifact_ref = normalize_text(args.get("artifact_id"))
    if not artifact_ref:
        return tool_error("artifact_id_required", "artifact_id is required.", note_id=note["id"])
    artifact = _resolve_image_artifact_payload(media_store, artifact_ref)
    if not artifact or not normalize_text(artifact.get("url")):
        return tool_error("image_artifact_not_found", f"Image artifact was not found: {artifact_ref}", note_id=note["id"])
    if normalize_text(artifact.get("kind") or "image") != "image":
        return tool_error("image_artifact_required", "insert_image requires an image artifact.", note_id=note["id"], artifact_id=artifact_ref)
    artifact_id = normalize_text(artifact.get("id") or artifact_ref)

    try:
        document = html_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return tool_error("note_html_not_found", f"HTML note file was not found: {html_path.name}", note_id=note["id"])

    match = _note_body_match(document)
    if match is None:
        return tool_error("note_body_missing", "HTML note does not contain a .note-body element.", note_id=note["id"])

    heading = normalize_text(args.get("heading"))
    position = normalize_text(args.get("position") or ("after_heading" if heading else "append")).lower()
    if position not in {"append", "prepend", "after_heading", "replace_heading"}:
        return tool_error("invalid_position", "position must be append, prepend, after_heading, or replace_heading.", note_id=note["id"])

    figure_html = _image_figure_html(
        artifact=artifact,
        caption=normalize_text(args.get("caption")),
        alt=normalize_text(args.get("alt")),
    )
    current_body = match.group("body").strip()
    before = {
        "section_count": len(_collect_headings(current_body)),
        "body_chars": len(current_body),
    }
    next_body, changed = _apply_body_update(
        current_body,
        fragment=figure_html,
        heading=heading,
        position=position,
    )
    if not changed:
        return tool_error("heading_not_found", f"Could not find heading: {heading}", note_id=note["id"])
    next_body = _format_note_body_html(next_body, base_indent=_note_body_child_indent(document, match))

    next_document = (
        document[:match.start("body")]
        + _with_surrounding_newlines(next_body, trailing_indent=_note_body_container_indent(document, match))
        + document[match.end("body"):]
    )
    atomic_write_text(html_path, next_document)
    return {
        "success": True,
        "changed": next_document != document,
        "note_id": note["id"],
        "heading": heading,
        "position": position,
        "artifact_id": artifact_id,
        "message": "Inserted image into HTML note.",
        "image": artifact,
        "before": before,
        "after": {
            "section_count": len(_collect_headings(next_body)),
            "body_chars": len(next_body),
        },
    }


def update_note_metadata(args: dict[str, Any], *, library_path: Path | None = None) -> dict[str, Any]:
    note_id = normalize_text(args.get("note_id") or args.get("id"))
    if not note_id:
        return tool_error("note_id_required", "note_id is required")

    allowed_input_keys = {
        "note_id",
        "id",
        "summary",
        "tags",
        "venue",
        "date",
        "category_id",
        "categoryId",
        "collection",
        "collection_name",
        "collectionName",
        "collection_path",
        "collectionPath",
    }
    unknown = sorted(key for key in args if key not in allowed_input_keys)
    if unknown:
        return tool_error("unknown_metadata_fields", f"Unsupported metadata fields: {', '.join(unknown)}", note_id=note_id)

    path = library_path if library_path is not None else None
    library = read_library(path) if path is not None else read_library()
    note = find_note(library, note_id)
    if note is None:
        return tool_error("note_not_found", f"Note not found: {note_id}", note_id=note_id)

    before = _note_detail(note, library)
    updates: dict[str, Any] = {}
    if "summary" in args:
        updates["summary"] = normalize_text(args.get("summary"))
    if "tags" in args:
        raw_tags = args.get("tags")
        if isinstance(raw_tags, str):
            raw_tags = [tag for tag in re.split(r"[,，]", raw_tags)]
        updates["tags"] = normalize_tags(raw_tags)
    if "venue" in args:
        updates["venue"] = normalize_text(args.get("venue"))
    if "date" in args:
        updates["date"] = normalize_text(args.get("date"))
    if "category_id" in args or "categoryId" in args:
        updates["categoryId"] = normalize_text(args.get("category_id") or args.get("categoryId"))
    collection_value = normalize_text(
        args.get("collection")
        or args.get("collection_name")
        or args.get("collectionName")
        or args.get("collection_path")
        or args.get("collectionPath")
    )
    if collection_value:
        resolved_category_id = _resolve_collection_id(library, collection_value)
        if not resolved_category_id:
            return tool_error("collection_not_found", f"Collection not found: {collection_value}", note_id=note_id)
        updates["categoryId"] = resolved_category_id

    if not updates:
        return tool_error("no_metadata_updates", "Provide at least one metadata field to update.", note_id=note_id)

    note.update(updates)
    saved = write_library(library, path) if path is not None else write_library(library)
    after_note = find_note(saved, note_id) or note
    return {
        "success": True,
        "changed": before != _note_detail(after_note, saved),
        "note_id": note_id,
        "message": "Updated note metadata.",
        "before": before,
        "after": _note_detail(after_note, saved),
    }

__all__ = [name for name in globals() if not name.startswith("__")]
