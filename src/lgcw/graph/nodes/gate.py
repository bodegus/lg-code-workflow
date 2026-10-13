"""Measured repository gate with write-ahead command journal and exact-content receipts."""

from __future__ import annotations

from typing import Any

from langgraph.runtime import Runtime

from lgcw.graph.claims import check_claims
from lgcw.graph.context import RunContext
from lgcw.graph.nodes.common import attention, finish_command, observe, post_once
from lgcw.graph.nodes.work import current_parent, latest_build, latest_gate, load_work
from lgcw.ledger.markers import fingerprint
from lgcw.models.ledger import GateMarker
from lgcw.models.state import Feedback, RunState


async def gate(state: RunState, runtime: Runtime[RunContext]) -> dict[str, Any]:
    """Run trusted commands once per observed intent and bind success to actual file content."""
    ctx = runtime.context
    state, info = await load_work(state, ctx)
    if state.pr is not None and state.pr.state != "OPEN":
        return {"pr": state.pr, "outcome": "closed", "next_step": "end"}
    if info is None:
        raise ValueError("owned workspace missing")
    if state.pr is None or state.issue is None:
        raise ValueError("gate has no PR/intake")
    parent = await current_parent(state, ctx)
    if parent is None:
        return attention("head_moved", "Head changed before gate; retry to adopt it.", "reconcile")
    build = latest_build(state, parent)
    if build is None or build.phase != "complete" or build.handoff is None:
        return attention(
            "build_evidence_missing", "Gate requires a complete builder handoff.", "build"
        )
    command_id = state.owner_command.comment_id if state.owner_command else 0
    operation = fingerprint("gate", build.operation_id, str(command_id))
    previous = latest_gate(state, build.operation_id)
    if previous is not None and previous.phase == "complete":
        if previous.tree_fingerprint != await ctx.workspace.worktree_fingerprint(parent):
            return attention(
                "workspace_changed",
                "Work changed after its measured gate; inspect and retry.",
                "build",
            )
        return {
            "handoff": build.handoff,
            "feedback": previous.feedback,
            "next_step": "publish" if previous.code == 0 and previous.feedback is None else "build",
        }
    if previous is not None and previous.operation_id == operation:
        return attention(
            "gate_unknown",
            "Gate dispatch has no measured result. Inspect its local log "
            "and retry explicitly to authorize another command run.",
            "gate",
        )
    if await ctx.workspace.head_sha() != parent:
        return attention("local_head_changed", "Committed local HEAD changed before gate.", "build")
    before_tree = await ctx.workspace.worktree_fingerprint(parent)
    if previous is None and before_tree != build.tree_fingerprint:
        return attention(
            "workspace_changed",
            "Work content changed after the builder receipt; inspect and retry.",
            "build",
        )
    claims = check_claims(
        build.handoff,
        await ctx.workspace.changed_paths(parent),
        ctx.repo,
        state.issue.body + "\n" + (state.owner_answer or ""),
    )
    if claims.ask is not None:
        return {"ask": claims.ask, "next_step": "ask"}
    if claims.feedback is not None:
        return {"feedback": claims.feedback, "next_step": "build"}
    intent = GateMarker(
        operation_id=operation,
        build_id=build.operation_id,
        parent_sha=parent,
        phase="intent",
        code=None,
        fingerprint=None,
        tree_fingerprint=None,
        feedback=None,
    )
    await post_once(ctx, state.pr.number, intent, "Repository gate intent.")
    result = await ctx.workspace.run_commands(
        info.repo_dir,
        ctx.repo.gate,
        ctx.config.limits.build_run_timeout_s,
        ctx.log.run_dir / f"gate-{operation}.log",
    )
    if await ctx.workspace.head_sha() != parent:
        return attention(
            "local_head_changed", "Gate changed committed HEAD; preserve and inspect.", "build"
        )
    claims = check_claims(
        build.handoff,
        await ctx.workspace.changed_paths(parent),
        ctx.repo,
        state.issue.body + "\n" + (state.owner_answer or ""),
    )
    after_tree = await ctx.workspace.worktree_fingerprint(parent)
    feedback = (
        None
        if result.ok
        else Feedback(
            source="gate",
            summary="Repository gate failed: " + result.command,
            data=result.tail,
            fingerprint=result.fingerprint,
        )
    )
    if before_tree != after_tree:
        feedback = Feedback(
            source="gate",
            summary="Repository gate changed content; a new build and stable gate are required.",
            data=result.tail,
            fingerprint=fingerprint("gate_changed_content"),
        )
    if claims.feedback is not None:
        feedback = claims.feedback
    if claims.ask is not None:
        feedback = Feedback(
            source="gate",
            summary=claims.ask.question,
            data=None,
            fingerprint=fingerprint(claims.ask.code),
        )
    receipt = intent.model_copy(
        update={
            "phase": "complete",
            "code": result.code,
            "fingerprint": feedback.fingerprint if feedback else None,
            "feedback": feedback,
            "tree_fingerprint": after_tree,
        }
    )
    await post_once(
        ctx, state.pr.number, receipt, "Repository gate measured: exit " + str(result.code)
    )
    ctx.log.event(
        "gate_result",
        node="gate",
        operation_id=operation,
        code=result.code,
        duration_s=result.duration_s,
        log_path=str(result.log_path),
    )
    await finish_command(ctx, state, state.pr.number)
    obs = await observe(ctx, state.pr)
    fields = {
        "ledger": obs.ledger,
        "handoff": build.handoff,
        "feedback": feedback,
        "owner_command": None,
    }
    if claims.ask is not None:
        return fields | {"ask": claims.ask, "next_step": "ask"}
    return fields | {"next_step": "publish" if result.ok and feedback is None else "build"}
