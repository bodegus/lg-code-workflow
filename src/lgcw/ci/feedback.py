"""Bound failure evidence before serializing its durable escaped JSON marker."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from lgcw.ci.logs import clean_evidence
from lgcw.ledger.markers import render_marker
from lgcw.models.ci import CiDecision
from lgcw.models.github import JobView, RunView
from lgcw.models.ledger import FeedbackMarker
from lgcw.models.state import Feedback


def _clip(text: str, cap: int) -> str:
    return text.encode()[: max(0, cap)].decode(errors="ignore")


def failure_feedback(
    decision: CiDecision,
    failing: Sequence[JobView],
    tails: Mapping[int, str],
    runs: Sequence[RunView],
) -> Feedback:
    """Reserve log space per job, cap annotations and measure the actual marker."""
    selected_id = decision.job.job_id if decision.job else None
    ordered = sorted(failing, key=lambda job: job.job_id != selected_id)
    pieces: list[str] = []
    remaining = 16384
    for job in ordered:
        cap = min(8191, remaining - (1 if pieces else 0))
        if cap < 1024:
            break
        header = _clip(
            clean_evidence(
                f"Workflow: {job.workflow}; job: {job.name}; conclusion: {job.conclusion}\n"
            ),
            512,
        )
        annotation_cap = min(2048, max(0, cap - len(header.encode()) - 526))
        annotation = _clip(clean_evidence("\n".join(job.annotations)), annotation_cap)
        prefix = header + "Annotations: " + annotation + "\n"
        log = clean_evidence(tails.get(job.job_id, ""))
        log_cap = cap - len(prefix.encode())
        if len(log.encode()) > log_cap:
            omission = "\n[... omitted ...]\n"
            size = (log_cap - len(omission)) // 2
            log = _clip(log, size) + omission + log.encode()[-size:].decode(errors="ignore")
        text = prefix + log
        pieces.append(text)
        remaining -= len(text.encode()) + (1 if len(pieces) > 1 else 0)
    if not pieces:
        pieces = [
            _clip(
                clean_evidence(
                    "\n".join(
                        f"Workflow: {run.workflow}; path: {run.workflow_path}; "
                        f"startup error: {run.startup_error or run.conclusion}"
                        for run in runs
                        if run.conclusion == "startup_failure"
                    )
                ),
                8192,
            )
        ]
    feedback = Feedback(
        source="ci", summary=decision.note, data="\n".join(pieces), fingerprint=decision.fingerprint
    )
    while (
        len(render_marker(FeedbackMarker(head_sha=decision.head_sha, feedback=feedback))) >= 59000
    ):
        pieces = [_clip(piece, max(0, len(piece.encode()) - 256)) for piece in pieces]
        feedback = feedback.model_copy(update={"data": "\n".join(pieces)})
    return feedback
