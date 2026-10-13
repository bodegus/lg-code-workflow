"""Numstat paths, binary files, rename records and excluded evidence."""

from __future__ import annotations

import pytest

from lgcw.review.diffstat import parse_numstat


@pytest.mark.unit
@pytest.mark.parametrize(
    "text,excluded,paths,lines",
    [
        ("", (), (), 0),
        (
            "12\t3\tsrc/main.py\n2\t0\ttests/test_main.py\n",
            (),
            ("src/main.py", "tests/test_main.py"),
            17,
        ),
        ("-\t-\tassets/image.png\n", (), ("assets/image.png",), 1),
        (
            "4\t1\tpackage-lock.json\n2\t0\tsrc/a.py\n",
            ("**/*lock*", "package-lock.json"),
            ("src/a.py",),
            2,
        ),
        ("1\t0\tdocs/name with spaces.md\n", (), ("docs/name with spaces.md",), 1),
        ("1\t2\tsrc/{old => new}/a.py\n", (), ("src/new/a.py",), 3),
        ("1\t2\told.py => new.py\n", (), ("new.py",), 3),
        ("1\t2\t\0old.py\0new.py\0", (), ("new.py",), 3),
        ("1\t2\tsrc/main.py\0-\t-\timage.png\0", (), ("src/main.py", "image.png"), 4),
    ],
)
def test_numstat(text: str, excluded: tuple[str, ...], paths: tuple[str, ...], lines: int) -> None:
    result = parse_numstat(text, excluded)
    assert result.paths == paths and result.changed_lines == lines


@pytest.mark.unit
@pytest.mark.parametrize(
    "text",
    [
        "bad",
        "a\t2\tsrc/a.py",
        "-1\t0\tsrc/a.py",
        "1\t0\t../outside.py",
        "1\t0\t/root.py",
        '1\t0\t"quoted\\tpath.py"',
        "1\t2\t\0old.py\0",
    ],
)
def test_invalid_or_ambiguous_numstat_is_rejected(text: str) -> None:
    with pytest.raises(ValueError):
        parse_numstat(text, ())
