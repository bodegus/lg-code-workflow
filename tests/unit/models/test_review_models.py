"""Finding bounds and diff accounting."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from lgcw.models.review import DiffStat, FileChange, LineRange, ReviewFinding


@pytest.mark.unit
@pytest.mark.parametrize(
    "override",
    [{"priority": 4}, {"priority": -1}, {"confidence_score": -0.1}, {"confidence_score": 1.1}],
)
def test_finding_bounds(override: dict[str, Any]) -> None:
    finding = {
        "title": "[P1] Missing guard",
        "body": "Synthetic evidence",
        "confidence_score": 0.9,
        "priority": 1,
        "category": "correctness",
        "code_location": {
            "absolute_file_path": "/synthetic/repo/a.py",
            "line_range": {"start": 1, "end": 2},
        },
    }
    with pytest.raises(ValidationError):
        ReviewFinding.model_validate(finding | override)


@pytest.mark.unit
def test_line_ranges_are_ordered_and_one_based() -> None:
    assert LineRange(start=1, end=1).end == 1
    for start, end in [(0, 1), (2, 1)]:
        with pytest.raises(ValidationError):
            LineRange(start=start, end=end)


@pytest.mark.unit
def test_diffstat_counts_additions_and_deletions() -> None:
    diff = DiffStat(
        files=(
            FileChange(path="a.py", added=4, deleted=2),
            FileChange(path="b.py", added=0, deleted=1),
        )
    )
    assert diff.changed_lines == 7
    assert diff.paths == ("a.py", "b.py")
    assert DiffStat(files=()).changed_lines == 0
