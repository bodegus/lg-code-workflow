"""Extract explicit acceptance criteria without an LLM or Markdown dependency."""

from __future__ import annotations

import re

_HEADING = re.compile(r"^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$")
_SECTION = re.compile(r"^(acceptance criteria|done when|definition of done|expected)\s*:?$", re.I)
_ITEM = re.compile(r"^\s*(?:[-*+]\s+(?:\[[ xX]\]\s*)?|\d+[.)]\s+)(.+)$")
_CHECKBOX = re.compile(r"^\s*[-*+]\s+\[ \]\s+(.+)$")


def extract_acceptance_criteria(body: str) -> tuple[str, ...]:
    """Return a named nonempty section's items, or unchecked checklist items as fallback."""
    visible: list[str] = []
    fence: tuple[str, int] | None = None
    body = re.sub(r"<!--[\s\S]*?(?:-->|$)", "", body)
    for line in body.splitlines():
        if line.startswith(("    ", "\t")):
            continue
        match = re.match(r"^\s{0,3}(`{3,}|~{3,})(.*)$", line)
        if match:
            chars, rest = match.groups()
            if fence is None:
                fence = (chars[0], len(chars))
            elif chars[0] == fence[0] and len(chars) >= fence[1] and not rest.strip():
                fence = None
            continue
        if fence is None:
            visible.append(line)
    for index, line in enumerate(visible):
        heading = _HEADING.match(line)
        if heading is None or _SECTION.fullmatch(heading.group(2)) is None:
            continue
        level = len(heading.group(1))
        items: list[str] = []
        paragraph: list[str] = []
        for content in visible[index + 1 :]:
            next_heading = _HEADING.match(content)
            if next_heading is not None and len(next_heading.group(1)) <= level:
                break
            item = _ITEM.match(content)
            if item is not None or not content.strip() or next_heading is not None:
                if paragraph:
                    items.append(" ".join(paragraph))
                    paragraph = []
                if item is not None:
                    items.append(item.group(1).strip())
            else:
                paragraph.append(content.strip())
        if paragraph:
            items.append(" ".join(paragraph))
        if items:
            return tuple(items)
    return tuple(match.group(1).strip() for line in visible if (match := _CHECKBOX.match(line)))
