"""Configuration boundary contracts and limits."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from lgcw.models.config import Limits, ReviewThresholds
from lgcw.models.issue import IssueRef


@pytest.mark.unit
def test_limits_defaults() -> None:
    limits = Limits()
    assert limits.review_fix_rounds == {"none": 0, "light": 1, "standard": 2, "deep": 2}
    assert (limits.gate_fix_rounds, limits.ci_fix_rounds) == (2, 3)
    assert (limits.reruns_per_head, limits.reruns_per_pr) == (2, 5)
    assert (limits.ci_start_grace_s, limits.ci_deadline_s) == (600, 5400)
    assert (limits.poll_initial_s, limits.poll_max_s) == (15, 120)
    assert limits.context_restart_ratio == 0.6
    assert (limits.build_run_timeout_s, limits.build_idle_timeout_s) == (3600, 600)
    assert (limits.review_run_timeout_s, limits.review_idle_timeout_s) == (1200, 300)
    assert (limits.verify_run_timeout_s, limits.verify_idle_timeout_s) == (300, 120)
    assert ReviewThresholds().model_dump() == {
        "light_max_lines": 99,
        "standard_max_lines": 499,
        "many_files": 8,
    }


@pytest.mark.unit
@pytest.mark.parametrize(
    ("field", "value"),
    [("gate_fix_rounds", -1), ("context_restart_ratio", 0), ("context_restart_ratio", 1.1)],
)
def test_limits_reject_unsafe_values(field: str, value: float) -> None:
    with pytest.raises(ValidationError):
        Limits.model_validate({field: value})


@pytest.mark.unit
def test_limit_defaults_are_independent() -> None:
    first, second = Limits(), Limits()
    first.review_fix_rounds["light"] = 5
    assert second.review_fix_rounds["light"] == 1


@pytest.mark.unit
def test_issue_ref_parse() -> None:
    assert IssueRef.parse("bodegus/family-calendar#12") == IssueRef(
        repo="bodegus/family-calendar", number=12
    )


@pytest.mark.unit
@pytest.mark.parametrize("value", ["repo#12", "a/b#0", "a/b#-1", "a/b#x", "a/b", "a/b#1#2"])
def test_issue_ref_rejects_invalid_input(value: str) -> None:
    with pytest.raises(ValueError):
        IssueRef.parse(value)
