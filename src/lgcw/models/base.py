"""Frozen boundaries and validation of Codex-compatible output schemas."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

type Step = Literal[
    "reconcile",
    "intake",
    "open_pr",
    "build",
    "gate",
    "publish",
    "ci_wait",
    "review",
    "merge_ready",
    "ask",
    "blocked",
    "end",
]


class Strict(BaseModel):
    """Boundary model rejecting unknown fields and attribute reassignment."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class SchemaNotStrictError(ValueError):
    """A schema has defaults, optional properties, or an open object."""


def strict_json_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Return the model schema only when all nested object properties are required.

    Args:
        model: Pydantic model used as an agent's output contract.

    Raises:
        SchemaNotStrictError: An object permits extra fields or omits required properties,
            or any schema node supplies a default.
    """
    schema = model.model_json_schema()
    _check_schema(schema, "$")
    return schema


def _check_schema(node: dict[str, Any], path: str) -> None:
    if "default" in node:
        raise SchemaNotStrictError(f"{path}: defaults are forbidden")
    if node.get("type") == "object" or "properties" in node:
        if node.get("additionalProperties") is not False:
            raise SchemaNotStrictError(f"{path}: additionalProperties must be false")
        if not set(node.get("properties", {})).issubset(node.get("required", [])):
            raise SchemaNotStrictError(f"{path}: every property must be required")
    for key in ("$defs", "properties", "patternProperties", "dependentSchemas"):
        for name, child in node.get(key, {}).items():
            _check_schema(child, f"{path}.{key}.{name}")
    for key in ("anyOf", "oneOf", "allOf", "prefixItems"):
        for index, child in enumerate(node.get(key, [])):
            _check_schema(child, f"{path}.{key}[{index}]")
    for key in ("items", "not", "if", "then", "else", "contains", "propertyNames"):
        child = node.get(key)
        if isinstance(child, dict):
            _check_schema(child, f"{path}.{key}")
