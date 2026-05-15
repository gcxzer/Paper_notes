from __future__ import annotations

from typing import Any


_GEMINI_SCHEMA_ALLOWED_KEYS = {
    "type",
    "format",
    "title",
    "description",
    "nullable",
    "enum",
    "maxItems",
    "minItems",
    "properties",
    "required",
    "minProperties",
    "maxProperties",
    "minLength",
    "maxLength",
    "pattern",
    "example",
    "anyOf",
    "propertyOrdering",
    "default",
    "items",
    "minimum",
    "maximum",
}


def sanitize_gemini_schema(schema: Any) -> dict[str, Any]:
    """Return a Gemini-compatible copy of an OpenAI-flavored JSON schema.

    Adapted from Hermes Agent's Gemini schema adapter.
    """

    if not isinstance(schema, dict):
        return {}

    cleaned: dict[str, Any] = {}
    for key, value in schema.items():
        if key not in _GEMINI_SCHEMA_ALLOWED_KEYS:
            continue
        if key == "properties":
            if not isinstance(value, dict):
                continue
            cleaned[key] = {
                prop_name: sanitize_gemini_schema(prop_schema)
                for prop_name, prop_schema in value.items()
                if isinstance(prop_name, str)
            }
            continue
        if key == "items":
            cleaned[key] = sanitize_gemini_schema(value)
            continue
        if key == "anyOf":
            if not isinstance(value, list):
                continue
            cleaned[key] = [sanitize_gemini_schema(item) for item in value if isinstance(item, dict)]
            continue
        cleaned[key] = value

    enum_value = cleaned.get("enum")
    type_value = cleaned.get("type")
    if isinstance(enum_value, list) and type_value in {"integer", "number", "boolean"}:
        if any(not isinstance(item, str) for item in enum_value):
            cleaned.pop("enum", None)

    return cleaned


def sanitize_gemini_tool_parameters(parameters: Any) -> dict[str, Any]:
    cleaned = sanitize_gemini_schema(parameters)
    return cleaned or {"type": "object", "properties": {}}
