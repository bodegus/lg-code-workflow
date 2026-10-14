"""Code-only required-policy binding and ledger-derived CI counters."""

from __future__ import annotations

from collections.abc import Sequence

from lgcw.models.ci import CiClass, CiHistory
from lgcw.models.config import RequiredCheck
from lgcw.models.github import JobView, RunView
from lgcw.models.ledger import CiMarker, PrLedger


def effective_required(
    configured: Sequence[RequiredCheck],
    contexts: Sequence[str],
    runs: Sequence[RunView],
    jobs: Sequence[JobView],
) -> tuple[RequiredCheck, ...]:
    """Bind ruleset names to observed workflow/jobs; unresolved names remain required."""
    pairs = {(check.workflow, check.job) for check in configured}
    for context in contexts:
        found = {(job.workflow, job.name) for job in jobs if job.name == context}
        found.update((check.workflow, check.job) for check in configured if check.job == context)
        # Before the job exists, conservatively include every observed workflow so an
        # approval/startup block cannot be filtered out. Unknown contexts never become green.
        pairs.update(
            found
            | {
                (run.workflow, context)
                for run in runs
                if run.conclusion in {"action_required", "startup_failure"}
                or not any(job.workflow == run.workflow for job in jobs)
            }
            or {("unobserved-required", context)}
        )
    return tuple(RequiredCheck(workflow=workflow, job=job) for workflow, job in sorted(pairs))


def ci_history(ledger: PrLedger) -> CiHistory:
    """Reconstruct total/class-specific reruns and fix counts solely from PR facts."""
    counts = ledger.counts()
    classes: dict[str, dict[CiClass, int]] = {}
    fingerprints: list[str] = []
    for entry in ledger.entries:
        marker = entry.marker
        if isinstance(marker, CiMarker):
            if marker.action == "rerun" and marker.klass is not None:
                head = classes.setdefault(marker.head_sha, {})
                head[marker.klass] = head.get(marker.klass, 0) + 1
            if marker.action == "fix" and marker.fingerprint is not None:
                fingerprints.append(marker.fingerprint)
    return CiHistory(
        reruns_by_head=counts.reruns_by_head,
        reruns_total=counts.reruns_total,
        ci_fix_rounds=counts.ci_fix_rounds,
        fingerprints=tuple(fingerprints),
        reruns_by_class_head=classes,
    )
