"""Recoverable initial checkpoint, exact leased push, and atomic draft identity."""

from __future__ import annotations

from typing import Any

from langgraph.runtime import Runtime

from lgcw.github.render import PrStatus, render_event, render_pr_body
from lgcw.graph.context import RunContext
from lgcw.graph.nodes.common import attention, finish_command, labels, observe, post_once, sanitized
from lgcw.ledger.markers import fingerprint, render_marker
from lgcw.models.ledger import BootstrapMarker, PushMarker, RunMarker, SetupMarker
from lgcw.models.state import RunState


async def open_pr(state: RunState, runtime: Runtime[RunContext]) -> dict[str, Any]:
    """Journal before effects and verify exact remote/local identities on every re-entry."""
    ctx = runtime.context
    if state.issue is None or state.intake is None or state.intake.status != "ok":
        return attention("intake_missing", "Accepted issue criteria are missing.", "intake")
    branch = f"lgcw/issue-{ctx.issue_ref.number}"
    pr = await ctx.github.find_pr(ctx.issue_ref.repo, branch)
    if pr is not None and pr.state != "OPEN":
        return {"pr": pr, "next_step": "end", "outcome": "closed"}
    obs = await observe(ctx, pr)
    previous = obs.ledger.latest("bootstrap")
    journal = previous.marker if previous and isinstance(previous.marker, BootstrapMarker) else None
    if pr is not None and journal is None:
        return attention(
            "bootstrap_evidence_missing",
            "This branch has a PR but no bootstrap journal; inspect ownership.",
            "open_pr",
        )
    run_entry = obs.ledger.latest("run")
    old_run = run_entry.marker if run_entry and isinstance(run_entry.marker, RunMarker) else None
    info = await ctx.workspace.prepare(ctx.repo, ctx.issue_ref, branch)
    remote_before = await ctx.github.branch_head(ctx.issue_ref.repo, branch)
    replacing = bool(info.created and old_run and old_run.initial_sha and remote_before is None)
    base = info.base_sha if replacing else journal.base_sha if journal else info.base_sha
    operation = (
        journal.operation_id
        if journal
        else fingerprint(
            ctx.issue_ref.repo, str(ctx.issue_ref.number), base, state.issue.updated_at.isoformat()
        )
    )
    if replacing and old_run and old_run.initial_sha:
        operation = fingerprint(operation, "recheckpoint", old_run.initial_sha, base)
    intent = BootstrapMarker(
        operation_id=operation, branch=branch, base_sha=base, phase="intent", head_sha=None
    )
    await post_once(ctx, ctx.issue_ref.number, intent, "Initial checkpoint intent.")
    if ctx.repo.setup:
        setup_id = fingerprint(
            operation,
            *ctx.repo.setup,
            str(state.owner_command.comment_id) if state.owner_command else "initial",
        )
        records = [
            entry.marker
            for entry in obs.ledger.of_kind("setup")
            if isinstance(entry.marker, SetupMarker) and entry.marker.operation_id == setup_id
        ]
        result = next((item for item in reversed(records) if item.phase == "complete"), None)
        if result is None:
            if records:
                return attention(
                    "setup_interrupted",
                    "Setup result is unknown. Inspect local state, then retry explicitly.",
                    "open_pr",
                )
            await post_once(
                ctx,
                ctx.issue_ref.number,
                SetupMarker(
                    operation_id=setup_id, phase="intent", code=None, tail=None, fingerprint=None
                ),
                "Setup command intent.",
            )
            measured = await ctx.workspace.run_commands(
                info.repo_dir, ctx.repo.setup, 600, ctx.log.run_dir / f"setup-{setup_id}.log"
            )
            result = sanitized(
                SetupMarker(
                    operation_id=setup_id,
                    phase="complete",
                    code=measured.code,
                    tail=None,
                    fingerprint=measured.fingerprint,
                )
            )
            await post_once(ctx, ctx.issue_ref.number, result, "Measured setup result.")
        if result.code != 0:
            return attention(
                "setup_failed",
                "Setup failed; inspect its measured output and retry when corrected.",
                "open_pr",
            )
    head = await ctx.workspace.head_sha()
    if await ctx.workspace.changed_paths(head):
        return attention(
            "setup_dirty",
            "Bootstrap workspace has changes. Preserve and inspect them before retrying.",
            "open_pr",
        )
    message = (
        f"lgcw: initialize issue #{ctx.issue_ref.number} [skip ci]\n\nLGCW-Operation: {operation}"
    )
    if head == base:
        if (
            old_run
            and old_run.initial_sha is not None
            and (old_run.operation_id == operation or remote_before is not None)
        ):
            return attention(
                "local_head_changed",
                "Recorded checkpoint is missing from an existing local branch.",
                "open_pr",
            )
        head = await ctx.workspace.commit_empty(message)
    elif (
        await ctx.workspace.commit_message(head)
    ).strip() != message or await ctx.workspace.diff_text(base, head, 1):
        return attention(
            "unexpected_local_head",
            "Local bootstrap head is not the recorded empty checkpoint.",
            "open_pr",
        )
    if (
        old_run
        and old_run.initial_sha is not None
        and old_run.initial_sha != head
        and (old_run.operation_id == operation or remote_before is not None)
    ):
        return attention(
            "local_head_changed", "Local checkpoint differs from its recorded identity.", "open_pr"
        )
    run = sanitized(
        RunMarker(
            issue=f"{ctx.issue_ref.repo}#{ctx.issue_ref.number}",
            branch=branch,
            base_sha=base,
            snapshot=state.issue,
            criteria=state.intake.acceptance_criteria,
            initial_sha=head,
            operation_id=operation,
            owner_answer=state.owner_answer,
        )
    )
    body = (
        render_pr_body(
            state.issue, None, PrStatus(checklist=(), ci="Not run", review="Not run", notes=())
        )
        + "\n\n"
        + render_marker(run)
    )
    if len(body) > 60000 or len(render_event("Run identity and frozen intake.", run)) > 60000:
        return attention(
            "record_too_large",
            "The canonical run record exceeds the service bound; split the issue.",
            "open_pr",
        )
    await post_once(ctx, ctx.issue_ref.number, run, "Run identity and frozen intake.")
    remote = await ctx.github.branch_head(ctx.issue_ref.repo, branch)
    if remote is None:
        await ctx.workspace.push(branch, None, ctx.push_auth())
    elif remote != head:
        return attention(
            "head_moved",
            "Remote head changed. Inspect and restore the checkpoint before retrying.",
            "open_pr" if pr is None else "reconcile",
        )
    pr = pr or await ctx.github.create_draft_pr(
        ctx.issue_ref.repo, branch, ctx.repo.default_branch, state.issue.title, body
    )
    if pr.head_sha != head:
        return attention("head_moved", "PR head differs from the initial checkpoint.", "reconcile")
    await post_once(ctx, pr.number, run, "Run identity and frozen intake.")
    await post_once(
        ctx,
        pr.number,
        PushMarker(head_sha=head, source="initial", round=0),
        "Initial checkpoint published.",
    )
    await labels(
        ctx, pr.number, ("lgcw:active",), ("lgcw:waiting", "lgcw:blocked", "lgcw:merge-ready")
    )
    await labels(ctx, ctx.issue_ref.number, (), ("lgcw:waiting",))
    await post_once(
        ctx,
        ctx.issue_ref.number,
        BootstrapMarker(
            operation_id=operation,
            branch=branch,
            base_sha=base,
            phase="complete",
            head_sha=head,
            pr_number=pr.number,
        ),
        "Bootstrap complete.",
    )
    await finish_command(ctx, state.model_copy(update={"pr": pr}), ctx.issue_ref.number)
    refreshed = await observe(ctx, pr)
    return {
        "ledger": refreshed.ledger,
        "threads": refreshed.threads,
        "pr": pr,
        "branch": branch,
        "base_sha": base,
        "owner_command": None,
        "next_step": "build",
    }
