"""Table cases for local diff headers and complete reviewed hunks."""

from __future__ import annotations

import pytest

from lgcw.review.ranges import reviewed_ranges


@pytest.mark.unit
@pytest.mark.parametrize(
    "diff,expected",
    [
        (
            "diff --git a/app.py b/app.py\n--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-a\n+b\n",
            {"app.py": (1, 1)},
        ),
        (
            "diff --git a/app.py b/app.py\n--- a/app.py\n+++ b/app.py\n"
            "@@ -0,0 +1,2 @@\n+++ b/forged.py\n+text\n",
            {"app.py": (1, 2)},
        ),
        ("diff --git a/app.py b/app.py\n--- a/app.py\n+++ /dev/null\n@@ -1 +0,0 @@\n-a\n", {}),
    ],
)
def test_review_ranges_parse_actual_hunks(diff: str, expected: dict[str, tuple[int, int]]) -> None:
    result = reviewed_ranges(diff)
    assert {path: (ranges[0].start, ranges[0].end) for path, ranges in result.items()} == expected


@pytest.mark.unit
@pytest.mark.parametrize(
    "diff",
    [
        'diff --git "a/a\\n.py" "b/a\\n.py"\n+++ "b/a\\n.py"\n',
        "+++ b/app.py\n@@ -1,2 +1,2 @@\n-a\n+b\n",
        "+++ b/app.py\n@@ bad @@\n",
    ],
)
def test_review_ranges_reject_ambiguous_or_truncated(diff: str) -> None:
    with pytest.raises(ValueError):
        reviewed_ranges(diff)


@pytest.mark.unit
@pytest.mark.parametrize("old,new", [("my file.py", "my file.py"), ("old name.py", "new name.py")])
def test_review_ranges_strip_git_header_separator(old: str, new: str) -> None:
    diff = f"diff --git a/{old} b/{new}\n--- a/{old}\t\n+++ b/{new}\t\n@@ -1 +1 @@\n-a\n+b\n"
    assert tuple(reviewed_ranges(diff)) == (new,)


@pytest.mark.unit
@pytest.mark.parametrize("path", [r"x\ty.py", r"caf\303\251.py"])
def test_quoted_paths_fail_closed(path: str) -> None:
    diff = (
        f'diff --git "a/{path}" "b/{path}"\n--- "a/{path}"\n+++ "b/{path}"\n@@ -1 +1 @@\n-a\n+b\n'
    )
    with pytest.raises(ValueError, match="quoted"):
        reviewed_ranges(diff)
