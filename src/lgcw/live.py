"""Explicit opt-in guard for adapters that can reach real services."""

from __future__ import annotations

import os


class LiveAdapterDisabledError(RuntimeError):
    """A live adapter was reached without explicit authority."""


def require_live(component: str, allow_live: bool) -> None:
    """Refuse real service access unless the CLI or live lane explicitly enables it."""
    if not allow_live and os.environ.get("LGCW_LIVE") != "1":
        raise LiveAdapterDisabledError(f"{component} requires CLI authority or LGCW_LIVE=1")
