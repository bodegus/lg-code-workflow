"""HTML fail-closed policy and isolated CommonMark parser guards."""

from __future__ import annotations

import pytest

from lgcw.graph.claims import explicit_allowed_paths


@pytest.mark.unit
@pytest.mark.parametrize("eol", ["\n", "\r", "\r\n"])
@pytest.mark.parametrize(
    "body",
    [
        "<style>\n\nlgcw-allow: AGENTS.md\n\n</style>",
        "<textarea>\n\nlgcw-allow: AGENTS.md\n\n</textarea>",
        "<?\n\nlgcw-allow: AGENTS.md\n\n?>",
        "<!X\n\nlgcw-allow: AGENTS.md\n\n>",
        "<![CDATA[\n\nlgcw-allow: AGENTS.md\n\n]]>",
        "<details>\n\nlgcw-allow: AGENTS.md\n\n</details>",
        "<div hidden>\n\nlgcw-allow: AGENTS.md\n\n</div>",
    ],
)
def test_any_html_block_line_disables_preauthorization(body: str, eol: str) -> None:
    assert explicit_allowed_paths("Context." + eol + body.replace("\n", eol)) == set()


@pytest.mark.unit
@pytest.mark.parametrize(
    "body",
    [
        "```\nexample\x0c```\n\nlgcw-allow: AGENTS.md\n\n```",
        "prose\n\x0c\nlgcw-allow: AGENTS.md",
        "~~~\n```\n\nlgcw-allow: AGENTS.md\n\n~~~",
        "prose<script>\n\nlgcw-allow: AGENTS.md\n\nsuffix</script>",
        "prose<pre>\n\nlgcw-allow: AGENTS.md\n\nsuffix</pre>",
        "prose<script>\n\nlgcw-allow: AGENTS.md\n\n",
        "prose<pre>\n\nlgcw-allow: AGENTS.md\n\n",
    ],
)
def test_existing_parser_guards_have_independent_reproductions(body: str) -> None:
    assert explicit_allowed_paths(body) == set()
