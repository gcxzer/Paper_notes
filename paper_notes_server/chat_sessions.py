from __future__ import annotations

import copy
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import config
from .storage import normalize_text


SESSION_ID_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9-_]{32,255}$")
DEFAULT_SESSION_TITLE = "New chat"
WORKSPACE_NOTE_ID = "workspace"


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def normalize_note_id(value: object) -> str:
    return normalize_text(value) or WORKSPACE_NOTE_ID


def normalize_session_id(value: object) -> str:
    session_id = normalize_text(value)
    return session_id if SESSION_ID_PATTERN.match(session_id) else ""


def new_session_id() -> str:
    return str(uuid.uuid4())


def session_file_timestamp(value: object) -> str:
    timestamp = normalize_text(value) or now_iso()
    timestamp = timestamp.replace("+00:00", "Z").replace(":", "-").replace(".", "-")
    timestamp = re.sub(r"[^0-9A-Za-zTZ-]+", "-", timestamp).strip("-")
    return timestamp or now_iso().replace(":", "-")


def session_file_name(session: dict[str, Any]) -> str:
    return f"session-{session_file_timestamp(session.get('createdAt'))}-{session['id']}.jsonl"


def session_jsonl_paths() -> list[Path]:
    if not config.CHAT_SESSIONS_DIR.exists():
        return []
    return sorted(config.CHAT_SESSIONS_DIR.glob("*.jsonl"))


def session_header(session: dict[str, Any]) -> dict[str, Any]:
    header = {
        "type": "session",
        "id": session["id"],
        "noteId": session["noteId"],
        "title": session["title"],
        "createdAt": session["createdAt"],
        "updatedAt": session["updatedAt"],
        "agentSessionId": session["agentSessionId"],
    }
    if session.get("trashedAt"):
        header["trashedAt"] = session["trashedAt"]
    return header


def session_update(session: dict[str, Any]) -> dict[str, Any]:
    update = {
        "type": "session_update",
        "title": session["title"],
        "updatedAt": session["updatedAt"],
    }
    if "trashedAt" in session:
        update["trashedAt"] = session.get("trashedAt") or ""
    return update


def message_line(message: dict[str, Any]) -> dict[str, Any]:
    line = {
        "type": "message",
        "id": message["id"],
        "role": message["role"],
        "text": message["text"],
        "createdAt": message["createdAt"],
        "error": bool(message.get("error")),
    }
    if message.get("sources"):
        line["sources"] = message["sources"]
    if message.get("noteEdit"):
        line["noteEdit"] = message["noteEdit"]
    return line


def write_jsonl_lines(path: Path, lines: list[dict[str, Any]], append: bool = False) -> None:
    config.CHAT_SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    mode = "a" if append else "w"
    with path.open(mode, encoding="utf-8") as handle:
        for line in lines:
            handle.write(f"{json.dumps(line, ensure_ascii=False, separators=(',', ':'))}\n")


def read_chat_session_file(path: Path) -> dict[str, Any] | None:
    metadata: dict[str, Any] = {}
    messages: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return None

    for line in lines:
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(entry, dict):
            continue
        entry_type = normalize_text(entry.get("type"))
        if entry_type in {"session", "session_update"}:
            metadata.update({key: value for key, value in entry.items() if key not in {"type", "messages"}})
        elif entry_type == "message" or normalize_text(entry.get("role")):
            messages.append(sanitize_chat_message(entry))

    if not metadata and not messages:
        return None
    metadata["messages"] = messages
    return sanitize_chat_session(metadata)


def write_chat_session_file(session: dict[str, Any], path: Path | None = None) -> dict[str, Any]:
    sanitized = sanitize_chat_session(session)
    target = path or config.CHAT_SESSIONS_DIR / session_file_name(sanitized)
    lines = [session_header(sanitized), *[message_line(message) for message in sanitized["messages"]]]
    write_jsonl_lines(target, lines)
    return copy.deepcopy(sanitized)


def read_legacy_chat_session_store() -> dict[str, Any]:
    try:
        raw = json.loads(config.LEGACY_CHAT_SESSIONS_PATH.read_text(encoding="utf-8"))
    except Exception:
        raw = {}
    sessions = raw.get("sessions") if isinstance(raw, dict) and isinstance(raw.get("sessions"), list) else []
    return {"sessions": [sanitize_chat_session(session) for session in sessions if isinstance(session, dict)]}


def migrate_legacy_chat_sessions() -> None:
    if not config.LEGACY_CHAT_SESSIONS_PATH.exists():
        return

    legacy_text = config.LEGACY_CHAT_SESSIONS_PATH.read_text(encoding="utf-8")
    legacy_store = read_legacy_chat_session_store()
    if not legacy_store["sessions"]:
        return

    existing_ids = {
        session["id"]
        for session in (read_chat_session_file(path) for path in session_jsonl_paths())
        if session
    }
    for session in legacy_store["sessions"]:
        if session["id"] not in existing_ids:
            write_chat_session_file(session)
            existing_ids.add(session["id"])

    backup_path = config.LEGACY_CHAT_SESSIONS_PATH.with_suffix(".legacy.json")
    if not backup_path.exists():
        backup_path.write_text(legacy_text, encoding="utf-8")
    config.LEGACY_CHAT_SESSIONS_PATH.write_text(f"{json.dumps({'sessions': []}, ensure_ascii=False, indent=2)}\n", encoding="utf-8")


def read_chat_session_entries() -> list[dict[str, Any]]:
    migrate_legacy_chat_sessions()
    entries: list[dict[str, Any]] = []
    for path in session_jsonl_paths():
        session = read_chat_session_file(path)
        if session:
            entries.append({"path": path, "session": session})
    return entries


def find_chat_session_entry(session_id: object) -> dict[str, Any] | None:
    target_session_id = normalize_session_id(session_id)
    if not target_session_id:
        return None
    return next((entry for entry in read_chat_session_entries() if entry["session"].get("id") == target_session_id), None)


def read_chat_session_store() -> dict[str, Any]:
    return {"sessions": [entry["session"] for entry in read_chat_session_entries()]}


def write_chat_session_store(store: dict[str, Any]) -> dict[str, Any]:
    sanitized = {
        "sessions": [
            sanitize_chat_session(session)
            for session in (store.get("sessions") if isinstance(store.get("sessions"), list) else [])
            if isinstance(session, dict)
        ]
    }
    for session in sanitized["sessions"]:
        write_chat_session_file(session)
    return sanitized


def sanitize_chat_message(raw_message: object) -> dict[str, Any]:
    raw = raw_message if isinstance(raw_message, dict) else {}
    role = normalize_text(raw.get("role")).lower()
    if role not in {"user", "assistant", "system"}:
        role = "assistant"
    created_at = normalize_text(raw.get("createdAt")) or now_iso()
    return {
        "id": normalize_session_id(raw.get("id")) or new_session_id(),
        "role": role,
        "text": normalize_text(raw.get("text")),
        "createdAt": created_at,
        "error": bool(raw.get("error")),
        "sources": sanitize_chat_sources(raw.get("sources")),
        "noteEdit": sanitize_note_edit(raw.get("noteEdit")),
    }


def sanitize_note_edit(raw_edit: object) -> dict[str, Any] | None:
    if not isinstance(raw_edit, dict):
        return None
    note_id = normalize_text(raw_edit.get("noteId"))
    replacement_html = normalize_text(raw_edit.get("replacementHtml"))
    if not note_id or not replacement_html:
        return None
    return {
        "id": normalize_text(raw_edit.get("id")) or f"note-edit-{new_session_id()}",
        "noteId": note_id,
        "summary": normalize_text(raw_edit.get("summary")) or "Prepared a note edit draft.",
        "replacementHtml": replacement_html,
        "applied": bool(raw_edit.get("applied")),
    }


def sanitize_chat_sources(raw_sources: object) -> list[dict[str, Any]]:
    if not isinstance(raw_sources, list):
        return []
    sources: list[dict[str, Any]] = []
    for raw_source in raw_sources[:12]:
        if isinstance(raw_source, str):
            source = {"uri": normalize_text(raw_source)}
        elif isinstance(raw_source, dict):
            source = raw_source
        else:
            continue
        uri = normalize_text(source.get("uri"))
        label = normalize_text(source.get("label"))
        if not uri and not label:
            continue
        page = source.get("page")
        try:
            page = int(float(str(page))) if page is not None and page != "" else None
        except (TypeError, ValueError):
            page = None
        sources.append(
            {
                "type": normalize_text(source.get("type")) or "source",
                "label": label,
                "uri": uri,
                "s3Key": normalize_text(source.get("s3Key")),
                "noteId": normalize_text(source.get("noteId")),
                "page": page if page and page > 0 else None,
                "excerpt": normalize_text(source.get("excerpt")),
            }
        )
    return sources


def sanitize_chat_session(raw_session: object) -> dict[str, Any]:
    raw = raw_session if isinstance(raw_session, dict) else {}
    session_id = normalize_session_id(raw.get("id")) or new_session_id()
    created_at = normalize_text(raw.get("createdAt")) or now_iso()
    updated_at = normalize_text(raw.get("updatedAt")) or created_at
    messages = [
        sanitize_chat_message(message)
        for message in (raw.get("messages") if isinstance(raw.get("messages"), list) else [])
        if isinstance(message, dict)
    ]
    return {
        "id": session_id,
        "noteId": normalize_note_id(raw.get("noteId")),
        "title": normalize_text(raw.get("title")) or DEFAULT_SESSION_TITLE,
        "createdAt": created_at,
        "updatedAt": updated_at,
        "trashedAt": normalize_text(raw.get("trashedAt")),
        "messages": messages,
        "agentSessionId": normalize_session_id(raw.get("agentSessionId")) or session_id,
    }


def chat_session_summary(session: dict[str, Any]) -> dict[str, Any]:
    messages = session.get("messages") if isinstance(session.get("messages"), list) else []
    last_message = messages[-1] if messages else {}
    return {
        "id": session["id"],
        "noteId": session["noteId"],
        "title": session["title"],
        "createdAt": session["createdAt"],
        "updatedAt": session["updatedAt"],
        "trashedAt": normalize_text(session.get("trashedAt")),
        "messageCount": len(messages),
        "lastMessagePreview": normalize_text(last_message.get("text"))[:120] if isinstance(last_message, dict) else "",
    }


def is_chat_session_trashed(session: dict[str, Any]) -> bool:
    return bool(normalize_text(session.get("trashedAt")))


def list_chat_sessions(note_id: object, trashed: bool = False) -> list[dict[str, Any]]:
    target_note_id = normalize_note_id(note_id)
    store = read_chat_session_store()
    sessions = [
        session
        for session in store["sessions"]
        if session.get("noteId") == target_note_id and is_chat_session_trashed(session) == trashed
    ]
    sessions.sort(key=lambda session: normalize_text(session.get("updatedAt")), reverse=True)
    return [chat_session_summary(session) for session in sessions]


def get_chat_session(session_id: object) -> dict[str, Any] | None:
    entry = find_chat_session_entry(session_id)
    return copy.deepcopy(entry["session"]) if entry else None


def get_chat_session_jsonl_path(session_id: object) -> Path | None:
    entry = find_chat_session_entry(session_id)
    path = entry["path"] if entry else None
    return path if path and path.is_file() else None


def create_chat_session(note_id: object, title: object = "", session_id: object = "") -> dict[str, Any]:
    store = read_chat_session_store()
    requested_session_id = normalize_session_id(session_id)
    existing_ids = {session.get("id") for session in store["sessions"]}
    next_session_id = requested_session_id if requested_session_id and requested_session_id not in existing_ids else new_session_id()
    timestamp = now_iso()
    session = {
        "id": next_session_id,
        "noteId": normalize_note_id(note_id),
        "title": normalize_text(title) or DEFAULT_SESSION_TITLE,
        "createdAt": timestamp,
        "updatedAt": timestamp,
        "trashedAt": "",
        "messages": [],
        "agentSessionId": next_session_id,
    }
    write_chat_session_file(session)
    return copy.deepcopy(session)


def ensure_chat_session(session_id: object, note_id: object, first_message: object = "") -> dict[str, Any]:
    target_note_id = normalize_note_id(note_id)
    requested_session_id = normalize_session_id(session_id)
    if requested_session_id:
        existing_session = get_chat_session(requested_session_id)
        if existing_session and existing_session.get("noteId") == target_note_id and not is_chat_session_trashed(existing_session):
            return existing_session
        if not existing_session:
            return create_chat_session(target_note_id, title=title_from_message(first_message), session_id=requested_session_id)
    return create_chat_session(target_note_id, title=title_from_message(first_message))


def title_from_message(message: object) -> str:
    title = re.sub(r"\s+", " ", normalize_text(message))
    if not title:
        return DEFAULT_SESSION_TITLE
    return f"{title[:47]}..." if len(title) > 50 else title


def append_chat_message(
    session_id: object,
    role: str,
    text: object,
    error: bool = False,
    sources: object = None,
    note_edit: object = None,
) -> dict[str, Any] | None:
    target_session_id = normalize_session_id(session_id)
    if not target_session_id:
        return None

    entry = find_chat_session_entry(session_id)
    if not entry:
        return None

    timestamp = now_iso()
    session = entry["session"]
    if is_chat_session_trashed(session):
        return None
    message = {
        "id": new_session_id(),
        "role": role if role in {"user", "assistant", "system"} else "assistant",
        "text": normalize_text(text),
        "createdAt": timestamp,
        "error": error,
        "sources": sanitize_chat_sources(sources),
        "noteEdit": sanitize_note_edit(note_edit),
    }
    session["messages"].append(message)
    session["updatedAt"] = timestamp
    if role == "user" and session.get("title") == DEFAULT_SESSION_TITLE:
        session["title"] = title_from_message(text)
    write_jsonl_lines(entry["path"], [message_line(message), session_update(session)], append=True)
    return copy.deepcopy(session)


def rename_chat_session(session_id: object, title: object) -> dict[str, Any] | None:
    target_session_id = normalize_session_id(session_id)
    next_title = normalize_text(title)
    if not target_session_id or not next_title:
        return None

    entry = find_chat_session_entry(session_id)
    if not entry:
        return None

    timestamp = now_iso()
    session = entry["session"]
    session["title"] = next_title
    session["updatedAt"] = timestamp
    write_jsonl_lines(entry["path"], [session_update(session)], append=True)
    return copy.deepcopy(session)


def trash_chat_session(session_id: object) -> dict[str, Any] | None:
    target_session_id = normalize_session_id(session_id)
    if not target_session_id:
        return None

    entry = find_chat_session_entry(target_session_id)
    if not entry:
        return None
    session = entry["session"]
    if not is_chat_session_trashed(session):
        timestamp = now_iso()
        session["trashedAt"] = timestamp
        session["updatedAt"] = timestamp
        write_jsonl_lines(entry["path"], [session_update(session)], append=True)
    return copy.deepcopy(session)


def restore_chat_session(session_id: object) -> dict[str, Any] | None:
    target_session_id = normalize_session_id(session_id)
    if not target_session_id:
        return None

    entry = find_chat_session_entry(target_session_id)
    if not entry:
        return None
    session = entry["session"]
    timestamp = now_iso()
    session["trashedAt"] = ""
    session["updatedAt"] = timestamp
    write_jsonl_lines(entry["path"], [session_update(session)], append=True)
    return copy.deepcopy(session)


def delete_chat_session_permanently(session_id: object) -> bool:
    target_session_id = normalize_session_id(session_id)
    if not target_session_id:
        return False

    entry = find_chat_session_entry(target_session_id)
    if not entry:
        return False
    entry["path"].unlink(missing_ok=True)
    return True
