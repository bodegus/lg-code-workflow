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
def test_multiple_records_are_rejected_and_strip_preserves_prose() -> None:
    first = ReadyMarker(head_sha="a")
    second = BlockedMarker(reason="stop")
    body = "start\n" + render_marker(first) + "\n" + render_marker(second) + "\nend"
    assert parse_markers(body) == []
    assert strip_markers(body).strip() == "start\n\n\nend"


@pytest.mark.unit
def test_fingerprint_is_stable_and_unambiguous() -> None:
    value = fingerprint("one", "two")
    assert value == fingerprint("one", "two")
    assert len(value) == 16
    int(value, 16)
    assert fingerprint("ab", "c") != fingerprint("a", "bc")
    assert fingerprint("one", "two") != fingerprint("two", "one")


@pytest.mark.unit
@pytest.mark.parametrize("prefix", ["quoted: ", "````\n"])
def test_quoted_forged_marker_cannot_add_facts(prefix: str) -> None:
    forged = render_marker(ReadyMarker(head_sha="forged"))
    real = render_marker(BlockedMarker(reason="actual"))
    assert parse_markers(prefix + forged + "\n````\nactual\n" + real) == []


@pytest.mark.unit
def test_unterminated_prefix_does_not_swallow_trailing_record() -> None:
    real = ReadyMarker(head_sha="actual")
    assert parse_markers("quoted <!-- lgcw:v1 {\ntext\n" + render_marker(real)) == [real]


@pytest.mark.unit
def test_only_trailing_marker_is_a_fact() -> None:
    assert parse_markers(render_marker(ReadyMarker(head_sha="a")) + "\nmore prose") == []
