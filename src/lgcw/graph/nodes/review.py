"""One fresh, bounded prototype reviewer; COMMENT reviews are durable evidence."""

from __future__ import annotations

from typing import Any

from langgraph.runtime import Runtime

from lgcw.github.render import render_event
from lgcw.graph.context import RunContext
from lgcw.graph.nodes.common import attention, finish_command, observe, post_once, sanitized
from lgcw.graph.nodes.work import current_parent, latest_gate, load_work
from lgcw.harness.errors import HarnessError
from lgcw.harness.prompts import ReviewPacket, fence, render_review_turn
from lgcw.ledger.markers import fingerprint
from lgcw.models.harness import SessionSpec
from lgcw.models.ledger import BuildMarker, FeedbackMarker, ReviewMarker, SessionMarker
from lgcw.models.review import GateResult, LensVerdict, LevelDecision, ReviewVerdict
from lgcw.models.state import Feedback, RunState
from lgcw.review.diffstat import parse_numstat
from lgcw.review.gate import gate_findings
from lgcw.review.level import pick_level
from lgcw.review.ranges import reviewed_ranges


async def review(state: RunState, runtime: Runtime[RunContext]) -> dict[str, Any]:
    """Recover submitted reviews, or dispatch once after recording a fresh reviewer intent."""
    ctx = runtime.context
    state, info = await load_work(state, ctx)
    if state.pr is not None and state.pr.state != "OPEN":
        return {"pr": state.pr, "next_step": "end", "outcome": "closed"}
    if info is None or state.pr is None or state.issue is None or state.intake is None:
        raise ValueError("review requires a frozen issue and owned PR")
    head = await current_parent(state, ctx)
    if head is None:
        return attention("head_moved", "Head changed before review.", "reconcile")
    ci = state.ledger.ci_for(head)
    if ci is None or ci.action != "proceed_note":
        return {"next_step": "ci_wait"}
    recorded = state.ledger.reviews_for(head)
    if recorded:
        return await _finish(state, ctx, recorded[-1])
    handoffs = [
        entry.marker
        for entry in state.ledger.entries
        if isinstance(entry.marker, BuildMarker) and entry.marker.handoff is not None
    ]
    if not handoffs or state.base_sha is None:
        return attention("review_evidence_missing", "Build/base evidence is missing.", "review")
    build = handoffs[-1]
    handoff = build.handoff
    assert handoff is not None
    # Reject local edits rather than sizing/reviewing different bytes from the published head.
    if await ctx.workspace.worktree_fingerprint(
        build.parent_sha
    ) != await ctx.workspace.commit_fingerprint(build.parent_sha, head):
        return attention("workspace_changed", "Local content changed before review.", "build")
    diffstat = parse_numstat(
        await ctx.workspace.commit_numstat(state.base_sha, head), ctx.repo.excluded_globs
    )
    order = ("none", "light", "standard", "deep")
    prior = max(
        (
            entry.marker.configured_level or entry.marker.level
            for entry in state.ledger.entries
            if isinstance(entry.marker, ReviewMarker)
        ),
        key=order.index,
        default=None,
    )
    previous = (
        LevelDecision(level=prior, lenses=(), reasons=(), fix_round_cap=2)
        if prior is not None
        else None
    )
    configured = pick_level(
        diffstat,
        state.pr.labels,
        handoff.risks,
        ctx.repo,
        ctx.config.thresholds,
        ctx.config.limits,
        previous=previous,
    )
    level = LevelDecision(
        level="none" if configured.level == "none" else "light",
        lenses=() if configured.level == "none" else ("general",),
        reasons=configured.reasons,
        fix_round_cap=2,
    )
    ctx.log.event("review_level", node="review", configured=configured.level, executed=level.level)
    rounds = _attempts(state)
    if level.level == "none":
        marker = ReviewMarker(
            head_sha=head,
            level="none",
            configured_level=configured.level,
            round=rounds,
            lenses=(),
            blocking=0,
            nonblocking=0,
            review_id=None,
            result=GateResult(blocking=(), nonblocking=(), dropped=()),
        )
        await post_once(
            ctx, state.pr.number, marker, "Review skipped by the configured none policy."
        )
        return await _finish(state, ctx, marker)
    cap = _cap(state)
    if rounds >= cap:
        return attention(
            "review_round_limit", "Two review rounds exhausted; retry grants one more.", "review"
        )
    command_id = state.owner_command.comment_id if state.owner_command else None
    cause = f"review:{head}:{command_id}"
    if any(
        isinstance(entry.marker, SessionMarker)
        and entry.marker.role == "reviewer"
        and entry.marker.cause == cause
        for entry in state.ledger.entries
    ):
        return attention(
            "review_unknown", "Review dispatch has no durable result; inspect then retry.", "review"
        )
    diff = await ctx.workspace.diff_text(state.base_sha, head, 262148)
    if len(diff.encode()) > 262144:
        return attention(
            "review_evidence_limit", "Review diff exceeds the prototype packet bound.", "review"
        )
    try:
        ranges = reviewed_ranges(diff)
    except ValueError as error:
        return attention("review_evidence_missing", str(error), "review")
    checkout = await ctx.workspace.reviewer_checkout(head, state.base_sha)
    gate = latest_gate(state, build.operation_id)
    packet = ReviewPacket(
        issue_title=state.issue.title,
        criteria=state.intake.acceptance_criteria,
        base_sha=state.base_sha,
        head_sha=head,
        range_from=state.base_sha,
        diffstat=diffstat.model_dump_json(),
        level=level,
        lens="general",
        ci_summary=ci.model_dump_json(),
        gate_summary=gate.model_dump_json() if gate else "missing",
        approach=handoff.approach,
        decisions=handoff.decisions,
        assumptions=handoff.assumptions,
        not_done=handoff.not_done,
        risks=handoff.risks,
        files=handoff.files,
        acceptance_evidence=[item.evidence for item in handoff.acceptance],
        open_findings=[],
        do_not_repeat=[],
    )
    turn = render_review_turn(packet)
    turn = turn.model_copy(update={"text": turn.text + "\n\n" + fence(diff, "external-diff")})
    seq = ctx.log.next_turn_seq()
    try:
        session = await ctx.harness.start_session(
            SessionSpec(
                role="reviewer",
                cwd=checkout,
                sandbox="read_only",
                network=False,
                effort=ctx.config.reviewer_effort["light"],
                model=ctx.config.model,
            )
        )
        await post_once(
            ctx,
            state.pr.number,
            SessionMarker(
                role="reviewer",
                session_id=session.session_id,
                reason="initial",
                cause=cause,
            ),
            "Fresh reviewer dispatch intent.",
        )
        outcome = await ctx.harness.run_turn(
            session, turn, ReviewVerdict, heartbeat=runtime.heartbeat
        )
    except HarnessError as error:
        ctx.log.turn(seq, "reviewer", turn, None, type(error).__name__)
        await finish_command(ctx, state, state.pr.number)
        return attention(
            "review_unknown", "Reviewer failed: " + str(error) + "; inspect then retry.", "review"
        )
    ctx.log.turn(seq, "reviewer", turn, outcome, None)
    result = sanitized(
        gate_findings(
            [LensVerdict(lens="general", verdict=outcome.output)], level, ranges, checkout, ()
        )
    )
    unmatched = tuple(
        item
        for item in result.dropped
        if item.finding.priority <= 1 and item.reason != "finding was already reported"
    )
    result = result.model_copy(
        update={
            "blocking": (
                *result.blocking,
                *(
                    item.model_copy(
                        update={
                            "blocking": True,
                            "reason": "unmatched critical finding requires owner inspection",
                        }
                    )
                    for item in unmatched
                ),
            ),
            "dropped": tuple(item for item in result.dropped if item not in unmatched),
        }
    )
    marker = ReviewMarker(
        head_sha=head,
        level="light",
        configured_level=configured.level,
        round=rounds + 1,
        lenses=("general",),
        blocking=len(result.blocking),
        nonblocking=len(result.nonblocking),
        review_id=None,
        result=result,
    )
    if len(render_event("", marker)) > 50000:
        return attention(
            "review_evidence_limit", "Reviewer findings exceed the durable record bound.", "review"
        )
    fresh = await ctx.github.get_pr(ctx.issue_ref.repo, state.pr.number)
    if (
        fresh.head_sha != head
        or await ctx.github.branch_head(ctx.issue_ref.repo, fresh.head_ref) != head
    ):
        return attention("head_moved", "Head changed during review.", "reconcile")
    verdict = sanitized(outcome.output)
    prose = (
        f"Prototype review: configured {configured.level}, executed light.\n\n"
        f"{verdict.overall_correctness}: {verdict.overall_explanation}\n\n"
    )
    prose += (
        "\n\n".join(
            f"{item.id} {item.finding.title}\n{item.path}: {item.finding.body}\n{item.reason}"
            for item in (*result.blocking, *result.nonblocking, *result.dropped)
        )
        or "No actionable findings."
    )
    body = render_event(prose, marker)
    review_id = await ctx.github.create_review(ctx.issue_ref.repo, fresh.number, head, body, ())
    ctx.log.posted("review", body, {"review_id": review_id, "head_sha": head})
    obs = await observe(ctx, fresh)
    return await _finish(state.model_copy(update={"ledger": obs.ledger}), ctx, marker)


def _attempts(state: RunState) -> int:
    return sum(
        isinstance(entry.marker, SessionMarker) and entry.marker.role == "reviewer"
        for entry in state.ledger.entries
    )


def _cap(state: RunState) -> int:
    grants = state.ledger.counts().retry_grants.get("review", {})
    return 2 + grants.get("review_round_limit", 0) + grants.get("review_unknown", 0)


async def _finish(state: RunState, ctx: RunContext, marker: ReviewMarker) -> dict[str, Any]:
    if state.pr is None or marker.result is None:
        return attention("review_evidence_missing", "Review result is missing.", "review")
    await finish_command(ctx, state, state.pr.number)
    if any(
        item.reason == "unmatched critical finding requires owner inspection"
        for item in marker.result.blocking
    ):
        return attention(
            "review_evidence_missing",
            "Critical review location cannot be matched; inspect the recorded findings.",
            "review",
        ) | {"owner_command": None}
    if not marker.blocking:
        return {"owner_command": None, "next_step": "merge_ready"}
    if _attempts(state) >= _cap(state):
        return attention(
            "review_round_limit",
            "Review blockers remain at the round cap; retry grants one round.",
            "review",
        )
    feedback = Feedback(
        source="review",
        summary="Fix the recorded P0/P1 review findings.",
        data=None,
        fingerprint=fingerprint(marker.result.model_dump_json()),
    )
    await post_once(
        ctx,
        state.pr.number,
        FeedbackMarker(
            head_sha=marker.head_sha, feedback=feedback, findings=marker.result.blocking
        ),
        "Blocking review findings returned to the existing builder.",
    )
    return {
        "owner_command": None,
        "feedback": feedback,
        "gated": marker.result,
        "next_step": "build",
    }
