"""Content-bound, exact-leased commit/push recovery with a canonical handoff body."""

from __future__ import annotations

from typing import Any

from langgraph.runtime import Runtime

from lgcw.github.render import PrStatus, render_pr_body
from lgcw.graph.context import RunContext
from lgcw.graph.nodes.common import attention, finish_command, observe, post_once
from lgcw.graph.nodes.work import latest_build, latest_gate, latest_publish, load_work
from lgcw.ledger.markers import fingerprint, render_marker
from lgcw.models.ledger import PublishMarker, PushMarker, RunMarker
from lgcw.models.state import RunState
from lgcw.runlog import redact


async def publish(state: RunState, runtime: Runtime[RunContext]) -> dict[str, Any]:
    """Recover exact local commits/remote heads before creating any commit, push or receipt."""
    ctx = runtime.context
    state, _ = await load_work(state, ctx)
    if state.pr is None or state.issue is None or state.intake is None:
        raise ValueError("publication requires the frozen issue and PR")
    if state.pr.state != "OPEN":
        return {"outcome": "closed", "next_step": "end"}
    build = latest_build(state)
    if build is None or build.phase != "complete" or build.handoff is None:
        return attention(
            "build_evidence_missing", "Publication requires a durable validated handoff.", "build"
        )
    gate = latest_gate(state, build.operation_id)
    if gate is None or gate.phase != "complete" or gate.code != 0 or gate.feedback is not None:
        return attention(
            "gate_evidence_missing", "Publication requires a measured successful gate.", "gate"
        )
    parent = build.parent_sha
    if gate.tree_fingerprint != await ctx.workspace.worktree_fingerprint(parent):
        return attention(
            "workspace_changed", "Work changed after gate; nothing was published.", "build"
        )
    operation = fingerprint("publish", build.operation_id)
    proposed = latest_publish(state, build.operation_id)
    push = state.ledger.last_push()
    if push is None:
        raise ValueError("publication has no prior push")
    remote = await ctx.github.branch_head(ctx.issue_ref.repo, state.pr.head_ref)
    allowed_heads = {parent}
    if proposed is not None and proposed.head_sha is not None:
        allowed_heads.add(proposed.head_sha)
    if remote not in allowed_heads or state.pr.head_sha not in allowed_heads:
        return attention("head_moved", "Remote/PR head changed before publication.", "reconcile")
    if proposed is None:
        proposed = PublishMarker(
            operation_id=operation,
            build_id=build.operation_id,
            parent_sha=parent,
            head_sha=None,
            phase="intent",
            source=build.publish_source or build.source,
            round=push.round + 1,
        )
        await post_once(ctx, state.pr.number, proposed, "Publication commit intent.")
    head = await ctx.workspace.head_sha()
    trailers = {
        "LGCW-Issue": f"{ctx.issue_ref.repo}#{ctx.issue_ref.number}",
        "LGCW-Operation": operation,
        "LGCW-Parent": parent,
    }
    if proposed.phase == "intent":
        if head == parent:
            committed = await ctx.workspace.commit_all(
                "lgcw: " + redact(state.issue.title).splitlines()[0], trailers
            )
            if committed is None:
                return attention("no_changes", "No unpublished change remains to commit.", "build")
            head = committed
        else:
            message = await ctx.workspace.commit_message(head)
            if not all(
                f"{key}: {value}" in message.splitlines() for key, value in trailers.items()
            ):
                return attention(
                    "local_head_changed",
                    "Local commit lacks the exact publication operation.",
                    "build",
                )
        proposed = proposed.model_copy(update={"phase": "committed", "head_sha": head})
        await post_once(ctx, state.pr.number, proposed, "Publication commit retained.")
    elif head != proposed.head_sha:
        return attention(
            "local_head_changed", "Local head differs from the journaled commit.", "build"
        )
    if await ctx.workspace.commit_fingerprint(parent, head) != gate.tree_fingerprint:
        return attention(
            "workspace_changed",
            "Committed bytes differ from the measured gate; "
            "inspect the preserved unpublished commit.",
            "build",
        )
    if await ctx.workspace.changed_paths(head):
        return attention(
            "workspace_changed", "Local work changed after commit; nothing was pushed.", "build"
        )
    remote = await ctx.github.branch_head(ctx.issue_ref.repo, state.pr.head_ref)
    if remote == parent:
        observed = await ctx.workspace.push(state.pr.head_ref, parent, ctx.push_auth())
        if observed != head:
            raise ValueError("push response differs from the committed head")
    elif remote != head:
        return attention("head_moved", "Remote head moved at the publication lease.", "reconcile")
    pr = await ctx.github.get_pr(ctx.issue_ref.repo, state.pr.number)
    if pr.head_sha != head:
        return attention(
            "head_moved",
            "PR head changed after publication; inspect before continuing.",
            "reconcile",
        )
    await post_once(
        ctx,
        pr.number,
        PushMarker(head_sha=head, source=proposed.source, round=proposed.round),
        "Workflow commit published with its exact lease.",
    )
    run = next(
        (
            entry.marker
            for entry in reversed(state.ledger.entries)
            if isinstance(entry.marker, RunMarker)
        ),
        None,
    )
    if run is None:
        raise ValueError("publication run identity missing")
    body = render_pr_body(
        state.issue,
        build.handoff,
        PrStatus(
            checklist=tuple((criterion, False) for criterion in state.intake.acceptance_criteria),
            ci="pending for " + head,
            review="pending",
            notes=("Repository gate passed in code.",),
        ),
    )
    body_run = run.model_copy(
        update={"body_operation_id": operation, "body_head_sha": head, "body_step": "publish"}
    )
    body = redact(body) + "\n\n" + render_marker(body_run)
    if len(body) > 60000:
        return attention(
            "handoff_too_large", "Canonical PR body exceeds the service bound.", "publish"
        )
    document = await ctx.github.get_pr_document(ctx.issue_ref.repo, pr.number)
    if document.body != body:
        await ctx.github.update_pr_body(ctx.issue_ref.repo, pr.number, body)
    ctx.log.posted("pr_body", body, {"number": pr.number, "head_sha": head})
    await post_once(
        ctx,
        pr.number,
        proposed.model_copy(update={"phase": "complete"}),
        "Publication effects observed complete.",
    )
    await finish_command(ctx, state, pr.number)
    obs = await observe(ctx, pr)
    return {
        "pr": pr,
        "ledger": obs.ledger,
        "handoff": build.handoff,
        "owner_command": None,
        "next_step": "ci_wait",
    }
