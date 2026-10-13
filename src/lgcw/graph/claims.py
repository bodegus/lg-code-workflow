"""Pure checks of builder claims and bounded fresh-thread selection."""

from __future__ import annotations

import fnmatch
import hashlib
from collections.abc import Mapping, Sequence

from lgcw.models.base import Strict
from lgcw.models.config import RepoConfig
from lgcw.models.handoff import BuildHandoff
from lgcw.models.harness import Usage
from lgcw.models.state import Feedback, PendingAsk


class ClaimsResult(Strict):
    """An independently checked result, never the builder's self-assessment."""

    ok: bool
    feedback: Feedback | None
    ask: PendingAsk | None


def check_claims(
    handoff: BuildHandoff, changed: Sequence[str], repo: RepoConfig, issue_body: str
) -> ClaimsResult:
    """Check completion, actual changed paths and explicit protected-path scope."""
    if handoff.status != "done":
        questions = (
            "; ".join(handoff.open_questions or handoff.not_done) or "clarify remaining scope"
        )
        return ClaimsResult(
            ok=False,
            feedback=None,
            ask=PendingAsk(
                code="handoff_incomplete",
                question=f"Builder returned {handoff.status}: {questions}",
                return_to="build",
            ),
        )
    protected = [
        path
        for path in changed
        if any(fnmatch.fnmatchcase(path, pattern) for pattern in repo.protected_globs)
        and path not in issue_body
    ]
    if protected:
        return ClaimsResult(
            ok=False,
            feedback=None,
            ask=PendingAsk(
                code="protected_path",
                question="Changes touch protected paths not explicitly named in the issue: "
                + ", ".join(protected),
                return_to="build",
            ),
        )
    claimed = {note.path for note in handoff.files}
    code = "no_changes" if not changed else "claims_mismatch" if claimed != set(changed) else None
    if code is not None:
        summary = (
            "Builder claimed done but made no changes."
            if code == "no_changes"
            else "Handoff file paths do not match the independently observed git diff."
        )
        return ClaimsResult(
            ok=False,
            ask=None,
            feedback=Feedback(
                source="no_changes" if code == "no_changes" else "gate",
                summary=summary,
                data=f"actual paths: {sorted(set(changed))}; claimed paths: {sorted(claimed)}",
                fingerprint=hashlib.sha256(code.encode()).hexdigest()[:16],
            ),
        )
    return ClaimsResult(ok=True, feedback=None, ask=None)


def should_restart_builder(
    usage: Usage | None,
    fingerprints: Sequence[str],
    restarts_by_cause: Mapping[str, int],
    ratio: float,
) -> str | None:
    """Select an unused restart cause from repeated evidence or measured context occupancy."""
    cause: str | None = None
    if len(fingerprints) >= 2 and fingerprints[-1] == fingerprints[-2]:
        cause = "failure:" + fingerprints[-1]
    elif usage is not None and usage.context_window is not None:
        context = usage.context_input_tokens
        if context is None:  # legacy/fake Usage records before D-034
            context = usage.input_tokens
        if context > ratio * usage.context_window:
            cause = "context"
    return cause if cause is not None and restarts_by_cause.get(cause, 0) == 0 else None
