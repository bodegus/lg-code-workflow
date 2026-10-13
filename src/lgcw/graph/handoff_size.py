"""Bound untrusted agent prose before creating its durable completion record."""

from __future__ import annotations

from typing import Any

from lgcw.models.handoff import BuildHandoff

# These are machine identities or enum values, never safe to shorten for display.
_IDENTITIES = frozenset(
    {"path", "paths", "finding_id", "status", "result", "decision", "criterion"}
)


def fit_handoff(handoff: BuildHandoff) -> BuildHandoff | None:
    """Clip explanatory prose, preserving every path/id/list item, or reject an unfit record."""
    if len(handoff.model_dump_json()) <= 45000:
        return handoff

    def bounded(value: Any, limit: int, key: str = "") -> Any:
        if isinstance(value, str):
            return (
                value
                if key in _IDENTITIES or len(value) <= limit
                else value[:limit] + " [... agent prose truncated; full output retained locally]"
            )
        if isinstance(value, dict):
            return {name: bounded(item, limit, name) for name, item in value.items()}
        if isinstance(value, list):
            return [bounded(item, limit, key) for item in value]
        return value

    for limit in (4096, 2048, 1024, 512, 128):
        result = BuildHandoff.model_validate(bounded(handoff.model_dump(), limit))
        if len(result.model_dump_json()) <= 45000:
            return result
    return None
