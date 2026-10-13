"""Idempotent owner questions and observed waiting-label repair."""

from __future__ import annotations

from typing import Any

from langgraph.runtime import Runtime

from lgcw.graph.context import RunContext
from lgcw.graph.nodes.common import labels, observe, post_once
from lgcw.models.ledger import AskMarker
from lgcw.models.state import PendingAsk, RunState


async def ask(state: RunState, runtime: Runtime[RunContext]) -> dict[str, Any]:
    """Publish one question before ending; a lost response is recovered by its marker."""
    ctx = runtime.context
    pr = state.pr or await ctx.github.find_open_pr(
        ctx.issue_ref.repo, f"lgcw/issue-{ctx.issue_ref.number}"
    )
    obs = await observe(ctx, pr)
    question = state.ask or PendingAsk(
        code="unknown", question="Inspect the run and provide direction.", return_to="reconcile"
    )
    pending = obs.ledger.pending_ask()
    if (
        pending is not None
        and isinstance(pending.marker, AskMarker)
        and (
            pending.marker.code == question.code
            and pending.marker.step == question.return_to
            and pending.marker.protected_paths == question.protected_paths
            and pending.marker.tree_fingerprint == question.tree_fingerprint
        )
    ):
        marker = pending.marker
    else:
        sequences = [
            entry.marker.seq
            for entry in obs.ledger.of_kind("ask")
            if isinstance(entry.marker, AskMarker)
        ]
        marker = AskMarker(
            seq=max(sequences, default=0) + 1,
            step=question.return_to,
            code=question.code,
            protected_paths=question.protected_paths,
            tree_fingerprint=question.tree_fingerprint,
            supersedes=(pending.marker.seq,)
            if pending and isinstance(pending.marker, AskMarker)
            else (),
        )
    number = pr.number if pr is not None else ctx.issue_ref.number
    await post_once(ctx, number, marker, question.question, question=True)
    await labels(ctx, number, ("lgcw:waiting",), ("lgcw:active", "lgcw:merge-ready"))
    return {"pr": pr, "next_step": "end", "outcome": "waiting"}
