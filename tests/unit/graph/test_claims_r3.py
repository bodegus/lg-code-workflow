"""CommonMark line and paragraph scope for explicit path authorization."""

from __future__ import annotations

import pytest

from lgcw.graph.claims import explicit_allowed_paths


@pytest.mark.unit
@pytest.mark.parametrize(
    "separator", ["\x0b", "\x0c", "\x1c", "\x1d", "\x1e", "\x85", "\u2028", "\u2029"]
)
def test_non_commonmark_separator_never_creates_an_allow_line(separator: str) -> None:
    assert explicit_allowed_paths("x" + separator + "lgcw-allow: AGENTS.md") == set()
    assert (
        explicit_allowed_paths("~~~\nexample" + separator + "~~~\nlgcw-allow: AGENTS.md\n~~~")
        == set()
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    "body",
    [
        "Soft wrapped prose\nlgcw-allow: AGENTS.md",
        "lgcw-allow: AGENTS.md\nsoft continuation",
        "> a blockquote\nlgcw-allow: AGENTS.md",
        ">\nlgcw-allow: AGENTS.md",
        "lgcw-allow: AGENTS.md\nlgcw-allow: CLAUDE.md\nsoft continuation",
        "<script>\nlgcw-allow: AGENTS.md\n</script>",
        "<pre>\nlgcw-allow: AGENTS.md\n</pre>",
        "<SCRIPT>\nlgcw-allow: AGENTS.md",
        "<!--\nlgcw-allow: AGENTS.md",
        "<!--\n\nlgcw-allow: AGENTS.md\n\n",
        "````\n```\n\nlgcw-allow: AGENTS.md\n\n````",
        "prefix lgcw-allow: AGENTS.md",
    ],
)
def test_allow_lines_require_visible_standalone_paragraph(body: str) -> None:
    assert explicit_allowed_paths(body) == set()


@pytest.mark.unit
@pytest.mark.parametrize("separator", ["\n", "\r", "\r\n"])
def test_adjacent_allow_lines_form_a_standalone_paragraph(separator: str) -> None:
    body = separator.join(
        ["Prose", "", "lgcw-allow: AGENTS.md", "lgcw-allow: CLAUDE.md", "", "Other prose"]
    )
    assert explicit_allowed_paths(body) == {"AGENTS.md", "CLAUDE.md"}
