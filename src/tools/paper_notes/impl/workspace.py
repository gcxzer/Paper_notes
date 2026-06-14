from __future__ import annotations

# Workspace-local read helpers inspired by Hermes Agent's file tools: keep reads
# paginated, bounded, and scoped to the active workspace.

import fnmatch
import mimetypes
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from app_infra.formatting import normalize_text
from app_infra.paths import PROJECT_ROOT, is_relative_to
from tools.paper_notes.impl.common import positive_int, tool_error, truthy


DEFAULT_READ_LINES = 500
MAX_READ_LINES = 2_000
DEFAULT_MAX_CHARS = 12_000
MAX_MAX_CHARS = 50_000
DEFAULT_LIST_LIMIT = 100
MAX_LIST_LIMIT = 500
DEFAULT_SEARCH_LIMIT = 50
MAX_SEARCH_LIMIT = 200
MAX_SEARCH_FILE_BYTES = 2_000_000
DEFAULT_IGNORED_SEARCH_DIRS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "node_modules",
}
_CREDENTIAL_REDACTIONS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{6,255}\b"),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{3,255}"),
    re.compile(
        r"(?i)\b((?:authorization|proxy-authorization|x-api-key|api-key|api_key|openai-api-key|"
        r"client-secret|client_secret)\s*[:=]\s*)(?:Bearer\s+)?[^\s,;\"']{1,255}"
    ),
    re.compile(
        r"(?i)\b([A-Za-z0-9_]*(?:API[_-]?KEY|TOKEN|SECRET|PASSWORD)[A-Za-z0-9_]*\s*=\s*)"
        r"[^\s,;\"']{1,255}"
    ),
    re.compile(
        r"(?i)([\"'](?:api[_-]?key|token|secret|password|authorization)[\"']\s*:\s*[\"'])"
        r"([^\"']{1,255})([\"'])"
    ),
)


def read_workspace(args: dict[str, Any]) -> dict[str, Any]:
    action = normalize_text(args.get("action")).lower() or "read"
    if action == "read":
        return read_workspace_file(args)
    if action == "list":
        return list_workspace_path(args)
    if action == "search":
        return search_workspace(args)
    if action == "stat":
        return stat_workspace_path(args)
    return tool_error("invalid_action", "action must be read, list, search, or stat.", action=action)


def read_workspace_file(args: dict[str, Any]) -> dict[str, Any]:
    resolved = _resolve_workspace_path(args.get("path"))
    if "error" in resolved:
        return resolved
    path = resolved["path"]
    if path.is_dir():
        return list_workspace_path({**args, "path": str(path)})
    if not path.is_file():
        return _not_found(path, args.get("path"))

    stat = _safe_stat(path)
    binary = _is_binary_file(path)
    payload: dict[str, Any] = {
        "success": True,
        "action": "read",
        "path": _workspace_relative_path(path),
        "kind": "binary" if binary else "text",
        "mimeType": _mime_type(path),
        "size": stat.st_size if stat is not None else 0,
        "modifiedAt": _modified_at(stat),
    }
    if binary:
        return {
            **payload,
            "content": "",
            "truncated": False,
            "message": "Binary file metadata returned. Text content is not available through read_workspace.",
        }

    offset = positive_int(args.get("offset"), default=1, maximum=1_000_000)
    limit = positive_int(args.get("limit"), default=DEFAULT_READ_LINES, maximum=MAX_READ_LINES)
    max_chars = positive_int(args.get("max_chars"), default=DEFAULT_MAX_CHARS, maximum=MAX_MAX_CHARS)
    read_result = _read_text_lines(path, offset=offset, limit=limit, max_chars=max_chars)
    return {**payload, **read_result}


def list_workspace_path(args: dict[str, Any]) -> dict[str, Any]:
    resolved = _resolve_workspace_path(args.get("path") or ".")
    if "error" in resolved:
        return resolved
    path = resolved["path"]
    if not path.exists():
        return _not_found(path, args.get("path"))
    if path.is_file():
        return {
            "success": True,
            "action": "list",
            "path": _workspace_relative_path(path),
            "entries": [_entry_payload(path)],
            "count": 1,
            "truncated": False,
        }

    limit = positive_int(args.get("limit"), default=DEFAULT_LIST_LIMIT, maximum=MAX_LIST_LIMIT)
    recursive = truthy(args.get("recursive"))
    pattern = normalize_text(args.get("glob") or "*") or "*"
    entries: list[dict[str, Any]] = []
    candidates = path.rglob(pattern) if recursive else path.glob(pattern)
    for candidate in sorted(candidates, key=_sort_key):
        if candidate == path:
            continue
        try:
            resolved_candidate = candidate.resolve()
        except OSError:
            continue
        if not is_relative_to(resolved_candidate, _workspace_root()):
            continue
        entries.append(_entry_payload(resolved_candidate))
        if len(entries) >= limit + 1:
            break
    truncated = len(entries) > limit
    return {
        "success": True,
        "action": "list",
        "path": _workspace_relative_path(path),
        "glob": pattern,
        "recursive": recursive,
        "entries": entries[:limit],
        "count": min(len(entries), limit),
        "truncated": truncated,
    }


def search_workspace(args: dict[str, Any]) -> dict[str, Any]:
    query = normalize_text(args.get("query"))
    if not query:
        return tool_error("query_required", "query is required for workspace search.")
    resolved = _resolve_workspace_path(args.get("path") or ".")
    if "error" in resolved:
        return resolved
    path = resolved["path"]
    if not path.exists():
        return _not_found(path, args.get("path"))

    limit = positive_int(args.get("limit"), default=DEFAULT_SEARCH_LIMIT, maximum=MAX_SEARCH_LIMIT)
    max_chars = positive_int(args.get("max_chars"), default=240, maximum=2_000)
    pattern = normalize_text(args.get("glob") or "*") or "*"
    recursive = args.get("recursive")
    recursive = True if recursive is None else truthy(recursive)
    matches: list[dict[str, Any]] = []
    searched_files = 0
    skipped_files = 0
    for candidate in _search_candidates(path, pattern=pattern, recursive=recursive):
        stat = _safe_stat(candidate)
        if stat is None or stat.st_size > MAX_SEARCH_FILE_BYTES or _is_binary_file(candidate):
            skipped_files += 1
            continue
        searched_files += 1
        file_matches = _search_text_file(
            candidate,
            query=query,
            max_chars=max_chars,
            remaining=limit + 1 - len(matches),
        )
        matches.extend(file_matches)
        if len(matches) >= limit + 1:
            break
    truncated = len(matches) > limit
    return {
        "success": True,
        "action": "search",
        "path": _workspace_relative_path(path),
        "query": query,
        "glob": pattern,
        "recursive": recursive,
        "matches": matches[:limit],
        "count": min(len(matches), limit),
        "truncated": truncated,
        "searchedFiles": searched_files,
        "skippedFiles": skipped_files,
    }


def stat_workspace_path(args: dict[str, Any]) -> dict[str, Any]:
    resolved = _resolve_workspace_path(args.get("path"))
    if "error" in resolved:
        return resolved
    path = resolved["path"]
    if not path.exists():
        return _not_found(path, args.get("path"))
    return {
        "success": True,
        "action": "stat",
        "path": _workspace_relative_path(path),
        "entry": _entry_payload(path),
    }


def _resolve_workspace_path(raw_path: Any) -> dict[str, Any]:
    text = normalize_text(raw_path or ".")
    if text.startswith("file://"):
        parsed = urlparse(text)
        text = unquote(parsed.path or "")
    root = _workspace_root()
    candidate = Path(text).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    try:
        resolved = candidate.resolve(strict=False)
    except OSError as error:
        return tool_error("invalid_path", f"Invalid workspace path: {error}", path=text)
    if not is_relative_to(resolved, root):
        return tool_error(
            "path_outside_workspace",
            "read_workspace can only read files under the current Paper_Notes workspace.",
            path=text,
            workspace=_workspace_relative_path(root),
        )
    return {"path": resolved}


def _workspace_root() -> Path:
    return PROJECT_ROOT.resolve()


def _workspace_relative_path(path: Path) -> str:
    resolved = Path(path).resolve()
    root = _workspace_root()
    if is_relative_to(resolved, root):
        return str(resolved.relative_to(root))
    return str(resolved)


def _not_found(path: Path, requested: Any) -> dict[str, Any]:
    return tool_error(
        "path_not_found",
        f"Workspace path was not found: {normalize_text(requested) or _workspace_relative_path(path)}",
        path=normalize_text(requested) or _workspace_relative_path(path),
        suggestions=_similar_paths(path),
    )


def _similar_paths(path: Path) -> list[str]:
    name = path.name
    if not name:
        return []
    root = _workspace_root()
    matches: list[str] = []
    for candidate in root.rglob(name):
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if is_relative_to(resolved, root):
            matches.append(_workspace_relative_path(resolved))
        if len(matches) >= 5:
            break
    return matches


def _read_text_lines(path: Path, *, offset: int, limit: int, max_chars: int) -> dict[str, Any]:
    content_parts: list[str] = []
    total_lines = 0
    captured_lines = 0
    truncated = False
    redacted = False
    start = max(offset, 1)
    end = start + max(limit, 1) - 1
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line_number, line in enumerate(handle, start=1):
                total_lines = line_number
                if line_number < start:
                    continue
                if line_number > end:
                    truncated = True
                    continue
                next_line, line_redacted = _redact_sensitive_text(line)
                redacted = redacted or line_redacted
                if sum(len(part) for part in content_parts) + len(next_line) > max_chars:
                    remaining = max(max_chars - sum(len(part) for part in content_parts), 0)
                    if remaining:
                        content_parts.append(next_line[:remaining])
                    truncated = True
                    continue
                content_parts.append(next_line)
                captured_lines += 1
    except UnicodeError:
        return {
            "content": "",
            "lineStart": start,
            "lineEnd": start - 1,
            "totalLines": 0,
            "chars": 0,
            "truncated": False,
            "redacted": False,
            "message": "File could not be decoded as text.",
        }
    content = "".join(content_parts)
    return {
        "content": content,
        "lineStart": start,
        "lineEnd": start + max(captured_lines - 1, 0),
        "totalLines": total_lines,
        "chars": len(content),
        "truncated": truncated,
        "redacted": redacted,
    }


def _search_candidates(path: Path, *, pattern: str, recursive: bool) -> list[Path]:
    if path.is_file():
        return [path] if fnmatch.fnmatch(path.name, pattern) else []
    iterator = path.rglob(pattern) if recursive else path.glob(pattern)
    candidates: list[Path] = []
    for candidate in iterator:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if not resolved.is_file() or not is_relative_to(resolved, _workspace_root()):
            continue
        if any(part in DEFAULT_IGNORED_SEARCH_DIRS for part in resolved.relative_to(_workspace_root()).parts[:-1]):
            continue
        candidates.append(resolved)
    return sorted(candidates, key=_workspace_relative_path)


def _search_text_file(path: Path, *, query: str, max_chars: int, remaining: int) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    needle = query.lower()
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line_number, line in enumerate(handle, start=1):
                if needle not in line.lower():
                    continue
                snippet, redacted = _redact_sensitive_text(line.strip())
                if len(snippet) > max_chars:
                    snippet = f"{snippet[:max_chars].rstrip()}..."
                matches.append({
                    "path": _workspace_relative_path(path),
                    "line": line_number,
                    "text": snippet,
                    "redacted": redacted,
                })
                if len(matches) >= remaining:
                    break
    except OSError:
        return matches
    return matches


def _entry_payload(path: Path) -> dict[str, Any]:
    stat = _safe_stat(path)
    return {
        "path": _workspace_relative_path(path),
        "kind": "directory" if path.is_dir() else "file" if path.is_file() else "other",
        "size": stat.st_size if stat is not None else 0,
        "modifiedAt": _modified_at(stat),
        "mimeType": "" if path.is_dir() else _mime_type(path),
    }


def _is_binary_file(path: Path) -> bool:
    if path.is_dir():
        return False
    try:
        sample = path.open("rb").read(4096)
    except OSError:
        return False
    if b"\x00" in sample:
        return True
    mime_type = _mime_type(path)
    if mime_type.startswith("text/") or mime_type in {"application/json", "application/xml"}:
        return False
    return path.suffix.lower() in {
        ".7z",
        ".avif",
        ".bin",
        ".db",
        ".dmg",
        ".gif",
        ".gz",
        ".ico",
        ".jpeg",
        ".jpg",
        ".mov",
        ".mp3",
        ".mp4",
        ".pdf",
        ".png",
        ".pyc",
        ".sqlite",
        ".tif",
        ".tiff",
        ".webp",
        ".zip",
    }


def _mime_type(path: Path) -> str:
    guessed, _encoding = mimetypes.guess_type(str(path))
    return guessed or "application/octet-stream"


def _safe_stat(path: Path):
    try:
        return path.stat()
    except OSError:
        return None


def _modified_at(stat: Any) -> str:
    if stat is None:
        return ""
    return datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()


def _sort_key(path: Path) -> tuple[int, str]:
    return (0 if path.is_dir() else 1, _workspace_relative_path(path).lower())


def _redact_sensitive_text(text: str) -> tuple[str, bool]:
    redacted = str(text)
    changed = False
    for pattern in _CREDENTIAL_REDACTIONS:
        def _replace(match: re.Match[str]) -> str:
            nonlocal changed
            changed = True
            if match.lastindex and match.lastindex >= 1:
                prefix = match.group(1) or ""
                suffix = match.group(match.lastindex) if match.lastindex >= 3 else ""
                return f"{prefix}[REDACTED]{suffix}"
            if match.group(0).lower().startswith("bearer "):
                return "Bearer [REDACTED]"
            return "[REDACTED]"

        redacted = pattern.sub(_replace, redacted)
    return redacted, changed
