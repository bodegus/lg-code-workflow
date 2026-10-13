"""Deterministic acceptance-criteria extraction from issue data."""

from __future__ import annotations

import pytest

from lgcw.intake import extract_acceptance_criteria


@pytest.mark.unit
@pytest.mark.parametrize(
    "body,expected",
    [
        (
            "## Acceptance criteria\n- release 0.1.1\n- CLI matches\n## Notes\n- later",
            ("release 0.1.1", "CLI matches"),
        ),
        ("### Done when\n1. first\n2. second", ("first", "second")),
        ("## Definition of Done\n- [ ] one\n- [x] two", ("one", "two")),
        (
            "## Expected\nThe CLI reports the canonical release.",
            ("The CLI reports the canonical release.",),
        ),
        ("Other text\n- [ ] fallback\n- [x] already done", ("fallback",)),
        ("No criteria here", ()),
        ("## Acceptance criteria\n\n## Later\n- not criteria", ()),
        ("```md\n## Acceptance criteria\n- fake\n```\n- [ ] real", ("real",)),
    ],
)
def test_extract_acceptance_criteria(body: str, expected: tuple[str, ...]) -> None:
    assert extract_acceptance_criteria(body) == expected
