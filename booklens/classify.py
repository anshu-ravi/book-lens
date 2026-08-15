"""Sorts chapters into 'body', 'front', and 'excerpt'.

Back matter that previews the next book must never be served; see the Back
matter section of `DECISIONS.md`.
"""

from __future__ import annotations

import re

from booklens.extract import BookExtraction

_EXCERPT_RE = re.compile(
    r"\bexcerpt\b|\bread on for\b|\bpreview of\b|\bsneak peek\b|\ba preview\b|"
    r"\bbonus (?:chapter|material)\b|\balso by\b",
    re.IGNORECASE,
)

_FRONT_RE = re.compile(
    r"\bcover\b|\btitle page\b|\bcopyright\b|\bcontents\b|\bmap\b|\bdedication\b|"
    r"\bepigraph\b|\bdramatis personae\b|\bcast of characters\b|"
    r"\babout the (?:author|book)\b|\backnowledg",
    re.IGNORECASE,
)

_RULE3_RE = re.compile(
    r"\babout the (?:author|book)\b|\backnowledg|\bpraise for\b|\bother books\b",
    re.IGNORECASE,
)


def classify_chapters(book: BookExtraction) -> dict[int, str]:
    """Tag every chapter so the tool layer can exclude another book's text.

    Errs toward over-excluding: hidden real text gets reported, a leaked
    preview does not.
    """
    chapters = book.chapters
    n = len(chapters)
    labels = [c.label for c in chapters]
    kind: dict[int, str] = {}

    # Once a preview starts, everything after it is more of the same:
    # ads, reading lists, further previews.
    excerpt_trigger: int | None = None
    for i, label in enumerate(labels):
        if _EXCERPT_RE.search(label):
            excerpt_trigger = i
            break
    if excerpt_trigger is not None:
        for i in range(excerpt_trigger, n):
            kind[i] = "excerpt"

    # Leading front matter, contiguous from the start.
    for i in range(n):
        if i in kind:
            break
        if _FRONT_RE.search(labels[i]):
            kind[i] = "front"
        else:
            break

    # Trailing author bios and the like. Without a known preview to place them
    # before, quarantine them rather than assume they are harmless.
    for i in range(n - 1, -1, -1):
        if kind.get(i) == "excerpt":
            continue
        if i in kind:
            break
        if _RULE3_RE.search(labels[i]):
            kind[i] = "front" if excerpt_trigger is not None else "excerpt"
        else:
            break

    # Everything untouched is the book proper.
    for i in range(n):
        kind.setdefault(i, "body")

    return {chapters[i].chapter_idx: kind[i] for i in range(n)}
