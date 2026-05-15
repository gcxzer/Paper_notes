"""Transparent snapshots for local Paper Notes mutating tools.

Inspired by Hermes' checkpoint manager, but intentionally narrower: this
manager snapshots only Paper Notes files touched by local note-writing tools.
It is not exposed as a model tool.
"""

from __future__ import annotations

import hashlib
import difflib
import os
import re
import shutil
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from library.annotations import annotation_path_for
from app_infra.formatting import normalize_text
from library import find_note, read_library
from app_infra.paths import ANNOTATIONS_DIR, HTML_DIR, NOTES_PATH, PROJECT_ROOT, is_relative_to
from app_infra.storage import atomic_replace, atomic_write_json


NOTE_HTML_TOOLS = {
    "write_note",
    "write_note_media",
    "write_note_section",
    "append_note_section",
    "replace_note_section",
    "write_note_from_paper_image",
}
LIBRARY_TOOLS = {"update_note_metadata"}
ANNOTATION_TOOLS = {"manage_annotations"}


class ToolSnapshotError(Exception):
    """Raised when a tool snapshot cannot be loaded or restored."""


class ToolSnapshotConflictError(ToolSnapshotError):
    def __init__(self, message: str, conflicts: list[dict[str, Any]]) -> None:
        super().__init__(message)
        self.conflicts = conflicts


@dataclass(frozen=True, slots=True)
class ToolSnapshotHandle:
    session_id: str
    snapshot_id: str
    manifest_path: Path


class PaperNotesSnapshotManager:
    def __init__(
        self,
        snapshot_root: Path,
        *,
        project_root: Path = PROJECT_ROOT,
        notes_path: Path = NOTES_PATH,
        html_dir: Path = HTML_DIR,
        annotations_dir: Path = ANNOTATIONS_DIR,
    ) -> None:
        self.snapshot_root = Path(snapshot_root)
        self.project_root = Path(project_root).resolve()
        self.notes_path = Path(notes_path).resolve()
        self.html_dir = Path(html_dir).resolve()
        self.annotations_dir = Path(annotations_dir).resolve()

    def start(
        self,
        *,
        session_id: str,
        tool_call_id: str,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> ToolSnapshotHandle | None:
        session_id = _safe_id(session_id)
        if not session_id:
            return None
        paths = self._affected_paths(tool_name, arguments)
        if not paths:
            return None

        base_snapshot_id = _safe_id(tool_call_id) or f"snapshot-{uuid.uuid4().hex[:12]}"
        snapshot_id = self._unique_snapshot_id(session_id, base_snapshot_id)
        snapshot_dir = self.snapshot_root / session_id / snapshot_id
        files_dir = snapshot_dir / "files"
        files_dir.mkdir(parents=True, exist_ok=True)

        file_entries = []
        for index, path in enumerate(paths):
            resolved = Path(path).resolve()
            if not self._is_allowed_path(resolved):
                continue
            existed = resolved.exists()
            snapshot_file = files_dir / f"{index}.bin"
            before_hash = ""
            size = 0
            if existed and resolved.is_file():
                data = resolved.read_bytes()
                before_hash = _sha256_bytes(data)
                size = len(data)
                snapshot_file.write_bytes(data)
            file_entries.append({
                "path": str(resolved),
                "relativePath": self._relative_label(resolved),
                "existed": existed and resolved.is_file(),
                "beforeHash": before_hash,
                "beforeBytes": size,
                "snapshotFile": str(snapshot_file.relative_to(snapshot_dir)) if existed else "",
            })

        if not file_entries:
            return None

        manifest = {
            "version": 1,
            "sessionId": session_id,
            "snapshotId": snapshot_id,
            "toolCallId": tool_call_id,
            "toolName": tool_name,
            "arguments": _argument_summary(arguments),
            "files": file_entries,
            "changed": False,
            "changedFiles": [],
            "restored": False,
        }
        manifest_path = snapshot_dir / "manifest.json"
        atomic_write_json(manifest_path, manifest)
        return ToolSnapshotHandle(session_id=session_id, snapshot_id=snapshot_id, manifest_path=manifest_path)

    def finalize(self, handle: ToolSnapshotHandle | None, *, failed: bool = False) -> dict[str, Any] | None:
        if handle is None:
            return None
        manifest = self._read_manifest(handle.session_id, handle.snapshot_id)
        snapshot_dir = self.snapshot_root / handle.session_id / handle.snapshot_id
        files_dir = snapshot_dir / "files"
        files_dir.mkdir(parents=True, exist_ok=True)
        changed_files = []
        next_files = []
        for index, entry in enumerate(manifest.get("files", [])):
            if not isinstance(entry, dict):
                continue
            path = Path(str(entry.get("path") or "")).resolve()
            if not self._is_allowed_path(path):
                continue
            after_hash = ""
            after_bytes = 0
            after_data = b""
            after_exists = path.exists() and path.is_file()
            if after_exists:
                after_data = path.read_bytes()
                after_hash = _sha256_bytes(after_data)
                after_bytes = len(after_data)
            changed = bool(entry.get("existed")) != after_exists or str(entry.get("beforeHash") or "") != after_hash
            next_entry = {
                **entry,
                "afterHash": after_hash,
                "afterBytes": after_bytes,
                "afterExists": after_exists,
                "changed": changed,
            }
            if after_exists and changed:
                after_file = files_dir / f"{index}.after.bin"
                after_file.write_bytes(after_data)
                next_entry["afterFile"] = str(after_file.relative_to(snapshot_dir))
            next_files.append(next_entry)
            if changed:
                changed_files.append({
                    "path": entry.get("relativePath") or self._relative_label(path),
                    "beforeBytes": int(entry.get("beforeBytes") or 0),
                    "afterBytes": after_bytes,
                })

        manifest["files"] = next_files
        manifest["changed"] = bool(changed_files)
        manifest["changedFiles"] = changed_files
        manifest["failed"] = bool(failed)
        atomic_write_json(handle.manifest_path, manifest)
        return self._public_snapshot(manifest)

    def restore(self, *, session_id: str, snapshot_id: str, force: bool = False) -> dict[str, Any]:
        session_id = _safe_id(session_id)
        snapshot_id = _safe_id(snapshot_id)
        if not session_id or not snapshot_id:
            raise ToolSnapshotError("session_id and snapshot_id are required.")
        manifest = self._read_manifest(session_id, snapshot_id)
        snapshot_dir = self.snapshot_root / session_id / snapshot_id
        conflicts = self._restore_conflicts(manifest)
        if conflicts and not force:
            raise ToolSnapshotConflictError("Snapshot restore would overwrite newer changes.", conflicts)
        restored_files = []
        manifest_changed = False

        for index, entry in enumerate(manifest.get("files", [])):
            if not isinstance(entry, dict):
                continue
            path = Path(str(entry.get("path") or "")).resolve()
            if not self._is_allowed_path(path):
                raise ToolSnapshotError(f"Snapshot path is outside Paper Notes storage: {path}")
            if (
                entry.get("changed")
                and entry.get("afterExists")
                and not normalize_text(entry.get("afterFile"))
                and path.exists()
                and path.is_file()
            ):
                after_data = path.read_bytes()
                after_file = snapshot_dir / "files" / f"{index}.after.bin"
                after_file.parent.mkdir(parents=True, exist_ok=True)
                after_file.write_bytes(after_data)
                entry["afterFile"] = str(after_file.relative_to(snapshot_dir))
                manifest_changed = True
            if entry.get("existed"):
                snapshot_file = snapshot_dir / str(entry.get("snapshotFile") or "")
                if not snapshot_file.is_file():
                    raise ToolSnapshotError(f"Snapshot file missing for {path.name}.")
                _atomic_write_bytes(path, snapshot_file.read_bytes())
            elif path.exists():
                path.unlink()
            restored_files.append(entry.get("relativePath") or self._relative_label(path))

        manifest["restored"] = True
        manifest["redone"] = False
        manifest["restoredFiles"] = restored_files
        if manifest_changed:
            manifest["files"] = manifest.get("files", [])
        atomic_write_json(snapshot_dir / "manifest.json", manifest)
        return {
            "success": True,
            "sessionId": session_id,
            "snapshotId": snapshot_id,
            "toolName": manifest.get("toolName") or "",
            "restoredFiles": restored_files,
            "forced": bool(force),
        }

    def redo(self, *, session_id: str, snapshot_id: str, force: bool = False) -> dict[str, Any]:
        session_id = _safe_id(session_id)
        snapshot_id = _safe_id(snapshot_id)
        if not session_id or not snapshot_id:
            raise ToolSnapshotError("session_id and snapshot_id are required.")
        manifest = self._read_manifest(session_id, snapshot_id)
        snapshot_dir = self.snapshot_root / session_id / snapshot_id
        conflicts = self._redo_conflicts(manifest)
        if conflicts and not force:
            raise ToolSnapshotConflictError("Snapshot redo would overwrite newer changes.", conflicts)
        redone_files = []

        for entry in manifest.get("files", []):
            if not isinstance(entry, dict) or not entry.get("changed"):
                continue
            path = Path(str(entry.get("path") or "")).resolve()
            if not self._is_allowed_path(path):
                raise ToolSnapshotError(f"Snapshot path is outside Paper Notes storage: {path}")
            if entry.get("afterExists"):
                after_file = snapshot_dir / str(entry.get("afterFile") or "")
                if not after_file.is_file():
                    raise ToolSnapshotError(f"Snapshot redo file missing for {path.name}.")
                _atomic_write_bytes(path, after_file.read_bytes())
            elif path.exists():
                path.unlink()
            redone_files.append(entry.get("relativePath") or self._relative_label(path))

        manifest["restored"] = False
        manifest["redone"] = True
        manifest["redoneFiles"] = redone_files
        atomic_write_json(snapshot_dir / "manifest.json", manifest)
        return {
            "success": True,
            "sessionId": session_id,
            "snapshotId": snapshot_id,
            "toolName": manifest.get("toolName") or "",
            "redoneFiles": redone_files,
            "forced": bool(force),
        }

    def preview_diff(self, *, session_id: str, snapshot_id: str, max_chars: int = 16_000) -> dict[str, Any]:
        session_id = _safe_id(session_id)
        snapshot_id = _safe_id(snapshot_id)
        if not session_id or not snapshot_id:
            raise ToolSnapshotError("session_id and snapshot_id are required.")
        manifest = self._read_manifest(session_id, snapshot_id)
        snapshot_dir = self.snapshot_root / session_id / snapshot_id
        files = []
        remaining = max(1_000, int(max_chars or 16_000))
        for entry in manifest.get("files", []):
            if not isinstance(entry, dict) or not entry.get("changed"):
                continue
            path = Path(str(entry.get("path") or "")).resolve()
            if not self._is_allowed_path(path):
                continue
            before_bytes = b""
            if entry.get("existed"):
                snapshot_file = snapshot_dir / str(entry.get("snapshotFile") or "")
                if snapshot_file.is_file():
                    before_bytes = snapshot_file.read_bytes()
            current_exists = path.exists() and path.is_file()
            current_bytes = path.read_bytes() if current_exists else b""
            current_hash = _sha256_bytes(current_bytes) if current_exists else ""
            expected_hash = str(entry.get("afterHash") or "")
            after_bytes = b""
            if entry.get("afterExists"):
                after_file = snapshot_dir / str(entry.get("afterFile") or "")
                if after_file.is_file():
                    after_bytes = after_file.read_bytes()
                elif current_hash == expected_hash:
                    after_bytes = current_bytes
            diff_text = _unified_text_diff(
                before_bytes,
                after_bytes,
                fromfile=f"before/{entry.get('relativePath') or path.name}",
                tofile=f"after/{entry.get('relativePath') or path.name}",
            )
            truncated = len(diff_text) > remaining
            if truncated:
                diff_text = diff_text[:remaining].rstrip() + "\n... diff truncated ..."
            remaining = max(0, remaining - len(diff_text))
            files.append({
                "path": entry.get("relativePath") or self._relative_label(path),
                "beforeBytes": int(entry.get("beforeBytes") or 0),
                "afterBytes": int(entry.get("afterBytes") or 0),
                "currentBytes": len(current_bytes),
                "currentMatchesSnapshot": current_hash == expected_hash,
                "diff": diff_text,
                "truncated": truncated,
            })
            if remaining <= 0:
                break
        return {
            "success": True,
            "sessionId": session_id,
            "snapshotId": snapshot_id,
            "toolName": manifest.get("toolName") or "",
            "arguments": manifest.get("arguments") if isinstance(manifest.get("arguments"), dict) else {},
            "files": files,
        }

    def list_snapshots(self, *, session_id: str, limit: int = 50) -> list[dict[str, Any]]:
        session_id = _safe_id(session_id)
        if not session_id:
            return []
        session_dir = self.snapshot_root / session_id
        if not session_dir.exists():
            return []
        snapshots: list[dict[str, Any]] = []
        for manifest_path in session_dir.glob("*/manifest.json"):
            try:
                manifest = self._read_manifest(session_id, manifest_path.parent.name)
            except ToolSnapshotError:
                continue
            public = self._public_snapshot(manifest)
            public.update({
                "sessionId": session_id,
                "createdAt": _mtime_iso(manifest_path),
                "arguments": manifest.get("arguments") if isinstance(manifest.get("arguments"), dict) else {},
                "restored": bool(manifest.get("restored")),
                "failed": bool(manifest.get("failed")),
            })
            snapshots.append(public)
        snapshots.sort(key=lambda item: str(item.get("createdAt") or ""), reverse=True)
        return snapshots[: max(1, min(int(limit or 50), 200))]

    def cleanup(
        self,
        *,
        session_id: str | None = None,
        keep_per_session: int = 50,
        max_age_days: int | None = None,
    ) -> dict[str, Any]:
        keep = max(0, int(keep_per_session))
        if session_id:
            safe_session_id = _safe_id(session_id)
            roots = [self.snapshot_root / safe_session_id] if safe_session_id else []
        elif self.snapshot_root.exists():
            roots = [path for path in self.snapshot_root.iterdir() if path.is_dir()]
        else:
            roots = []

        deleted: list[str] = []
        cutoff = time.time() - (max_age_days * 86400) if max_age_days is not None and max_age_days >= 0 else None
        for root in roots:
            manifests = sorted(
                root.glob("*/manifest.json"),
                key=lambda path: path.stat().st_mtime,
                reverse=True,
            )
            for index, manifest_path in enumerate(manifests):
                should_delete = index >= keep
                if cutoff is not None and manifest_path.stat().st_mtime < cutoff:
                    should_delete = True
                if not should_delete:
                    continue
                snapshot_dir = manifest_path.parent
                deleted.append(snapshot_dir.name)
                shutil.rmtree(snapshot_dir, ignore_errors=True)
        return {
            "success": True,
            "deletedCount": len(deleted),
            "deletedSnapshotIds": deleted,
        }

    def _affected_paths(self, tool_name: str, arguments: dict[str, Any]) -> list[Path]:
        if tool_name == "write_note":
            action = normalize_text(arguments.get("action")).lower()
            if action == "update_metadata":
                return [self.notes_path]
            if action in {"write_section", "append_to_section", "delete_section"}:
                path = self._note_html_path(arguments)
                return [path] if path is not None else []
            return []
        if tool_name in ANNOTATION_TOOLS:
            note_id = normalize_text(arguments.get("note_id") or arguments.get("id"))
            path = annotation_path_for(note_id, self.annotations_dir) if note_id else None
            return [path] if path is not None else []
        if tool_name in LIBRARY_TOOLS:
            return [self.notes_path]
        if tool_name in NOTE_HTML_TOOLS:
            path = self._note_html_path(arguments)
            return [path] if path is not None else []
        return []

    def _note_html_path(self, arguments: dict[str, Any]) -> Path | None:
        note_id = normalize_text(arguments.get("note_id") or arguments.get("id"))
        if not note_id:
            return None
        library = read_library(self.notes_path)
        note = find_note(library, note_id)
        if note is None:
            return None
        html_href = normalize_text(note.get("htmlHref"))
        if not html_href:
            return None
        raw_path = Path(unquote(html_href))
        if raw_path.is_absolute():
            html_path = raw_path.resolve()
        else:
            parts = raw_path.parts
            if "Paper-html" in parts:
                rel_path = Path(*parts[parts.index("Paper-html") + 1:])
                html_path = (self.html_dir / rel_path).resolve()
            else:
                html_path = (self.project_root / raw_path).resolve()
        if not is_relative_to(html_path, self.html_dir):
            return None
        return html_path

    def _read_manifest(self, session_id: str, snapshot_id: str) -> dict[str, Any]:
        manifest_path = self.snapshot_root / session_id / snapshot_id / "manifest.json"
        try:
            import json

            data = json.loads(manifest_path.read_text(encoding="utf-8"))
        except FileNotFoundError as error:
            raise ToolSnapshotError(f"Snapshot not found: {snapshot_id}") from error
        except Exception as error:
            raise ToolSnapshotError(f"Snapshot is unreadable: {snapshot_id}") from error
        if not isinstance(data, dict):
            raise ToolSnapshotError(f"Snapshot is invalid: {snapshot_id}")
        return data

    def _unique_snapshot_id(self, session_id: str, base_snapshot_id: str) -> str:
        session_dir = self.snapshot_root / session_id
        if not (session_dir / base_snapshot_id).exists():
            return base_snapshot_id
        for suffix in range(2, 10_000):
            candidate = f"{base_snapshot_id}-{suffix}"
            if not (session_dir / candidate).exists():
                return candidate
        return f"{base_snapshot_id}-{uuid.uuid4().hex[:8]}"

    def _restore_conflicts(self, manifest: dict[str, Any]) -> list[dict[str, Any]]:
        conflicts = []
        for entry in manifest.get("files", []):
            if not isinstance(entry, dict) or not entry.get("changed"):
                continue
            path = Path(str(entry.get("path") or "")).resolve()
            if not self._is_allowed_path(path):
                continue
            current_exists = path.exists() and path.is_file()
            current_hash = _sha256_bytes(path.read_bytes()) if current_exists else ""
            expected_exists = bool(entry.get("afterExists")) if "afterExists" in entry else bool(entry.get("afterHash"))
            expected_hash = str(entry.get("afterHash") or "")
            if current_exists != expected_exists or current_hash != expected_hash:
                conflicts.append({
                    "path": entry.get("relativePath") or self._relative_label(path),
                    "expectedHash": expected_hash,
                    "currentHash": current_hash,
                    "expectedExists": expected_exists,
                    "currentExists": current_exists,
                })
        return conflicts

    def _redo_conflicts(self, manifest: dict[str, Any]) -> list[dict[str, Any]]:
        conflicts = []
        for entry in manifest.get("files", []):
            if not isinstance(entry, dict) or not entry.get("changed"):
                continue
            path = Path(str(entry.get("path") or "")).resolve()
            if not self._is_allowed_path(path):
                continue
            current_exists = path.exists() and path.is_file()
            current_hash = _sha256_bytes(path.read_bytes()) if current_exists else ""
            expected_exists = bool(entry.get("existed"))
            expected_hash = str(entry.get("beforeHash") or "")
            if current_exists != expected_exists or current_hash != expected_hash:
                conflicts.append({
                    "path": entry.get("relativePath") or self._relative_label(path),
                    "expectedHash": expected_hash,
                    "currentHash": current_hash,
                    "expectedExists": expected_exists,
                    "currentExists": current_exists,
                })
        return conflicts

    def _is_allowed_path(self, path: Path) -> bool:
        resolved = path.resolve()
        return (
            resolved == self.notes_path
            or is_relative_to(resolved, self.html_dir)
            or is_relative_to(resolved, self.annotations_dir)
        )

    def _relative_label(self, path: Path) -> str:
        try:
            return str(path.resolve().relative_to(self.project_root))
        except ValueError:
            return path.name

    def _public_snapshot(self, manifest: dict[str, Any]) -> dict[str, Any]:
        changed = bool(manifest.get("changed"))
        failed = bool(manifest.get("failed"))
        current_matches_after = changed and not self._restore_conflicts(manifest)
        current_matches_before = changed and not self._redo_conflicts(manifest)
        return {
            "snapshotId": manifest.get("snapshotId") or "",
            "toolName": manifest.get("toolName") or "",
            "changed": changed,
            "changedFiles": manifest.get("changedFiles") if isinstance(manifest.get("changedFiles"), list) else [],
            "undoable": changed,
            "canUndo": changed and not failed and current_matches_after,
            "canRedo": changed and not failed and current_matches_before,
            "currentMatchesAfter": current_matches_after,
            "currentMatchesBefore": current_matches_before,
        }


def _safe_id(value: Any) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_.-]+", "-", str(value or "").strip())
    return cleaned.strip("-._")[:120]


def _argument_summary(arguments: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for key in ("note_id", "id", "annotation_id", "heading", "position", "summary", "venue", "date", "category_id"):
        if key in arguments and arguments.get(key) is not None:
            value = normalize_text(arguments.get(key))
            summary[key] = value[:200]
    if "tags" in arguments:
        tags = arguments.get("tags")
        summary["tags"] = tags[:20] if isinstance(tags, list) else normalize_text(tags)[:200]
    return summary


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _mtime_iso(path: Path) -> str:
    from datetime import datetime, timezone

    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.stem}_", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as file:
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
        atomic_replace(tmp_path, path)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _unified_text_diff(before: bytes, after: bytes, *, fromfile: str, tofile: str) -> str:
    before_text = before.decode("utf-8", errors="replace").splitlines(keepends=True)
    after_text = after.decode("utf-8", errors="replace").splitlines(keepends=True)
    if not before_text and not after_text:
        return ""
    return "".join(
        difflib.unified_diff(
            before_text,
            after_text,
            fromfile=fromfile,
            tofile=tofile,
            lineterm="",
        )
    )
