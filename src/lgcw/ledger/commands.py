"""Parse explicit commands from allowed unmarked owner comments."""

from __future__ import annotations

import re
from collections.abc import Collection, Sequence
from typing import Literal, cast

from lgcw.models.github import IssueComment
from lgcw.models.ledger import Command


def parse_command(body: str) -> tuple[Literal["answer", "retry", "abort", "revise"], str] | None:
    """Parse the first-line command, excluding a blank-separated terminal role signature."""
    lines = body.splitlines()
    first = next(((index, line.strip()) for index, line in enumerate(lines) if line.strip()), None)
    if first is None:
        return None
    index, line = first
    match = re.fullmatch(r"/lgcw\s+(answer|retry|abort|revise)(?:[ \t]+(.*))?", line)
    if match is None:
        return None
    verb = cast(Literal["answer", "retry", "abort", "revise"], match.group(1))
    last = next(index for index in range(len(lines) - 1, -1, -1) if lines[index].strip())
    if (
        last >= index + 2
        and not lines[last - 1].strip()
        and lines[last].strip() in {"-builder", "-reviewer", "-owner"}
    ):
        lines = lines[:last]
    text = "\n".join([match.group(2) or "", *lines[index + 1 :]]).strip()
    return None if verb == "revise" and not text else (verb, text)


def owner_commands(
    comments: Sequence[IssueComment], allowed_authors: Collection[str], after_comment_id: int
) -> list[Command]:
    """Return authorized commands after a question, in ascending comment-id order.

    Marker-bearing comments, even with a malformed or unknown marker, cannot be commands.
    """
    commands: list[Command] = []
    for comment in sorted(comments, key=lambda item: item.id):
        if comment.id <= after_comment_id or comment.author not in allowed_authors:
            continue
        if re.search(r"<!--\s*lgcw:", comment.body) is not None:
            continue
        parsed = parse_command(comment.body)
        if parsed is not None:
            verb, text = parsed
            commands.append(
                Command(verb=verb, text=text, comment_id=comment.id, author=comment.author)
            )
    return commands
