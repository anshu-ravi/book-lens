"""Sorts chapters into 'body', 'reference', 'boilerplate', and 'excerpt'.

Back matter that previews the next book must never be served; see the Back
matter section of `DECISIONS.md`. Front-matter-shaped material is split by
position: the same label is seed data before the story and a spoiler hazard
after it, per the Front/Back matter sections of `DECISIONS.md`.
"""

from __future__ import annotations

import re

from booklens.extract import BookExtraction

_EXCERPT_RE = re.compile(
    r"\bexcerpt\b|\bread on for\b|\bpreview of\b|\bsneak peek\b|\ba preview\b|"
    r"\bbonus (?:chapter|material)\b|\balso by\b",
    re.IGNORECASE,
)

# Publisher-supplied seed data (section 3): trustworthy only when it sits
# before the first body chapter, where it was written to be read first.
_REFERENCE_RE = re.compile(
    r"\bdramatis person\w*\b|\bcast of characters\b|\bmaps?\b|\bcharts?\b|"
    r"\bpreface\b|\bglossary\b",
    re.IGNORECASE,
)

# Non-narrative matter with no positional excuse: never a citable source,
# front or back.
_BOILERPLATE_RE = re.compile(
    r"\bcover\b|\btitle page\b|\bfront matter\b|\bcopyright\b|\bcontents\b|"
    r"\bstory so far\b|\bdedication\b|\bepigraph\b|"
    r"\babout the (?:author|book)\b|\backnowledg|\bpraise for\b|"
    r"\bother (?:books|titles)\b|\bpublisher'?s note\b|\bauthor'?s note\b|"
    r"\breading group\b|\bdiscussion questions\b|\badvertisement\b",
    re.IGNORECASE,
)

_FRONTLIKE_RE = re.compile(
    _REFERENCE_RE.pattern + "|" + _BOILERPLATE_RE.pattern, re.IGNORECASE
)


def classify_chapters(book: BookExtraction) -> dict[int, str]:
    """Tag every chapter so the tool layer serves only narrative and seed data.

    Errs toward over-excluding: hidden real text gets reported, a leaked
    preview or a back-matter reference section does not.
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

    # Leading front-matter run, contiguous from the start. Reference-shaped
    # material here is the publisher's seed data (section 3); boilerplate is
    # never served regardless of where it sits.
    for i in range(n):
        if i in kind:
            break
        if _REFERENCE_RE.search(labels[i]):
            kind[i] = "reference"
        elif _BOILERPLATE_RE.search(labels[i]):
            kind[i] = "boilerplate"
        else:
            break

    # Trailing back matter. Reference-shaped material back here does NOT get
    # the seed-data trust -- a cast list or glossary at the end of the book
    # is written with whole-book knowledge, so it is boilerplate too.
    for i in range(n - 1, -1, -1):
        if kind.get(i) == "excerpt":
            continue
        if i in kind:
            break
        if _FRONTLIKE_RE.search(labels[i]):
            kind[i] = "boilerplate"
        else:
            break

    # Everything untouched is the book proper.
    for i in range(n):
        kind.setdefault(i, "body")

    return {chapters[i].chapter_idx: kind[i] for i in range(n)}
