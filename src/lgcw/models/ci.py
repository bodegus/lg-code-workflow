"""CI classifier and decision-table records."""

from __future__ import annotations

from typing import Literal

from lgcw.models.base import Strict
from lgcw.models.github import JobView

type CiStatus = Literal[
    "pending", "success", "failure", "blocked", "missing", "conflict", "head_moved", "timeout"
]
type CiClass = Literal[
    "superseded",
    "awaiting_approval",
    "startup_failure",
    "infra",
    "timeout",
    "resources",
    "flaky",
    "pre_existing",
    "mass_failure",
    "change",
    "unclassified",
]
type CiAction = Literal["wait", "rerun", "fix", "proceed_note", "ask"]


class CiDecision(Strict):
    """A deterministic CI action and its evidence."""

    head_sha: str
    status: CiStatus
    klass: CiClass | None
    action: CiAction
    job: JobView | None
    fingerprint: str | None
    note: str


class CiHistory(Strict):
    """CI counts reconstructed from the PR ledger."""

    reruns_by_head: dict[str, int]
    reruns_total: int
    ci_fix_rounds: int
    fingerprints: tuple[str, ...]
