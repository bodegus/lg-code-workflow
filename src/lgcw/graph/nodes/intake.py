"""Freeze a valid issue and explicit acceptance criteria before bootstrap work."""

from __future__ import annotations

from typing import Any

from langgraph.runtime import Runtime

from lgcw.github.render import render_event
from lgcw.graph.context import RunContext
from lgcw.graph.nodes.common import attention, finish_command, observe, post_once, sanitized
from lgcw.intake import extract_acceptance_criteria
from lgcw.models.issue import IntakeResult
from lgcw.models.ledger import IntakeMarker
from lgcw.models.state import RunState


async def intake(state: RunState, runtime: Runtime[RunContext]) -> dict[str, Any]:
    """Reject unsupported issues; retain the original snapshot and owner-supplied criteria."""
    ctx = runtime.context
    current = await ctx.github.get_issue(ctx.issue_ref)
    if (
        current.state.casefold() != "open"
        or current.is_pull_request
        or current.author not in ctx.repo.allowed_authors
    ):
        result = attention(
            "issue_rejected",
            "Issue is closed, a pull request, or from an unauthorized author.",
            "intake",
        )
        result["next_step"] = "blocked"
        return result
    obs = await observe(ctx, state.pr)
    previous = obs.ledger.latest("intake")
    marker = (
        previous.marker
        if previous is not None and isinstance(previous.marker, IntakeMarker)
        else None
    )
    original = marker.snapshot if marker is not None else sanitized(current)
    criteria = marker.criteria if marker is not None else extract_acceptance_criteria(original.body)
    if not criteria and state.owner_answer:
        criteria = extract_acceptance_criteria(state.owner_answer) or (state.owner_answer.strip(),)
    canonical = sanitized(
        IntakeMarker(
            snapshot=original,
            criteria=criteria,
            command_id=(
                marker.command_id
                if marker and marker.criteria == criteria
                else state.owner_command.comment_id
                if state.owner_command
                else None
            ),
        )
    )
    if len(render_event("Issue snapshot and acceptance criteria.", canonical)) > 60000:
        return attention(
            "record_too_large",
            "The issue is too large to record safely. Split it into a bounded issue.",
            "intake",
        )
    await post_once(ctx, ctx.issue_ref.number, canonical, "Issue snapshot and acceptance criteria.")
    if not criteria:
        return {
            **attention(
                "missing_criteria", "Provide acceptance criteria with /lgcw answer.", "intake"
            ),
            "issue": original,
            "intake": IntakeResult(
                status="incomplete", acceptance_criteria=(), reason="missing criteria"
            ),
        }
    await finish_command(ctx, state, ctx.issue_ref.number)
    return {
        "issue": canonical.snapshot,
        "intake": IntakeResult(status="ok", acceptance_criteria=canonical.criteria, reason=None),
        "owner_command": None,
        "next_step": "open_pr",
    }
