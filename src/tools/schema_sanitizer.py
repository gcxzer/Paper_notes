"""Tool schema sanitizer.

Adapted from Nous Research Hermes Agent `tools/schema_sanitizer.py` (MIT License).
Paper Notes keeps the behavior intentionally small: sanitize locally defined and
future external schemas into the subset accepted by Responses-style function tools.

This module keeps behavior in one place:
- `sanitize_tool_schemas` cleans a list of tool definitions.
- `sanitize_parameters_schema` cleans a single `parameters` JSON schema and always
  returns a safe object-shaped schema.

Input/Output examples (for learning):

1) sanitize_tool_schemas
Input:
[
    {
        "name": "search_docs",
        "type": "function",
        "function": {
            "name": "search_docs",
            "parameters": {
                "type": "object",
                "properties": {"q": {"type": "string"}},
                "required": ["q"],
            },
        },
    },
    "invalid-entry",
]
Output:
[
    {
        "name": "search_docs",
        "type": "function",
        "function": {
            "name": "search_docs",
            "parameters": {
                "type": "object",
                "properties": {"q": {"type": "string"}},
                "required": ["q"],
                "additionalProperties": false,
            },
        },
    },
]

2) sanitize_parameters_schema
Input:
{
    "type": "string",
    "nullable": true,
    "enum": ["a", "b"],
}
Output:
{
    "type": "string",
    "additionalProperties": false,
}
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any


_SUPPORTED_TYPES = {"object", "array", "string", "number", "integer", "boolean", "null"}


def sanitize_tool_schemas(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sanitized: list[dict[str, Any]] = []
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        copied = deepcopy(tool)
        function = copied.get("function")
        if not isinstance(function, dict):
            sanitized.append(copied)
            continue
        function["parameters"] = sanitize_parameters_schema(function.get("parameters"))
        sanitized.append(copied)
    return sanitized


def sanitize_parameters_schema(schema: Any) -> dict[str, Any]:
    if not isinstance(schema, dict):
        return {"type": "object", "properties": {}, "additionalProperties": False}
    sanitized = _sanitize_schema_node(schema)
    if sanitized.get("type") != "object":
        sanitized = {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        }
    sanitized.setdefault("properties", {})
    if not isinstance(sanitized["properties"], dict):
        sanitized["properties"] = {}
    return sanitized


def _sanitize_schema_node(schema: Any) -> dict[str, Any]:
    if not isinstance(schema, dict):
        return {}
    node = {
        key: deepcopy(value)
        for key, value in schema.items()
        if key not in {"$schema", "$id", "definitions", "nullable"}
    }

    for combiner in ("anyOf", "oneOf", "allOf"):
        value = node.pop(combiner, None)
        merged = _merge_combiner(value, combiner=combiner)
        if merged:
            node.update({key: value for key, value in merged.items() if key not in node})

    node_type = _sanitize_type(node.get("type"))
    if node_type is None and "enum" in node:
        node_type = _type_from_enum(node.get("enum"))
    if node_type is not None:
        node["type"] = node_type
    else:
        node.pop("type", None)

    properties = node.get("properties")
    if isinstance(properties, dict):
        node["properties"] = {
            str(name): _sanitize_schema_node(prop_schema)
            for name, prop_schema in properties.items()
            if isinstance(prop_schema, dict)
        }

    defs = node.get("$defs")
    if isinstance(defs, dict):
        node["$defs"] = {
            str(name): _sanitize_schema_node(definition)
            for name, definition in defs.items()
            if isinstance(definition, dict)
        }
    elif "$defs" in node:
        node.pop("$defs", None)

    items = node.get("items")
    if isinstance(items, dict):
        node["items"] = _sanitize_schema_node(items)
    elif "items" in node:
        node.pop("items", None)

    required = node.get("required")
    if isinstance(required, list):
        property_names = set(node.get("properties", {})) if isinstance(node.get("properties"), dict) else set()
        node["required"] = [str(item) for item in required if str(item) in property_names]
    elif "required" in node:
        node.pop("required", None)

    additional = node.get("additionalProperties")
    if isinstance(additional, dict):
        node["additionalProperties"] = _sanitize_schema_node(additional)
    elif additional not in {True, False, None}:
        node.pop("additionalProperties", None)

    return node


def _sanitize_type(value: Any) -> str | list[str] | None:
    if isinstance(value, str):
        return value if value in _SUPPORTED_TYPES else None
    if not isinstance(value, list):
        return None
    seen: set[str] = set()
    sanitized: list[str] = []
    for item in value:
        if isinstance(item, str) and item in _SUPPORTED_TYPES and item not in seen:
            sanitized.append(item)
            seen.add(item)
    if not sanitized:
        return None
    return sanitized[0] if len(sanitized) == 1 else sanitized


def _type_from_enum(value: Any) -> str | None:
    if not isinstance(value, list) or not value:
        return None
    types = {type(item) for item in value if item is not None}
    if types == {str}:
        return "string"
    if types <= {int}:
        return "integer"
    if types <= {int, float}:
        return "number"
    if types == {bool}:
        return "boolean"
    return None


def _merge_combiner(value: Any, *, combiner: str) -> dict[str, Any]:
    if not isinstance(value, list) or not value:
        return {}
    sanitized_items = [_sanitize_schema_node(item) for item in value if isinstance(item, dict)]
    if not sanitized_items:
        return {}
    if combiner == "allOf":
        merged: dict[str, Any] = {}
        for item in sanitized_items:
            merged = _merge_schema_dicts(merged, item)
        return merged
    non_null = [
        item
        for item in sanitized_items
        if item.get("type") != "null" and item.get("type") != ["null"]
    ]
    return non_null[0] if non_null else sanitized_items[0]


def _merge_schema_dicts(base: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(base)
    for key, value in extra.items():
        if key == "properties" and isinstance(value, dict):
            existing = merged.setdefault("properties", {})
            if isinstance(existing, dict):
                existing.update(value)
            else:
                merged["properties"] = deepcopy(value)
            continue
        if key == "required" and isinstance(value, list):
            existing_required = merged.setdefault("required", [])
            if isinstance(existing_required, list):
                for item in value:
                    if item not in existing_required:
                        existing_required.append(item)
            else:
                merged["required"] = deepcopy(value)
            continue
        if key not in merged:
            merged[key] = deepcopy(value)
    return merged


__all__ = ["sanitize_parameters_schema", "sanitize_tool_schemas"]
