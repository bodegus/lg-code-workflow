"""Resolve only controller-owned packaged skills, never target-repository names."""

from __future__ import annotations

from pathlib import Path

_NAMES = frozenset({"build", "fix", "review", "review-security", "review-tests", "verify-finding"})


def skill_path(name: str) -> Path:
    """Return an exact installed skill path, rejecting traversal or unknown names.

    Raises:
        ValueError: The name is outside the packaged allowlist.
        FileNotFoundError: The installed package is incomplete.
    """
    if name not in _NAMES:
        raise ValueError("unknown packaged workflow skill")
    path = Path(__file__).resolve().parents[1] / "skills" / name / "SKILL.md"
    if not path.is_file():
        raise FileNotFoundError(f"packaged skill missing: {name}")
    return path
