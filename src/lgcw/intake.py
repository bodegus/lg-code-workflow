"""Extract explicit acceptance criteria without an LLM or Markdown dependency."""

from __future__ import annotations

import re

_HEADING = re.compile(r"^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$")
_SECTION = re.compile(r"^(acceptance criteria|done when|definition of done|expected)\s*:?$", re.I)
_ITEM = re.compile(r"^\s*(?:[-*+]\s+(?:\[[ xX]\]\s*)?|\d+[.)]\s+)(.+)$")
_CHECKBOX = re.compile(r"^\s*[-*+]\s+\[ \]\s+(.+)$")
_SECTION_CHECKBOX = re.compile(r"^\s*[-*+]\s+\[[ xX]\]\s+(.+)$")


def extract_acceptance_criteria(body: str) -> tuple[str, ...]:
    """Prefer a named section's checklist, then its items, then unchecked items elsewhere."""
    visible: list[str] = []
    fence: tuple[str, int] | None = None
    for line in body.splitlines():
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
    # Fenced examples cannot open a comment that consumes following real criteria.
    body = re.sub(r"<!--[\s\S]*?-->", "", "\n".join(visible))
    body = re.sub(r"(?m)^\s*<!--[\s\S]*$", "", body)
    visible = []
    in_list = False
    for line in body.splitlines():
        indented = line.startswith(("    ", "\t"))
        if indented and not in_list:
            continue
        if _ITEM.match(line):
            in_list = True
        elif line.strip() and not indented:
            in_list = False
        visible.append(line)
    for index, line in enumerate(visible):
        heading = _HEADING.match(line)
        if heading is None or _SECTION.fullmatch(heading.group(2)) is None:
            continue
        level = len(heading.group(1))
        items: list[str] = []
        checkbox_items: list[str] = []
        checkbox_continuation = False
        paragraph: list[str] = []
        for content in visible[index + 1 :]:
            next_heading = _HEADING.match(content)
            if next_heading is not None and len(next_heading.group(1)) <= level:
                break
            item = _ITEM.match(content)
            if item is not None or not content.strip() or next_heading is not None:
                checkbox_continuation = False
                if paragraph:
                    items.append(" ".join(paragraph))
                    paragraph = []
                if item is not None:
                    items.append(item.group(1).strip())
                    checkbox = _SECTION_CHECKBOX.match(content)
                    if checkbox is not None:
                        checkbox_items.append(checkbox.group(1).strip())
                        checkbox_continuation = True
            else:
                paragraph.append(content.strip())
                if checkbox_continuation:
                    checkbox_items[-1] += " " + content.strip()
        if paragraph:
            items.append(" ".join(paragraph))
        if items:
            return tuple(checkbox_items or items)
    return tuple(match.group(1).strip() for line in visible if (match := _CHECKBOX.match(line)))
