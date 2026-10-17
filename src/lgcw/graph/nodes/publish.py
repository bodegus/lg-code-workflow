"""Content-bound, exact-leased commit/push recovery with a canonical handoff body."""

from __future__ import annotations

from typing import Any

from langgraph.runtime import Runtime

from lgcw.github.render import PrStatus, render_pr_body
from lgcw.graph.context import RunContext
from lgcw.graph.nodes.common import attention, finish_command, observe, post_once
from lgcw.graph.nodes.work import (
    check_work_claims,
    claims_interruption,
    latest_build,
    latest_gate,
    latest_publish,
    load_work,
)
from lgcw.graph.retry import retry_ask
from lgcw.ledger.markers import fingerprint, render_marker
from lgcw.models.handoff import BuildHandoff
from lgcw.models.ledger import PublishMarker, PushMarker, RunMarker
from lgcw.models.state import Feedback, PendingAsk, RunState
from lgcw.runlog import redact


def publication_body(state: RunState, handoff: BuildHandoff, operation: str, head: str) -> str:
    """Fit view and compact receipt to one service bound before publication effects."""
    if state.issue is None or state.intake is None:
        raise ValueError("publication body requires frozen intake")
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
    body_run = run.model_copy(
        update={
            "snapshot": None,
            "criteria": (),
            "owner_answer": None,
            "body_operation_id": operation,
            "body_head_sha": head,
            "body_step": "publish",
        }
    )
    suffix = "\n\n" + render_marker(body_run)
    body = render_pr_body(
        state.issue,
        handoff,
        PrStatus(
            checklist=tuple((criterion, False) for criterion in state.intake.acceptance_criteria),
            ci="pending for " + head,
            review="pending",
            notes=("Repository gate passed in code.",),
        ),
        max_chars=60000 - len(suffix),
    )
    body = redact(body) + suffix
    return body


async def workspace_question(
    state: RunState, ctx: RunContext, parent: str, *, committed: bool
) -> dict[str, Any]:
    """Show exact changed content before asking for a destructive local restoration."""
    tree = await ctx.workspace.worktree_fingerprint(parent)
    return {
        "ask": PendingAsk(
            code="workspace_changed",
            return_to="publish" if committed else "build",
            tree_fingerprint=tree,
            question="Work differs from the measured gate; nothing new was pushed. "
            + (
                "Retry preserves the candidate and dirty tracked work under recovery refs, "
                "then restores "
                "the exact journaled commit (or its parent for a fresh build "
                "if commit audit failed). "
                "Untracked files are refused and must be preserved/removed by the owner first. "
                if committed
                else "Inspect preserved edits and retry for a new build. "
            )
            + "Observed content fingerprint: "
            + tree,
        ),
        "next_step": "ask",
    }


async def restore_publication(
    state: RunState, ctx: RunContext, proposed: PublishMarker, gate_tree: str
) -> tuple[PublishMarker, dict[str, Any] | None]:
    """Recover only an explicitly authorized reset and preserve all known local commits."""
    if state.pr is None or proposed.head_sha is None:
        raise ValueError("restore requires an exact candidate")
    question = retry_ask(state)
    retry = question is not None and question.code == "workspace_changed"
    if proposed.phase == "abandoned":
        return proposed, {
            "feedback": Feedback(
                source="rebuild",
                summary="Rebuild from the restored published parent; "
                "the rejected candidate is preserved.",
                data=None,
                fingerprint=None,
            ),
            "next_step": "build",
        }
    if (
        retry
        and state.owner_command is not None
        and proposed.reset_command_id != state.owner_command.comment_id
    ):
        current_tree = await ctx.workspace.worktree_fingerprint(proposed.parent_sha)
        if question is None or current_tree != question.tree_fingerprint:
            return proposed, await workspace_question(
                state, ctx, proposed.parent_sha, committed=True
            )
        candidate_tree = await ctx.workspace.commit_fingerprint(
            proposed.parent_sha, proposed.head_sha
        )
        proposed = proposed.model_copy(
            update={
                "phase": "reset_intent",
                "reset_to": proposed.head_sha
                if candidate_tree == gate_tree
                else proposed.parent_sha,
                "reset_command_id": state.owner_command.comment_id,
                "reset_tree_fingerprint": current_tree,
            }
        )
        await post_once(
            ctx,
            state.pr.number,
            proposed,
            "Owner-authorized local restore intent; exact candidate/parent and content frozen.",
        )
    if proposed.phase != "reset_intent":
        return proposed, None
    target = proposed.reset_to
    if target is None:
        raise ValueError("restore intent lacks exact target")
    head = await ctx.workspace.head_sha()
    already_restored = head == target and not await ctx.workspace.changed_paths(target)
    if not already_restored:
        if (
            await ctx.workspace.worktree_fingerprint(proposed.parent_sha)
            != proposed.reset_tree_fingerprint
        ):
            return proposed, await workspace_question(
                state, ctx, proposed.parent_sha, committed=True
            )
        candidate = proposed.head_sha
        if candidate is None:
            raise ValueError("restore lost candidate identity")
        try:
            await ctx.workspace.restore_owned_commit(
                candidate, target, proposed.operation_id, proposed.parent_sha
            )
        except ValueError as error:
            return proposed, attention(
                "local_head_changed", "Local restore refused: " + str(error), "publish"
            )
    proposed = proposed.model_copy(
        update={"phase": "abandoned" if target == proposed.parent_sha else "committed"}
    )
    await post_once(
        ctx,
        state.pr.number,
        proposed,
        "Local restore observed; candidate and tracked work remain recoverable.",
    )
    if proposed.phase == "abandoned":
        obs = await observe(ctx, state.pr)
        return proposed, {
            "ledger": obs.ledger,
            "feedback": Feedback(
                source="rebuild",
                summary="Rebuild from the restored published parent; "
                "the rejected candidate is preserved.",
                data=None,
                fingerprint=None,
            ),
            "next_step": "build",
        }
    return proposed, None


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
    head = await ctx.workspace.head_sha()
    trailers = {
        "LGCW-Issue": f"{ctx.issue_ref.repo}#{ctx.issue_ref.number}",
        "LGCW-Operation": operation,
        "LGCW-Parent": parent,
    }
    # A lost commit response is recovered even when later uncommitted work changed.
    if proposed is not None and proposed.phase == "intent" and head != parent:
        message = await ctx.workspace.commit_message(head)
        if not all(
            f"{key}: {value}" in message.splitlines() for key, value in trailers.items()
        ) or await ctx.workspace.commit_parents(head) != (parent,):
            return attention(
                "local_head_changed", "Local commit lacks the exact publication operation.", "build"
            )
        proposed = proposed.model_copy(update={"phase": "committed", "head_sha": head})
        await post_once(
            ctx,
            state.pr.number,
            proposed,
            "Publication commit recovered before content restoration.",
        )
    if gate.tree_fingerprint is None:
        raise ValueError("successful gate lacks content evidence")
    if proposed is not None and proposed.phase in {"committed", "reset_intent", "abandoned"}:
        proposed, restored = await restore_publication(state, ctx, proposed, gate.tree_fingerprint)
        if restored is not None:
            return restored
        head = await ctx.workspace.head_sha()
    if gate.tree_fingerprint != await ctx.workspace.worktree_fingerprint(parent):
        return await workspace_question(
            state, ctx, parent, committed=proposed is not None and proposed.head_sha is not None
        )
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
            ) or await ctx.workspace.commit_parents(head) != (parent,):
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
        return await workspace_question(state, ctx, parent, committed=True)
    if await ctx.workspace.changed_paths(head):
        return await workspace_question(state, ctx, parent, committed=True)
    remote = await ctx.github.branch_head(ctx.issue_ref.repo, state.pr.head_ref)
    if remote == parent:
        claims = await check_work_claims(state, ctx, build.handoff, parent)
        interrupted = await claims_interruption(claims, state, ctx)
        if interrupted is not None:
            return interrupted
        if claims.ask is not None:
            return {"ask": claims.ask, "next_step": "ask"}
        observed = await ctx.workspace.push(
            state.pr.head_ref, parent, ctx.push_auth(), head_sha=head
        )
        if observed != head:
            raise ValueError("push response differs from the committed head")
    elif remote != head:
        return attention("head_moved", "Remote head moved at the publication lease.", "reconcile")
    started = ctx.clock.now()
    delay = 1.0
    while True:
        pr = await ctx.github.get_pr(ctx.issue_ref.repo, state.pr.number)
        remote = await ctx.github.branch_head(ctx.issue_ref.repo, state.pr.head_ref)
        if remote != head or pr.head_sha not in {parent, head}:
            return attention("head_moved", "Remote/PR head changed after publication.", "reconcile")
        if pr.head_sha == head:
            break
        remaining = 10.0 - (ctx.clock.now() - started).total_seconds()
        if remaining <= 0:
            return attention(
                "head_moved", "PR head did not converge within 10 seconds.", "reconcile"
            )
        await ctx.clock.sleep(min(delay, remaining))
        delay = min(delay * 2, 4.0)
    await post_once(
        ctx,
        pr.number,
        PushMarker(head_sha=head, source=proposed.source, round=proposed.round),
        "Workflow commit published with its exact lease.",
    )
    body = publication_body(state, build.handoff, operation, head)
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
