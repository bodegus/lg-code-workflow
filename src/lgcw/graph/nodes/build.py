"""Journaled paid builder dispatch, recoverable handoffs and bounded fresh-thread policy."""

from __future__ import annotations

from typing import Any

from langgraph.runtime import Runtime

from lgcw.graph.claims import check_claims, should_restart_builder
from lgcw.graph.context import RunContext
from lgcw.graph.nodes.common import attention, finish_command, observe, post_once, sanitized
from lgcw.graph.nodes.work import current_parent, latest_build, latest_gate, load_work
from lgcw.harness.errors import (
    HarnessAuthError,
    HarnessError,
    HarnessQuotaError,
    HarnessSessionLostError,
)
from lgcw.harness.prompts import render_build_turn, render_fix_turn, render_restart_turn
from lgcw.ledger.markers import fingerprint
from lgcw.models.handoff import BuildHandoff
from lgcw.models.harness import SessionRef, SessionSpec
from lgcw.models.ledger import BuildMarker, BuildSource, FeedbackMarker, GateMarker, SessionMarker
from lgcw.models.review import GatedFinding
from lgcw.models.state import Feedback, RunState


def _error_code(error: str) -> str:
    return {
        "HarnessAuthError": "harness_auth",
        "HarnessQuotaError": "harness_quota",
        "HarnessSessionLostError": "harness_session_lost",
    }.get(error, "harness_error")


async def build(state: RunState, runtime: Runtime[RunContext]) -> dict[str, Any]:
    """Resume known completed work; never replay an unknown paid dispatch without owner retry."""
    ctx = runtime.context
    state, info = await load_work(state, ctx)
    if state.pr is not None and state.pr.state != "OPEN":
        return {"pr": state.pr, "outcome": "closed", "next_step": "end"}
    if info is None:
        raise ValueError("owned workspace missing")
    if state.pr is None or state.issue is None or state.intake is None:
        raise ValueError("frozen build input missing")
    number = state.pr.number
    parent = await current_parent(state, ctx)
    if parent is None:
        return attention(
            "head_moved", "The PR/remote head changed before builder dispatch.", "reconcile"
        )
    previous = latest_build(state, parent)
    command_id = state.owner_command.comment_id if state.owner_command else None
    feedback = state.feedback
    handoff = state.handoff
    findings: tuple[GatedFinding, ...] = ()
    recorded_feedback = next(
        (
            entry.marker
            for entry in reversed(state.ledger.entries)
            if isinstance(entry.marker, FeedbackMarker) and entry.marker.head_sha == parent
        ),
        None,
    )
    if recorded_feedback:
        feedback, findings = recorded_feedback.feedback, recorded_feedback.findings
    completed = [
        entry.marker
        for entry in state.ledger.entries
        if isinstance(entry.marker, BuildMarker)
        and entry.marker.phase == "complete"
        and entry.marker.handoff is not None
    ]
    if completed:
        handoff = completed[-1].handoff
    if previous is not None:
        authorized_new = command_id is not None and command_id != previous.command_id
        if previous.phase == "intent" and not authorized_new:
            return attention(
                "build_unknown",
                "A paid build dispatch has no durable result. "
                "Inspect its Codex rollout; retry explicitly to authorize a new operation.",
                "build",
            )
        if previous.error is not None and not authorized_new:
            return attention(
                _error_code(previous.error),
                "Previous builder attempt failed with "
                + previous.error
                + "; repair the login/quota/session and retry explicitly.",
                "build",
            )
        if previous.phase == "complete" and previous.handoff is not None and not authorized_new:
            handoff = previous.handoff
            gate = latest_gate(state, previous.operation_id)
            if gate is not None and gate.phase == "intent":
                return {"handoff": handoff, "ledger": state.ledger, "next_step": "gate"}
            expected_tree = (
                gate.tree_fingerprint
                if gate and gate.phase == "complete"
                else (previous.tree_fingerprint)
            )
            if expected_tree != await ctx.workspace.worktree_fingerprint(parent):
                return attention(
                    "workspace_changed",
                    "Local work differs from the recorded build/gate. "
                    "Inspect preserved edits and retry explicitly.",
                    "build",
                )
            if gate is None or gate.phase == "intent":
                if previous.feedback is None:
                    return {"handoff": handoff, "ledger": state.ledger, "next_step": "gate"}
                feedback = previous.feedback
            elif gate.code == 0 and gate.feedback is None:
                return {"handoff": handoff, "ledger": state.ledger, "next_step": "publish"}
            else:
                feedback = gate.feedback
        elif authorized_new:
            prior_gate = latest_gate(state, previous.operation_id)
            preserved = (
                prior_gate.feedback
                if prior_gate and prior_gate.phase == "complete"
                else (previous.feedback)
            )
            feedback = (
                preserved
                or feedback
                or Feedback(
                    source="owner",
                    summary="Owner authorized continuation.",
                    data=state.owner_answer,
                    fingerprint=None,
                )
            )
    if feedback is None and state.ledger.ci_for(parent) is not None:
        ci = state.ledger.ci_for(parent)
        if ci is not None and ci.action == "fix":
            feedback = Feedback(
                source="ci",
                summary="Current-head CI requires a fix.",
                data=None,
                fingerprint=ci.fingerprint,
            )
    source: BuildSource = "build"
    if feedback is not None:
        source = (
            "ci_fix"
            if feedback.source == "ci"
            else ("review_fix" if feedback.source == "review" else "gate_fix")
        )
    publish_source = source
    if source == "gate_fix" and previous is not None:
        origin = previous.publish_source or previous.source
        if origin in {"ci_fix", "review_fix"}:
            publish_source = origin
    counts = state.ledger.counts()
    grants = counts.retry_grants.get("build", {})
    if (
        source == "gate_fix"
        and counts.gate_fix_rounds
        >= ctx.config.limits.gate_fix_rounds + grants.get("gate_fix_limit", 0)
    ):
        return attention(
            "gate_fix_limit", "The bounded gate/no-change fix allowance is exhausted.", "build"
        )
    sessions = [
        entry.marker
        for entry in state.ledger.entries
        if isinstance(entry.marker, SessionMarker) and entry.marker.role == "builder"
    ]
    current = sessions[-1] if sessions else None
    causes: dict[str, int] = {}
    for session in sessions:
        if session.cause is not None:
            causes[session.cause] = causes.get(session.cause, 0) + 1
    failures = [
        entry.marker.feedback.fingerprint
        for entry in state.ledger.entries
        if isinstance(entry.marker, (BuildMarker, GateMarker))
        and entry.marker.parent_sha == parent
        and entry.marker.phase == "complete"
        and entry.marker.feedback is not None
        and entry.marker.feedback.fingerprint is not None
    ]
    usage = completed[-1].usage if completed else None
    cause = should_restart_builder(usage, failures, {}, ctx.config.limits.context_restart_ratio)
    unused_restart = (
        current is not None
        and current.cause == cause
        and not any(
            isinstance(entry.marker, BuildMarker) and entry.marker.session_id == current.session_id
            for entry in state.ledger.entries
        )
    )
    if (
        cause is not None
        and not unused_restart
        and causes.get(cause, 0) >= 1 + grants.get("builder_restart_limit", 0)
    ):
        return attention(
            "builder_restart_limit",
            "The same fresh-builder cause recurred after its allowed restart: " + cause,
            "build",
        )
    fresh_reason = cause if cause is not None and not unused_restart else None
    for session_attempt in range(2):
        if current is None or fresh_reason is not None:
            ref = await ctx.harness.start_session(
                SessionSpec(
                    role="builder",
                    cwd=info.repo_dir,
                    sandbox="workspace_write",
                    network=True,
                    effort=ctx.config.builder_effort,
                    model=ctx.config.model,
                )
            )
            current = SessionMarker(
                role="builder",
                session_id=ref.session_id,
                reason="initial" if not sessions else "fresh_restart",
                cause=fresh_reason,
            )
            await post_once(ctx, number, current, "Builder session selected.")
            sessions.append(current)
        ref = SessionRef(session_id=current.session_id, role="builder")
        obs = await observe(ctx, state.pr)
        seq = (
            len(
                {
                    entry.marker.operation_id
                    for entry in obs.ledger.entries
                    if isinstance(entry.marker, BuildMarker)
                }
            )
            + 1
        )
        operation = fingerprint("build", parent, str(seq), str(command_id), ref.session_id)
        intent = BuildMarker(
            operation_id=operation,
            parent_sha=parent,
            session_id=ref.session_id,
            source=source,
            publish_source=publish_source,
            phase="intent",
            command_id=command_id,
            handoff=None,
            usage=None,
            tree_fingerprint=None,
            feedback=None,
            error=None,
        )
        if await ctx.workspace.head_sha() != parent:
            return attention(
                "local_head_changed", "Local HEAD changed before builder dispatch.", "build"
            )
        await post_once(ctx, number, intent, "Builder dispatch intent.")
        if fresh_reason is not None or (session_attempt and fresh_reason == "session_lost"):
            turn = render_restart_turn(
                state.issue, state.intake.acceptance_criteria, handoff, findings, feedback
            )
        elif feedback is not None:
            turn = render_fix_turn(
                feedback, state.intake.acceptance_criteria, findings, handoff, state.owner_answer
            )
        else:
            turn = render_build_turn(state.issue, state.intake, ctx.repo, state.owner_answer)
        try:
            outcome = await ctx.harness.run_turn(
                ref, turn, BuildHandoff, heartbeat=runtime.heartbeat
            )
        except HarnessError as exc:
            error_name = type(exc).__name__
            ctx.log.turn(ctx.log.next_turn_seq(), "builder", turn, None, str(exc))
            await post_once(
                ctx,
                number,
                intent.model_copy(update={"phase": "complete", "error": error_name}),
                "Builder attempt failed: " + error_name,
            )
            if (
                isinstance(exc, HarnessSessionLostError)
                and session_attempt == 0
                and causes.get("session_lost", 0) == 0
            ):
                fresh_reason = "session_lost"
                continue
            message = "Builder failed: " + str(exc)
            if isinstance(exc, HarnessAuthError):
                message += "; re-login with the dedicated workflow CODEX_HOME, then retry."
            if isinstance(exc, HarnessQuotaError):
                message += (
                    "; quota resets at " + exc.resets_at.isoformat()
                    if exc.resets_at is not None
                    else "; reset time unavailable; check the dedicated login's usage."
                )
            await finish_command(ctx, state, number)
            return attention(_error_code(error_name), message, "build")
        ctx.log.turn(ctx.log.next_turn_seq(), "builder", turn, outcome, None)
        if await ctx.workspace.head_sha() != parent:
            return attention(
                "local_head_changed",
                "Builder changed committed HEAD; preserve and inspect.",
                "build",
            )
        result = sanitized(outcome.output)
        claims = check_claims(
            result,
            await ctx.workspace.changed_paths(parent),
            ctx.repo,
            state.issue.body + "\n" + (state.owner_answer or ""),
        )
        record = intent.model_copy(
            update={
                "phase": "complete",
                "handoff": result,
                "usage": outcome.usage,
                "feedback": claims.feedback,
                "tree_fingerprint": await ctx.workspace.worktree_fingerprint(parent),
            }
        )
        await post_once(ctx, number, record, "Builder handoff retained; claims checked in code.")
        await finish_command(ctx, state, number)
        obs = await observe(ctx, state.pr)
        fields = {
            "handoff": result,
            "builder_session": ref,
            "ledger": obs.ledger,
            "feedback": claims.feedback,
            "owner_command": None,
        }
        if claims.ask is not None:
            return fields | {"ask": claims.ask, "next_step": "ask"}
        return fields | {"next_step": "gate" if claims.ok else "build"}
    raise HarnessError("unreachable builder session loop")
