"""Location, priority, confidence and stable finding deduplication."""

from __future__ import annotations

from pathlib import Path

import pytest

from lgcw.models.review import (
    CodeLocation,
    LensVerdict,
    LevelDecision,
    LineRange,
    ReviewFinding,
    ReviewLevel,
    ReviewVerdict,
)
from lgcw.review.gate import finding_id, gate_findings


def verdict(
    root: Path,
    *,
    priority: int = 1,
    confidence: float = 0.9,
    category: str = "correctness",
    start: int = 3,
    end: int = 3,
    path: str = "src/a.py",
) -> LensVerdict:
    """Return one synthetic review finding."""
    finding = ReviewFinding(
        title="[P1] Handle missing record",
        body="A missing record raises.",
        confidence_score=confidence,
        priority=priority,
        category=category,
        code_location=CodeLocation(
            absolute_file_path=str(root / path), line_range=LineRange(start=start, end=end)
        ),
    )
    return LensVerdict(
        lens="general",
        verdict=ReviewVerdict(
            findings=[finding],
            overall_correctness="patch is incorrect",
            overall_explanation="missing input case",
            overall_confidence_score=0.9,
        ),
    )


def level(name: ReviewLevel) -> LevelDecision:
    """Return the expected lens set for the tested depth."""
    return LevelDecision(
        level=name,
        lenses=("general", "security", "tests") if name == "deep" else ("general",),
        reasons=(),
        fix_round_cap=2,
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    "depth,priority,confidence,category,blocking",
    [
        ("none", 0, 1.0, "security", False),
        ("light", 1, 0.9, "correctness", True),
        ("light", 1, 0.6, "correctness", False),
        ("light", 1, 0.7, "correctness", True),
        ("standard", 2, 0.9, "correctness", False),
        ("standard", 1, 0.6, "correctness", True),
        ("deep", 2, 0.9, "security", True),
        ("standard", 2, 0.9, "security", False),
        ("deep", 3, 1.0, "security", False),
    ],
)
def test_finding_policy(
    tmp_path: Path,
    depth: ReviewLevel,
    priority: int,
    confidence: float,
    category: str,
    blocking: bool,
) -> None:
    result = gate_findings(
        [verdict(tmp_path, priority=priority, confidence=confidence, category=category)],
        level(depth),
        {"src/a.py": [LineRange(start=2, end=5)]},
        tmp_path,
        (),
    )
    assert len(result.blocking) == int(blocking)
    assert len(result.nonblocking) == int(not blocking)


@pytest.mark.unit
@pytest.mark.parametrize(
    "path,start,end",
    [
        ("src/a.py", 6, 6),
        ("src/a.py", 1, 3),
        ("../outside.py", 3, 3),
        ("src/../../outside.py", 3, 3),
        ("other.py", 3, 3),
    ],
)
def test_invalid_locations_drop(tmp_path: Path, path: str, start: int, end: int) -> None:
    result = gate_findings(
        [verdict(tmp_path, path=path, start=start, end=end)],
        level("standard"),
        {"src/a.py": [LineRange(start=2, end=5)]},
        tmp_path,
        (),
    )
    assert not result.blocking and not result.nonblocking and len(result.dropped) == 1


@pytest.mark.unit
def test_known_and_duplicate_findings_are_not_repeated(tmp_path: Path) -> None:
    item = verdict(tmp_path)
    key = finding_id("src/a.py", item.verdict.findings[0].title, "correctness")
    ranges = {"src/a.py": [LineRange(start=1, end=10)]}
    known = gate_findings([item], level("standard"), ranges, tmp_path, [key])
    assert not known.blocking and len(known.dropped) == 1
    duplicate = gate_findings([item, item], level("standard"), ranges, tmp_path, ())
    assert len(duplicate.blocking) == 1 and len(duplicate.dropped) == 1


@pytest.mark.unit
def test_finding_identity_normalises_title_not_path() -> None:
    key = finding_id("src/a.py", "[P1] Handle  Missing Record", "Correctness")
    assert key == finding_id("src/a.py", "[P0] handle missing record", "correctness")
    assert key != finding_id("src/B.py", "handle missing record", "correctness")


@pytest.mark.unit
def test_relative_checkout_root_is_rejected() -> None:
    with pytest.raises(ValueError, match="absolute"):
        gate_findings([], level("standard"), {}, Path("relative"), ())


@pytest.mark.unit
def test_unrequested_lens_is_dropped(tmp_path: Path) -> None:
    item = verdict(tmp_path).model_copy(update={"lens": "security"})
    result = gate_findings(
        [item], level("light"), {"src/a.py": [LineRange(start=1, end=10)]}, tmp_path, ()
    )
    assert not result.blocking and result.dropped[0].reason == "lens was not requested"
