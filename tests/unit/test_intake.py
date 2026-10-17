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
        ("## Done when\n- top\n    - nested\n- second", ("top", "nested", "second")),
        ("- [ ] parent\n    - [ ] child", ("parent", "child")),
        ("- [ ] parent\n\t- [ ] child", ("parent", "child")),
        ("## Expected\n\n    - code\n\n- real", ("real",)),
        ("```html\n<!--\n```\n- [ ] real", ("real",)),
        ("Example `<!--` marker\n- [ ] real", ("real",)),
        ("## Acceptance criteria\n<!-- write criteria below -->", ()),
        ("<!--\n## Acceptance criteria\n- [ ] fake\n-->\n- [ ] real", ("real",)),
        ("## Acceptance criteria\n    - indented code", ()),
        ("    - [ ] indented code\n\t- [ ] tab code", ()),
        ("## Done when\n- real\n<!--\n- fake\n-->\n- second", ("real", "second")),
        ("## Acceptance criteria\n<!-- unfinished placeholder", ()),
        ("## Acceptance criteria\n\n## Later\n- not criteria", ()),
        ("```md\n## Acceptance criteria\n- fake\n```\n- [ ] real", ("real",)),
    ],
)
def test_extract_acceptance_criteria(body: str, expected: tuple[str, ...]) -> None:
    assert extract_acceptance_criteria(body) == expected


@pytest.mark.unit
@pytest.mark.parametrize(
    "body,expected",
    [
        (
            "## Done when\n\n"
            "- [ ] Names refused arguments.\n"
            "- [ ] Documents each operation.\n"
            "- [ ] Tests three invalid shapes.\n\n"
            "After merge and release (reviewer, not builder): perform a live update.\n\n"
            "-reviewer\n",
            (
                "Names refused arguments.",
                "Documents each operation.",
                "Tests three invalid shapes.",
            ),
        ),
        (
            "## Acceptance criteria\nIntroductory notes.\n\n"
            "- [x] Existing result.\n- [ ] Remaining result.\n\nOwner follow-up.\n\n-owner",
            ("Existing result.", "Remaining result."),
        ),
        (
            "## Done when\n- [ ] Implement this.\n"
            "```md\n- [ ] Not a real criterion.\n```\n\nReviewer follow-up.\n"
            "## Later\n- [ ] Separate work.",
            ("Implement this.",),
        ),
        (
            "## Done when\n- [ ] Names refused arguments\n  without exposing values.\n\n"
            "Reviewer release follow-up.",
            ("Names refused arguments without exposing values.",),
        ),
    ],
)
def test_checkbox_section_excludes_non_checklist_prose(
    body: str, expected: tuple[str, ...]
) -> None:
    assert extract_acceptance_criteria(body) == expected
