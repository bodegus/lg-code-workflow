"""Pure selection of the next step from authenticated durable facts."""

from __future__ import annotations

from lgcw.models.base import Step, Strict
from lgcw.models.github import PrSnapshot, ReviewThread
from lgcw.models.issue import IssueSnapshot
from lgcw.models.ledger import AckMarker, AskMarker, Command, FindingMarker, PrLedger, ReadyMarker
from lgcw.models.state import PendingAsk


class ReconcileView(Strict):
    """Authenticated observations supplied by the code-only reconcile node."""

    issue: IssueSnapshot | None
    pr: PrSnapshot | None
    ledger: PrLedger
    threads: tuple[ReviewThread, ...]
    commands: tuple[Command, ...]


class ReconcileOutcome(Strict):
    """A next step and any authorized continuation or owner question."""

    step: Step
    command: Command | None
    ask: PendingAsk | None
    reason: str


def next_step(view: ReconcileView) -> ReconcileOutcome:
    """Reconstruct the next step without trusting local state or unmarked reviewer prose."""

    def route(step: Step, reason: str, command: Command | None = None) -> ReconcileOutcome:
        return ReconcileOutcome(step=step, reason=reason, command=command, ask=None)

    def ask(code: str, question: str, return_to: Step = "reconcile") -> ReconcileOutcome:
        return ReconcileOutcome(
            step="ask",
            command=None,
            reason=code,
            ask=PendingAsk(code=code, question=question, return_to=return_to),
        )

    ledger, pr = view.ledger, view.pr
    if pr is not None and pr.state != "OPEN":
        return route("end", "closed")
    if ledger.latest("blocked") is not None:
        return route("end", "blocked")
    pending = ledger.pending_ask()
    if pending is not None and isinstance(pending.marker, AskMarker):
        acknowledged = {
            entry.marker.command_id
            for entry in ledger.of_kind("ack")
            if isinstance(entry.marker, AckMarker)
        }
        command = next(
            (
                item
                for item in sorted(view.commands, key=lambda item: item.comment_id)
                if item.comment_id > pending.comment_id and item.comment_id not in acknowledged
            ),
            None,
        )
        if command is None:
            return route("end", "waiting")
        return route(
            "blocked" if command.verb == "abort" else pending.marker.step, "owner command", command
        )
    if pr is None:
        return route("intake", "no PR")
    push = ledger.last_push()
    if push is None:
        return ask(
            "unowned_pr", "This PR has no recorded workflow-owned push. Confirm how to adopt it."
        )
    if pr.head_sha != push.head_sha:
        return ask(
            "head_moved",
            "The PR head changed outside the workflow. Retry to adopt the current head.",
        )
    ready = ledger.latest("ready")
    if (
        ready is not None
        and isinstance(ready.marker, ReadyMarker)
        and ready.marker.head_sha == pr.head_sha
    ):
        return route("end", "merge_ready")
    ci = ledger.ci_for(push.head_sha)
    if ci is None:
        return route(
            "build" if push.source == "initial" else "ci_wait", "latest push has no CI decision"
        )
    if ci.action == "fix":
        return route("build", "CI requires a fix")
    if ci.action in {"wait", "rerun"}:
        return route("ci_wait", "CI must be observed again")
    if ci.action == "ask":
        return ask(
            "ci_attention",
            f"CI needs owner attention ({ci.status}, {ci.klass or 'unknown class'}).",
            "ci_wait",
        )
    reviews = ledger.reviews_for(push.head_sha)
    if not reviews:
        return route("review", "CI permits review")
    findings = {
        entry.comment_id
        for entry in ledger.entries
        if entry.where == "thread" and isinstance(entry.marker, FindingMarker)
    }
    reported = [
        thread
        for thread in view.threads
        if any(comment.id in findings for comment in thread.comments)
    ]
    if any(not thread.is_resolved for thread in reported):
        return route("build", "unresolved blocking findings")
    if reviews[-1].blocking and not reported:
        return ask(
            "review_evidence_missing",
            "Review reports blockers but its finding threads are missing.",
            "review",
        )
    return route("merge_ready", "review has no unresolved blockers")
