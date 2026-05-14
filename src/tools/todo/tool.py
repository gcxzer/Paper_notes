"""Session-local todo planning tool.

Adapted from Nous Research Hermes Agent `tools/todo_tool.py` (MIT License).
Paper Notes keeps todo state in the current session metadata instead of an
in-memory AIAgent instance so it survives HTTP requests and context compaction.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from agent_sessions import AgentSessionStore
from tools.registry import ToolDefinition, ToolRegistry
from tools.todo.manifest import TOOL_GROUP


TODO_TOOLSET = "todo"
TODO_METADATA_KEY = "todo_items"
VALID_TODO_STATUSES = {"pending", "in_progress", "completed", "cancelled"}


class SessionTodoStore:
    def __init__(
        self,
        session_store: AgentSessionStore,
        *,
        current_session_id_provider: Callable[[], str] | None = None,
    ) -> None:
        self.session_store = session_store
        self.current_session_id_provider = current_session_id_provider or (lambda: "")

    def read(self, session_id: str | None = None) -> list[dict[str, str]]:
        resolved_session_id = self._session_id(session_id)
        if not resolved_session_id:
            return []
        session = self.session_store.get_session(resolved_session_id)
        if session is None:
            return []
        return [_validate_todo_item(item) for item in _raw_todo_items(session.metadata.metadata)]

    def write(
        self,
        todos: list[dict[str, Any]],
        *,
        merge: bool = False,
        session_id: str | None = None,
    ) -> list[dict[str, str]]:
        resolved_session_id = self._session_id(session_id)
        if not resolved_session_id:
            raise ValueError("TodoStore has no active session.")

        current = self.read(resolved_session_id)
        if merge:
            items = _merge_todos(current, todos)
        else:
            items = [_validate_todo_item(item, strict=True) for item in _dedupe_by_id(todos)]
        _ensure_single_in_progress(items)
        self.session_store.update_session_metadata(resolved_session_id, {TODO_METADATA_KEY: items})
        return self.read(resolved_session_id)

    def format_for_injection(self, session_id: str | None = None) -> str:
        active_items = [
            item
            for item in self.read(session_id)
            if item["status"] in {"pending", "in_progress"}
        ]
        if not active_items:
            return ""

        markers = {
            "completed": "[x]",
            "in_progress": "[>]",
            "pending": "[ ]",
            "cancelled": "[~]",
        }
        lines = ["[Your active session task list was preserved]"]
        for item in active_items:
            lines.append(f"- {markers.get(item['status'], '[?]')} {item['id']}. {item['content']} ({item['status']})")
        return "\n".join(lines)

    def _session_id(self, session_id: str | None = None) -> str:
        return str(session_id or self.current_session_id_provider() or "").strip()


def register_todo_tool(registry: ToolRegistry, *, store: SessionTodoStore) -> None:
    registry.register_group(TOOL_GROUP)
    if registry.get("todo") is not None:
        return
    registry.register(create_todo_tool_definition(store))


def create_todo_tool_definition(store: SessionTodoStore) -> ToolDefinition:
    return ToolDefinition(
        name="todo",
        description=(
            "Manage your task list for the current session. Use for complex tasks with 3+ steps "
            "or when the user provides multiple tasks. Call with no parameters to read the current list.\n\n"
            "Writing:\n"
            "- Provide 'todos' array to create/update items\n"
            "- merge=false (default): replace the entire list with a fresh plan\n"
            "- merge=true: update existing items by id, add any new ones\n\n"
            "Each item: {id: string, content: string, status: pending|in_progress|completed|cancelled}. "
            "List order is priority. Only ONE item should be in_progress at a time. "
            "Mark items completed immediately when done. If something fails, cancel it and add a revised item. "
            "Always returns the full current list."
        ),
        parameters={
            "type": "object",
            "properties": {
                "todos": {
                    "type": "array",
                    "description": "Task items to write. Omit to read current list.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {
                                "type": "string",
                                "description": "Unique item identifier.",
                            },
                            "content": {
                                "type": "string",
                                "description": "Task description.",
                            },
                            "status": {
                                "type": "string",
                                "enum": ["pending", "in_progress", "completed", "cancelled"],
                                "description": "Current task status.",
                            },
                        },
                        "required": ["id", "content", "status"],
                    },
                },
                "merge": {
                    "type": "boolean",
                    "description": "true: update existing items by id and add new ones; false: replace the full list.",
                    "default": False,
                },
            },
            "required": [],
            "additionalProperties": False,
        },
        handler=lambda args: todo_tool(args, store=store),
        toolset=TODO_TOOLSET,
        read_only=False,
        mutating=True,
        risk="write",
        kind="plan",
        result_max_chars=8_000,
        metadata={"durability": "session"},
    )


def todo_tool(args: dict[str, Any], *, store: SessionTodoStore) -> dict[str, Any]:
    todos = args.get("todos")
    merge = bool(args.get("merge", False))
    if todos is not None and not isinstance(todos, list):
        return {"success": False, "error": "todos must be an array when provided"}

    try:
        items = store.write(todos, merge=merge) if todos is not None else store.read()
    except ValueError as error:
        return {"success": False, "error": str(error)}

    return {
        "success": True,
        "todos": items,
        "summary": _todo_summary(items),
    }


def _merge_todos(current: list[dict[str, str]], incoming: list[dict[str, Any]]) -> list[dict[str, str]]:
    items = [dict(item) for item in current]
    by_id = {item["id"]: item for item in items}
    for raw in _dedupe_by_id(incoming):
        validated = _validate_todo_item(raw, strict=True)
        item_id = validated["id"]
        if item_id in by_id:
            existing = by_id[item_id]
            existing["content"] = validated["content"]
            existing["status"] = validated["status"]
        else:
            by_id[validated["id"]] = validated
            items.append(validated)
    return [_validate_todo_item(item, strict=True) for item in items]


def _raw_todo_items(metadata: dict[str, Any]) -> list[dict[str, Any]]:
    raw = metadata.get(TODO_METADATA_KEY) if isinstance(metadata, dict) else []
    return [item for item in raw if isinstance(item, dict)] if isinstance(raw, list) else []


def _validate_todo_item(item: dict[str, Any], *, strict: bool = False) -> dict[str, str]:
    item_id = str(item.get("id") or "").strip()
    content = str(item.get("content") or "").strip()
    status = str(item.get("status") or "pending").strip().lower()
    if strict and not item_id:
        raise ValueError("todo item id is required")
    if strict and not content:
        raise ValueError("todo item content is required")
    if status not in VALID_TODO_STATUSES:
        if strict:
            raise ValueError(f"todo item status must be one of: {', '.join(sorted(VALID_TODO_STATUSES))}")
        status = "pending"
    return {
        "id": item_id or "?",
        "content": content or "(no description)",
        "status": status,
    }


def _dedupe_by_id(todos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    last_index: dict[str, int] = {}
    for index, item in enumerate(todos):
        if not isinstance(item, dict):
            continue
        item_id = str(item.get("id") or "").strip() or "?"
        last_index[item_id] = index
    return [todos[index] for index in sorted(last_index.values()) if isinstance(todos[index], dict)]


def _ensure_single_in_progress(items: list[dict[str, str]]) -> None:
    count = sum(1 for item in items if item.get("status") == "in_progress")
    if count > 1:
        raise ValueError("todo list can contain at most one in_progress item")


def _todo_summary(items: list[dict[str, str]]) -> dict[str, int]:
    return {
        "total": len(items),
        "pending": sum(1 for item in items if item["status"] == "pending"),
        "in_progress": sum(1 for item in items if item["status"] == "in_progress"),
        "completed": sum(1 for item in items if item["status"] == "completed"),
        "cancelled": sum(1 for item in items if item["status"] == "cancelled"),
    }
