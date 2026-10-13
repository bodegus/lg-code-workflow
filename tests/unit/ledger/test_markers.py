"""The hidden marker wire format is safe and tolerant of malformed text."""

from __future__ import annotations

import pytest

from lgcw.ledger.markers import fingerprint, parse_markers, render_marker, strip_markers
from lgcw.models.ledger import BlockedMarker, ReadyMarker


@pytest.mark.unit
@pytest.mark.parametrize("reason", ["x --> <!-- y", "a--b---c", 'snowman ☃\nquoted "text"', "}"])
def test_marker_round_trip_with_hostile_text(reason: str) -> None:
    marker = BlockedMarker(reason=reason)
    rendered = render_marker(marker)
    assert parse_markers("Stopped.\n" + rendered) == [marker]
    assert "--" not in rendered.removeprefix("<!-- lgcw:v1 ").removesuffix(" -->")


@pytest.mark.unit
@pytest.mark.parametrize(
    "body",
    [
        "ordinary text",
        "<!-- lgcw:v1 {broken} -->",
        '<!-- lgcw:v1 {"kind":"merge"} -->',
        '<!-- lgcw:v1 {"kind":"ready"} -->',
        '<!-- lgcw:v1 {"kind":"ready", "head_sha":1} -->',
        '<!-- lgcw:v1 {"kind":"ready","head_sha":"a"}',
    ],
)
def test_bad_markers_are_ignored(body: str) -> None:
    assert parse_markers(body) == []


@pytest.mark.unit
def test_parse_multiple_and_strip_markers() -> None:
    first = ReadyMarker(head_sha="a")
    second = BlockedMarker(reason="stop")
    body = "start\n" + render_marker(first) + "\n" + render_marker(second) + "\nend"
    assert parse_markers(body) == [first, second]
    assert strip_markers(body).strip() == "start\n\n\nend"


@pytest.mark.unit
def test_fingerprint_is_stable_and_unambiguous() -> None:
    value = fingerprint("one", "two")
    assert value == fingerprint("one", "two")
    assert len(value) == 16
    int(value, 16)
    assert fingerprint("ab", "c") != fingerprint("a", "bc")
    assert fingerprint("one", "two") != fingerprint("two", "one")
