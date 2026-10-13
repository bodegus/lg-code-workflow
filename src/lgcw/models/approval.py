"""Content-bound approval of an explicitly enumerated protected-path proposal."""

from __future__ import annotations

from lgcw.models.base import Strict


class ProtectedApproval(Strict):
    """An authenticated approve answer bound to a particular question's exact proposal."""

    paths: tuple[str, ...]
    tree_fingerprint: str
