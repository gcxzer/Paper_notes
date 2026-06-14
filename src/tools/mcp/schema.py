from __future__ import annotations

from typing import Any


def normalize_mcp_input_schema(schema: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(schema, dict) or not schema:
        return {"type": "object", "properties": {}}

    def _rewrite_local_refs(node: Any) -> Any:
        if isinstance(node, list):
            return [_rewrite_local_refs(item) for item in node]
        if not isinstance(node, dict):
            return node
        rewritten: dict[str, Any] = {}
        for key, value in node.items():
            out_key = "$defs" if key == "definitions" else key
            rewritten[out_key] = _rewrite_local_refs(value)
        ref = rewritten.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/definitions/"):
            rewritten["$ref"] = "#/$defs/" + ref[len("#/definitions/"):]
        return rewritten

    def _strip_nullable(node: Any) -> Any:
        if isinstance(node, list):
            return [_strip_nullable(item) for item in node]
        if not isinstance(node, dict):
            return node
        cleaned = {key: _strip_nullable(value) for key, value in node.items()}
        for combiner in ("anyOf", "oneOf"):
            value = cleaned.get(combiner)
            if not isinstance(value, list):
                continue
            non_null = [item for item in value if not (isinstance(item, dict) and item.get("type") == "null")]
            if len(non_null) == 1 and len(non_null) != len(value):
                merged = dict(non_null[0])
                for key, original_value in cleaned.items():
                    if key not in {combiner, "type"} and key not in merged:
                        merged[key] = original_value
                merged["nullable"] = True
                return _strip_nullable(merged)
        return cleaned

    def _repair(node: Any) -> Any:
        if isinstance(node, list):
            return [_repair(item) for item in node]
        if not isinstance(node, dict):
            return node
        repaired = {key: _repair(value) for key, value in node.items()}
        if not repaired.get("type") and ("properties" in repaired or "required" in repaired):
            repaired["type"] = "object"
        if repaired.get("type") == "object":
            properties = repaired.get("properties")
            if not isinstance(properties, dict):
                repaired["properties"] = {}
                properties = repaired["properties"]
            required = repaired.get("required")
            if isinstance(required, list):
                valid = [item for item in required if isinstance(item, str) and item in properties]
                if valid:
                    repaired["required"] = valid
                else:
                    repaired.pop("required", None)
        return repaired

    normalized = _repair(_strip_nullable(_rewrite_local_refs(schema)))
    if not isinstance(normalized, dict) or normalized.get("type") != "object":
        return {"type": "object", "properties": {}}
    normalized.setdefault("properties", {})
    if not isinstance(normalized["properties"], dict):
        normalized["properties"] = {}
    return normalized


__all__ = ["normalize_mcp_input_schema"]
