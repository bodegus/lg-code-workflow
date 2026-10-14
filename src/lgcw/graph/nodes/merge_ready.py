"""Recheck actual published content and current CI before once-only readiness writes."""

from __future__ import annotations

import asyncio
from typing import Any

from langgraph.runtime import Runtime

from lgcw.ci.classify import classify, latest_runs, owned_runs
from lgcw.ci.observe import effective_required
from lgcw.github.render import PrStatus, render_pr_body
from lgcw.graph.context import RunContext
from lgcw.graph.nodes.common import attention, finish_command, labels, post_once
from lgcw.graph.nodes.work import current_parent, latest_gate, load_work
from lgcw.ledger.markers import fingerprint, render_marker
from lgcw.models.ledger import BuildMarker, ReadyMarker, RunMarker
from lgcw.models.state import RunState
from lgcw.runlog import redact


async def merge_ready(state: RunState, runtime: Runtime[RunContext]) -> dict[str, Any]:
    """Mark an exact, reviewed, green head ready; never invoke a merge operation."""
    ctx = runtime.context
    state, info = await load_work(state, ctx)
    pr = state.pr
    if pr is not None and pr.state != "OPEN":
        return {"pr": pr, "next_step": "end", "outcome": "closed"}
    if info is None or pr is None or state.issue is None or state.intake is None:
        raise ValueError("readiness requires frozen intake and an owned PR")
    head = await current_parent(state, ctx)
    if head is None:
        return attention("head_moved", "Head changed before readiness.", "reconcile")
    reviews = state.ledger.reviews_for(head)
    if not reviews or reviews[-1].blocking or reviews[-1].result is None:
        return attention(
            "review_evidence_missing", "No completed nonblocking prototype review.", "review"
        )
    build = next(
        (
            entry.marker
            for entry in reversed(state.ledger.entries)
            if isinstance(entry.marker, BuildMarker) and entry.marker.handoff is not None
        ),
        None,
    )
    if build is None:
        return attention("build_evidence_missing", "No completed build receipt.", "build")
    gate = latest_gate(state, build.operation_id)
    if gate is None or gate.phase != "complete" or gate.code != 0 or gate.feedback is not None:
        return attention("gate_evidence_missing", "No passing content-bound gate.", "gate")
    if (
        await ctx.workspace.commit_fingerprint(build.parent_sha, head) != gate.tree_fingerprint
        or await ctx.workspace.worktree_fingerprint(build.parent_sha) != gate.tree_fingerprint
    ):
        return attention(
            "workspace_changed", "Published/local bytes differ from the measured gate.", "build"
        )
    candidates = await ctx.github.runs_for_sha(ctx.issue_ref.repo, head, pr)
    owners = await ctx.github.open_prs_for_head(ctx.issue_ref.repo, pr.head_ref)
    if (
        len(owners) != 1
        or owners[0].number != pr.number
        or any(len(run.pull_requests) > 1 for run in candidates)
    ):
        return attention("ci_ownership_ambiguous", "CI head has ambiguous PR ownership.", "ci_wait")
    runs = latest_runs(owned_runs(candidates, ctx.issue_ref.repo, pr), head)
    batches = await asyncio.gather(
        *(ctx.github.jobs_for_run(ctx.issue_ref.repo, run.run_id) for run in runs)
    )
    jobs = tuple(job for batch in batches for job in batch)
    if len(jobs) > 200:
        return attention(
            "ci_evidence_limit", "CI aggregate exceeds the observation bound.", "ci_wait"
        )
    contexts = await ctx.github.required_check_contexts(ctx.issue_ref.repo, pr.base_ref)
    required = effective_required(ctx.repo.required_checks, contexts, runs, jobs)
    push_entry = next(entry for entry in reversed(state.ledger.of_kind("push")))
    status, _ = classify(
        required, runs, jobs, pr, head, push_entry.created_at, ctx.clock.now(), ctx.config.limits
    )
    if status != "success":
        return attention(
            "ci_not_green", f"Readiness requires current exact-head green CI ({status}).", "ci_wait"
        )
    current = await ctx.github.get_pr(ctx.issue_ref.repo, pr.number)
    if (
        current.head_sha != head
        or await ctx.github.branch_head(ctx.issue_ref.repo, pr.head_ref) != head
    ):
        return attention(
            "head_moved", "Head changed during the final readiness checks.", "reconcile"
        )
    if current.mergeable != "MERGEABLE":
        return attention(
            "pr_not_mergeable", f"PR mergeability is {current.mergeable}.", "merge_ready"
        )
    latest_issue = await ctx.github.get_issue(ctx.issue_ref)
    notes = ["Repository gate, current CI and prototype review completed in code."]
    if latest_issue.body != state.issue.body or latest_issue.title != state.issue.title:
        notes.append("Issue changed after pickup; this run used the frozen issue snapshot.")
    run = next(
        entry.marker
        for entry in reversed(state.ledger.entries)
        if isinstance(entry.marker, RunMarker)
    )
    receipt = run.model_copy(
        update={
            "snapshot": None,
            "criteria": (),
            "owner_answer": None,
            "body_operation_id": fingerprint(head, "merge_ready"),
            "body_head_sha": head,
            "body_step": "merge_ready",
        }
    )
    suffix = "\n\n" + render_marker(receipt)
    body = (
        redact(
            render_pr_body(
                state.issue,
                build.handoff,
                PrStatus(
                    checklist=tuple(
                        (criterion, True) for criterion in state.intake.acceptance_criteria
                    ),
                    ci="green on " + head,
                    review=f"{reviews[-1].level}: no blocking findings",
                    notes=tuple(notes),
                ),
                max_chars=60000 - len(suffix),
            )
        )
        + suffix
    )
    document = await ctx.github.get_pr_document(ctx.issue_ref.repo, pr.number)
    if document.body != body:
        await ctx.github.update_pr_body(ctx.issue_ref.repo, pr.number, body)
    if current.is_draft:
        await ctx.github.mark_ready(pr.node_id)
    current = await ctx.github.get_pr(ctx.issue_ref.repo, pr.number)
    if (
        current.head_sha != head
        or await ctx.github.branch_head(ctx.issue_ref.repo, pr.head_ref) != head
    ):
        return attention("head_moved", "Head changed during readiness writes.", "reconcile")
    await labels(
        ctx, pr.number, ("lgcw:merge-ready",), ("lgcw:active", "lgcw:waiting", "lgcw:blocked")
    )
    await post_once(
        ctx,
        pr.number,
        ReadyMarker(head_sha=head),
        "Merge-ready on this exact head. " + " ".join(notes),
    )
    await finish_command(ctx, state, pr.number)
    return {"next_step": "end", "outcome": "merge_ready", "owner_command": None}
