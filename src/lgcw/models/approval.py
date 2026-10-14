"""Content-bound approval of an explicitly enumerated protected-path proposal."""

from __future__ import annotations

from lgcw.models.base import Strict
from lgcw.models.ledger import Command


class ProtectedApproval(Strict):
    """An authenticated approve answer bound to a particular question's exact proposal."""

    paths: tuple[str, ...]
    tree_fingerprint: str


class ApprovalRevocation(Strict):
    """A later authenticated command cancelling an earlier question's permission."""

    seq: int
    command: Command
