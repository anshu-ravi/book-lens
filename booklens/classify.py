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

# Where the book proper starts, by the same reader-facing shapes the chapter
# addressing uses: a printed number, a named division, or a part divider.
_NARRATIVE_START_RE = re.compile(
    r"^\s*(?:chapter\s+)?\d+\b|^\s*(?:prologue|part\b|book\s+\w+\b|interlude)|"
    r"^\s*[IVXLC]+[.:]\s+\S",
    re.IGNORECASE,
)


class NoBodyChaptersError(Exception):
    """Classification left a book with nothing readable, which is always a bug here.

    A real EPUB is never entirely front matter, back matter, and previews, so
    this is the classifier misreading structure -- and it fails loudly rather
    than shelving a book whose every chapter is silently unservable.
    """


def classify_chapters(book: BookExtraction) -> dict[int, str]:
    """Tag every chapter so the tool layer serves only narrative and seed data.

    Errs toward over-excluding: hidden real text gets reported, a leaked
    preview or a back-matter reference section does not.
    """
    chapters = book.chapters
    n = len(chapters)
    labels = [c.label for c in chapters]
    kind: dict[int, str] = {}

    # Front matter is everything before the first narrative-shaped label,
    # recognised or not -- a title page carrying only the book's own name
    # would otherwise end the run one chapter in. Reference-shaped material
    # here is the publisher's seed data (section 3); the rest is boilerplate.
    narrative_start = next(
        (i for i, label in enumerate(labels) if _NARRATIVE_START_RE.match(label.strip())), 0
    )
    for i in range(narrative_start):
        if _REFERENCE_RE.search(labels[i]):
            kind[i] = "reference"
        else:
            kind[i] = "boilerplate"

    # Once a preview starts, everything after it is more of the same: ads,
    # reading lists, further previews. Only searched past the front matter --
    # "Also by X" opens a listing at the front and a teaser at the back.
    for i in range(narrative_start, n):
        if _EXCERPT_RE.search(labels[i]):
            for j in range(i, n):
                kind[j] = "excerpt"
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

    if n and not any(k == "body" for k in kind.values()):
        raise NoBodyChaptersError(
            f"classified all {n} chapters as non-body, leaving nothing readable; "
            f"labels: {labels[:12]}"
        )

    return {chapters[i].chapter_idx: kind[i] for i in range(n)}
