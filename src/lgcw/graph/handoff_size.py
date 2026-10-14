"""Bound untrusted agent prose before creating its durable completion record."""

from __future__ import annotations

import json
from typing import Any

from lgcw.ledger.markers import render_marker
from lgcw.models.handoff import BuildHandoff
from lgcw.models.ledger import BuildMarker

# These are machine identities or enum values, never safe to shorten for display.
_IDENTITIES = frozenset(
    {"path", "paths", "finding_id", "status", "result", "decision", "criterion"}
)


def fit_handoff(
    handoff: BuildHandoff, *, receipt: BuildMarker | None = None
) -> BuildHandoff | None:
    """Clip explanatory prose, preserving every path/id/list item, or reject an unfit record."""

    def measured(value: BuildHandoff) -> int:
        if receipt is not None:
            return len(render_marker(receipt.model_copy(update={"handoff": value})))
        return len(
            json.dumps(value.model_dump(mode="json"), ensure_ascii=True, separators=(",", ":"))
        )

    if measured(handoff) <= 45000:
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
        if measured(result) <= 45000:
            return result
    return None
