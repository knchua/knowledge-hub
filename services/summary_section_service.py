"""Presentation-independent pruning of non-applicable summary sections.

No model calls, source access, storage, or citation fabrication. The model chooses
headings; this defensive postprocessor removes placeholder-only sections.
"""
from __future__ import annotations

import re

_HEADING = re.compile(r"(?m)^ {0,3}#{1,6}\s+.+?\s*$")
_PLACEHOLDER = re.compile(
    r"(?ix)^\s*(?:[-*+]\s*|\d+[.)]\s*)?"
    r"(?:\*\*[^*\n]{1,80}:\*\*\s*)?"
    r"(?:\*\*|__)?\s*"
    r"(?:not\s+found\s+in\s+(?:the\s+)?document"
    r"|no\s+(?:relevant\s+)?information\s+(?:was\s+)?(?:found|provided|available)"
    r"|not\s+applicable"
    r"|none\s+(?:identified|specified|found|provided))"
    r"\s*(?:\*\*|__)?\s*[.!:;\-–—]*\s*(?:\[P\d+\])?\s*$"
)



def prune_inapplicable_sections(text: str) -> str:
    """Remove empty or placeholder-only sections.

    Preserve the original formatting when no changes are required.
    """
    if not isinstance(text, str):
        raise TypeError("Summary must be a string")

    matches = list(_HEADING.finditer(text))
    if not matches:
        return text.strip()

    pieces = []
    changed = False

    preamble = text[:matches[0].start()].strip()
    if preamble:
        pieces.append(preamble)

    for index, heading in enumerate(matches):
        end = (
            matches[index + 1].start()
            if index + 1 < len(matches)
            else len(text)
        )

        body = text[heading.end():end]

        meaningful = [
            line
            for line in body.splitlines()
            if line.strip() and not _PLACEHOLDER.fullmatch(line)
        ]

        if meaningful:
            if len(meaningful) != len(
                [line for line in body.splitlines() if line.strip()]
            ):
                changed = True

            pieces.append(
                heading.group(0).strip()
                + "\n\n"
                + "\n".join(meaningful).strip()
            )
        else:
            changed = True

    # Preserve existing formatting when every section is valid.
    if not changed:
        return text.strip()

    return "\n\n".join(pieces).strip()
