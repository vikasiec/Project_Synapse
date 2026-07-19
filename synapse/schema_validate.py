"""
Lightweight JSON-schema-ish validation for frozen contracts.

Uses required fields + basic types from docs/schemas/*.schema.json
without requiring the jsonschema package.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

SCHEMAS_DIR = Path(__file__).resolve().parent.parent / "docs" / "schemas"

_CACHE: dict[str, dict[str, Any]] = {}


class SchemaValidationError(ValueError):
    pass


def _load_schema(name: str) -> dict[str, Any]:
    key = name if name.endswith(".schema.json") else f"{name}.schema.json"
    if key in _CACHE:
        return _CACHE[key]
    path = SCHEMAS_DIR / key
    if not path.exists():
        raise SchemaValidationError(f"Schema not found: {path}")
    with path.open(encoding="utf-8") as f:
        schema = json.load(f)
    _CACHE[key] = schema
    return schema


def _type_ok(value: Any, declared: Any) -> bool:
    if isinstance(declared, list):
        return any(_type_ok(value, d) for d in declared)
    if declared == "string":
        return isinstance(value, str)
    if declared == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if declared == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if declared == "boolean":
        return isinstance(value, bool)
    if declared == "array":
        return isinstance(value, list)
    if declared == "object":
        return isinstance(value, dict)
    if declared == "null":
        return value is None
    return True  # unknown type keyword → permissive


def validate_model_dict(schema_name: str, data: dict[str, Any]) -> dict[str, Any]:
    """
    Validate a model dict against a frozen schema.

    Checks: type=object, required keys, property types, simple enums, min/max for numbers.
    Raises SchemaValidationError on failure. Returns data on success.
    """
    schema = _load_schema(schema_name)
    if schema.get("type") == "object" and not isinstance(data, dict):
        raise SchemaValidationError(f"{schema_name}: expected object")

    for req in schema.get("required", []):
        if req not in data:
            raise SchemaValidationError(f"{schema_name}: missing required field '{req}'")

    props = schema.get("properties", {})
    for key, value in data.items():
        if key not in props:
            if schema.get("additionalProperties") is False:
                raise SchemaValidationError(f"{schema_name}: unexpected field '{key}'")
            continue
        prop = props[key]
        if "type" in prop and not _type_ok(value, prop["type"]):
            raise SchemaValidationError(
                f"{schema_name}.{key}: type mismatch (got {type(value).__name__})"
            )
        if "enum" in prop and value is not None and value not in prop["enum"]:
            raise SchemaValidationError(f"{schema_name}.{key}: value not in enum {prop['enum']}")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if "minimum" in prop and value < prop["minimum"]:
                raise SchemaValidationError(f"{schema_name}.{key}: below minimum")
            if "maximum" in prop and value > prop["maximum"]:
                raise SchemaValidationError(f"{schema_name}.{key}: above maximum")
        if isinstance(value, list) and "minItems" in prop and len(value) < prop["minItems"]:
            raise SchemaValidationError(f"{schema_name}.{key}: fewer than minItems")
        if isinstance(value, str) and "minLength" in prop and len(value) < prop["minLength"]:
            raise SchemaValidationError(f"{schema_name}.{key}: shorter than minLength")

    return data


def list_schemas() -> list[str]:
    if not SCHEMAS_DIR.exists():
        return []
    return sorted(p.name for p in SCHEMAS_DIR.glob("*.schema.json"))
