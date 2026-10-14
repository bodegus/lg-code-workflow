"""Shared code-only observations for content-bound build and publication journals."""

from __future__ import annotations

from lgcw.git.port import WorkspaceInfo
from lgcw.graph.claims import ClaimsResult, check_claims
from lgcw.graph.context import RunContext
from lgcw.graph.nodes.common import observe
from lgcw.models.approval import ProtectedApproval
from lgcw.models.handoff import BuildHandoff
from lgcw.models.ledger import AckMarker, AskMarker, BuildMarker, GateMarker, PublishMarker
from lgcw.models.state import RunState


async def load_work(state: RunState, ctx: RunContext) -> tuple[RunState, WorkspaceInfo | None]:
    """Refresh the PR ledger and prepare its owned workspace without replacing local edits."""
    if state.pr is None or state.branch is None or state.issue is None or state.intake is None:
        raise ValueError("build requires a journaled PR and frozen intake")
    pr = await ctx.github.get_pr(ctx.issue_ref.repo, state.pr.number)
    obs = await observe(ctx, pr)
    current = state.model_copy(update={"pr": pr, "ledger": obs.ledger, "threads": obs.threads})
    if pr.state != "OPEN":
        return current, None
    info = await ctx.workspace.prepare(ctx.repo, ctx.issue_ref, state.branch)
    return current, info


def latest_build(state: RunState, parent: str | None = None) -> BuildMarker | None:
    """Return the latest journal phase, optionally for the current published parent."""
    return next(
        (
            entry.marker
            for entry in reversed(state.ledger.entries)
            if isinstance(entry.marker, BuildMarker)
            and (parent is None or entry.marker.parent_sha == parent)
        ),
        None,
    )


def latest_gate(state: RunState, build_id: str) -> GateMarker | None:
    """Return the last observed gate phase for an exact build operation."""
    return next(
        (
            entry.marker
            for entry in reversed(state.ledger.entries)
            if isinstance(entry.marker, GateMarker) and entry.marker.build_id == build_id
        ),
        None,
    )


def latest_publish(state: RunState, build_id: str) -> PublishMarker | None:
    """Return the last observed publish phase for an exact build operation."""
    return next(
        (
            entry.marker
            for entry in reversed(state.ledger.entries)
            if isinstance(entry.marker, PublishMarker) and entry.marker.build_id == build_id
        ),
        None,
    )


async def current_parent(state: RunState, ctx: RunContext) -> str | None:
    """Require the last owned push to match both live GitHub branch and PR heads."""
    push = state.ledger.last_push()
    if state.pr is None or push is None or state.pr.state != "OPEN":
        return None
    remote = await ctx.github.branch_head(ctx.issue_ref.repo, state.pr.head_ref)
    return push.head_sha if state.pr.head_sha == remote == push.head_sha else None


async def check_work_claims(
    state: RunState, ctx: RunContext, handoff: BuildHandoff, parent: str
) -> ClaimsResult:
    """Check actual paths and content against the issue or a question-bound owner approval."""
    if state.issue is None:
        raise ValueError("claims require frozen issue")
    approval: ProtectedApproval | None = None
    questions = {
        entry.marker.seq: entry.marker
        for entry in state.ledger.entries
        if isinstance(entry.marker, AskMarker)
    }
    for entry in state.ledger.entries:
        ack = entry.marker
        if not isinstance(ack, AckMarker):
            continue
        question = questions.get(ack.seq)
        if question is None or question.code != "protected_path":
            continue
        # Every later answer/retry supersedes the earlier proposal, including a denial.
        approval = None
        if (
            ack.verb == "answer"
            and ack.command_snapshot is not None
            and ack.command_snapshot.text.strip() == "approve"
            and question.protected_paths
            and question.tree_fingerprint is not None
        ):
            approval = ProtectedApproval(
                paths=question.protected_paths, tree_fingerprint=question.tree_fingerprint
            )
    return check_claims(
        handoff,
        await ctx.workspace.changed_paths(parent),
        ctx.repo,
        state.issue.body,
        tree_fingerprint=await ctx.workspace.worktree_fingerprint(parent),
        approval=approval,
    )
