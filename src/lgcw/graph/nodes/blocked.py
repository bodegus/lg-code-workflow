"""Durable terminal stop without merges, pushes or repeated comments."""

from __future__ import annotations

from typing import Any

from langgraph.runtime import Runtime

from lgcw.graph.context import RunContext
from lgcw.graph.nodes.common import finish_command, labels, observe, post_once
from lgcw.models.ledger import BlockedMarker
from lgcw.models.state import RunState


async def blocked(state: RunState, runtime: Runtime[RunContext]) -> dict[str, Any]:
    """Persist a stop reason and repair labels after a potentially interrupted write."""
    ctx = runtime.context
    pr = state.pr or await ctx.github.find_open_pr(
        ctx.issue_ref.repo, f"lgcw/issue-{ctx.issue_ref.number}"
    )
    obs = await observe(ctx, pr)
    prior = obs.ledger.latest("blocked")
    reason = state.ask.question if state.ask else "Owner aborted the workflow."
    marker = (
        prior.marker
        if prior is not None and isinstance(prior.marker, BlockedMarker)
        else BlockedMarker(reason=reason)
    )
    number = pr.number if pr else ctx.issue_ref.number
    await post_once(ctx, number, marker, reason)
    await labels(
        ctx, number, ("lgcw:blocked",), ("lgcw:active", "lgcw:waiting", "lgcw:merge-ready")
    )
    await finish_command(ctx, state, ctx.issue_ref.number)
    return {"pr": pr, "next_step": "end", "outcome": "blocked"}
