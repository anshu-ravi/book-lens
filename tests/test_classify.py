"""Tests for booklens.classify: chapter-kind classification.

Synthetic-fixture tests exercise the four rules directly against a
lightweight BookExtraction stand-in. Corpus tests then confirm the known
excerpt back matter is caught on the real Red Rising / Golden Son / Morning
Star EPUBs, and -- just as important -- that no real Mistborn chapter is
ever misclassified as 'excerpt' (Mistborn has no excerpt back matter at all,
so any 'excerpt' there would be a false positive silently deleting text).
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from booklens.classify import NoBodyChaptersError, classify_chapters
from booklens.extract import extract_book


@dataclass(frozen=True)
class _FakeChapter:
    chapter_idx: int
    label: str
    part_label: str | None = None
    start_spine_idx: int = 0
    end_spine_idx: int = 0


@dataclass(frozen=True)
class _FakeBook:
    chapters: tuple


def _book(labels: list[str]) -> _FakeBook:
    return _FakeBook(
        chapters=tuple(
            _FakeChapter(chapter_idx=i, label=label, start_spine_idx=i, end_spine_idx=i)
            for i, label in enumerate(labels)
        )
    )


# -- rule 1: trailing excerpt run -----------------------------------------


def test_trailing_excerpt_chapter_is_quarantined():
    book = _book(["Prologue", "Chapter 1", "Chapter 2", "Excerpt from Book Two"])
    kinds = classify_chapters(book)
    assert kinds[0] == "body"
    assert kinds[1] == "body"
    assert kinds[2] == "body"
    assert kinds[3] == "excerpt"


def test_excerpt_trigger_sweeps_every_subsequent_chapter():
    # Everything from the trigger onward is excerpt, even chapters whose own
    # label wouldn't independently match (publishers stack ads/teasers).
    book = _book(["Chapter 1", "Sneak Peek of Book Two", "Also by This Author", "Chapter 1"])
    kinds = classify_chapters(book)
    assert kinds[0] == "body"
    assert kinds[1] == "excerpt"
    assert kinds[2] == "excerpt"
    assert kinds[3] == "excerpt"  # swept even though it looks like a real chapter


def test_no_excerpt_pattern_no_excerpt_chapters():
    book = _book(["Prologue", "Chapter 1", "Chapter 2", "Epilogue"])
    kinds = classify_chapters(book)
    assert set(kinds.values()) == {"body"}


# -- rule 2: leading front-matter run --------------------------------------


def test_leading_boilerplate_run_is_marked_boilerplate():
    book = _book(["Cover", "Title Page", "Copyright", "Chapter 1", "Chapter 2"])
    kinds = classify_chapters(book)
    assert kinds[0] == "boilerplate"
    assert kinds[1] == "boilerplate"
    assert kinds[2] == "boilerplate"
    assert kinds[3] == "body"
    assert kinds[4] == "body"


def test_leading_reference_shaped_label_is_marked_reference():
    # Reference-shaped material positioned before the first body chapter is
    # seed data (DECISIONS.md section 3), distinct from boilerplate.
    book = _book(["Dramatis Personae", "Map", "Chapter 1"])
    kinds = classify_chapters(book)
    assert kinds[0] == "reference"
    assert kinds[1] == "reference"
    assert kinds[2] == "body"


def test_leading_run_stops_at_first_non_matching_label():
    book = _book(["Cover", "Prologue", "Copyright", "Chapter 1"])
    kinds = classify_chapters(book)
    assert kinds[0] == "boilerplate"
    # "Prologue" doesn't match a front pattern -- the leading run stops here.
    assert kinds[1] == "body"
    assert kinds[2] == "body"
    assert kinds[3] == "body"


def test_unrecognised_labels_before_the_first_chapter_are_front_matter():
    # An unrecognised label ahead of the narrative is a title page, not the
    # book proper. Previously the leading run stopped dead at index 0, which
    # is what let a front-matter "Also by" reach the excerpt trigger.
    book = _book(["Untitled Book", "Acknowledgments", "Chapter 1"])
    kinds = classify_chapters(book)
    assert kinds[0] == "boilerplate"
    assert kinds[1] == "boilerplate"
    assert kinds[2] == "body"


# -- rule 3: trailing back matter -------------------------------------------


def test_trailing_acknowledgments_before_excerpt_run_is_boilerplate():
    book = _book(["Chapter 1", "Chapter 2", "Acknowledgments", "About the Author", "Excerpt from Book Two"])
    kinds = classify_chapters(book)
    assert kinds[0] == "body"
    assert kinds[1] == "body"
    assert kinds[2] == "boilerplate"
    assert kinds[3] == "boilerplate"
    assert kinds[4] == "excerpt"


def test_trailing_acknowledgments_with_no_excerpt_run_is_boilerplate():
    book = _book(["Chapter 1", "Chapter 2", "Acknowledgments"])
    kinds = classify_chapters(book)
    assert kinds[0] == "body"
    assert kinds[1] == "body"
    assert kinds[2] == "boilerplate"


def test_trailing_reference_shaped_label_is_boilerplate_not_reference():
    # The key asymmetry: the same "Glossary" shape that would be `reference`
    # at the front is `boilerplate` at the back -- it was written with
    # whole-book knowledge and gets no seed-data trust there.
    book = _book(["Chapter 1", "Chapter 2", "Glossary"])
    kinds = classify_chapters(book)
    assert kinds[0] == "body"
    assert kinds[1] == "body"
    assert kinds[2] == "boilerplate"


def test_rule3_scan_stops_at_first_real_trailing_chapter():
    book = _book(["Chapter 1", "Chapter 2", "Epilogue", "Acknowledgments"])
    kinds = classify_chapters(book)
    # Epilogue is real content -- the backward scan for rule 3 stops there,
    # so Acknowledgments (after it) is still caught, but Epilogue is body.
    assert kinds[2] == "body"
    assert kinds[3] == "boilerplate"


# -- rule 4: default ---------------------------------------------------------


def test_default_classification_is_body():
    book = _book(["Chapter 1"])
    kinds = classify_chapters(book)
    assert kinds[0] == "body"


def test_returns_entry_for_every_chapter_idx():
    book = _book(["A", "B", "C"])
    kinds = classify_chapters(book)
    assert set(kinds.keys()) == {0, 1, 2}


# -- real corpus ------------------------------------------------------------


_KNOWN_EXCERPTS = {
    "red-rising": ("Excerpt from Golden Son", 146),
    "golden-son": ("Excerpt from Morning Star", 23),
    "morning-star": ("Excerpt from Iron Gold", 884),
}

_NO_EXCERPT_SLUGS = ["final-empire", "well-of-ascension", "hero-of-ages"]


def _paragraph_count(book, chapter) -> int:
    return sum(
        len(d.paragraphs)
        for d in book.documents
        if chapter.start_spine_idx <= d.spine_idx <= chapter.end_spine_idx
    )


def test_known_excerpt_chapters_are_caught_on_real_corpus(corpus):
    for slug, (expected_label, expected_paras) in _KNOWN_EXCERPTS.items():
        if slug not in corpus:
            continue
        book = extract_book(corpus[slug])
        kinds = classify_chapters(book)
        excerpt_chapters = [c for c in book.chapters if kinds[c.chapter_idx] == "excerpt"]
        assert len(excerpt_chapters) == 1, f"{slug}: expected exactly one excerpt chapter"
        ch = excerpt_chapters[0]
        assert ch.label == expected_label, f"{slug}: unexpected excerpt chapter {ch.label!r}"
        assert _paragraph_count(book, ch) == expected_paras, f"{slug}: excerpt paragraph count drifted"


def test_no_body_chapter_misclassified_as_excerpt_in_mistborn(corpus):
    for slug in _NO_EXCERPT_SLUGS:
        if slug not in corpus:
            continue
        book = extract_book(corpus[slug])
        kinds = classify_chapters(book)
        excerpt_chapters = [c.label for c in book.chapters if kinds[c.chapter_idx] == "excerpt"]
        assert excerpt_chapters == [], (
            f"{slug}: false positive excerpt classification would silently "
            f"hide real text: {excerpt_chapters}"
        )


def test_every_chapter_classified_exactly_once_on_real_corpus(corpus):
    for slug, path in corpus.items():
        book = extract_book(path)
        kinds = classify_chapters(book)
        assert set(kinds.keys()) == {c.chapter_idx for c in book.chapters}
        assert all(v in ("body", "reference", "boilerplate", "excerpt") for v in kinds.values())


def test_red_rising_boilerplate_and_reference_split_on_real_corpus(corpus):
    if "red-rising" not in corpus:
        pytest.skip("red-rising not present in uploads/")
    book = extract_book(corpus["red-rising"])
    kinds = classify_chapters(book)
    by_label = {c.label: kinds[c.chapter_idx] for c in book.chapters}

    for label in ("Copyright", "Contents", "Dedication", "Acknowledgments", "About the Author"):
        assert by_label[label] == "boilerplate", f"{label!r} should be boilerplate, got {by_label[label]!r}"

    assert by_label["Map"] == "reference"
    assert by_label["Prologue"] == "body"
    assert by_label["Excerpt from Golden Son"] == "excerpt"


def test_also_by_in_front_matter_does_not_quarantine_the_book():
    """Ironbound: 'Also by <author>' is a front-matter listing, not a preview.

    It matched the excerpt pattern, and the trigger marked everything after
    it as excerpt -- the entire book, leaving nothing readable.
    """
    book = _book([
        "Cover", "Title Page", "Copyright", "Contents",
        "Also by Andrew Givler", "Epigraph",
        "I. THE SENTENTIA", "Chapter 1", "Chapter 2",
    ])
    kinds = classify_chapters(book)

    assert kinds[4] == "boilerplate"   # "Also by Andrew Givler"
    assert kinds[6] == "body"          # "I. THE SENTENTIA"
    assert kinds[7] == "body"
    assert kinds[8] == "body"


def test_also_by_after_the_body_still_starts_the_excerpt_run():
    """The same label at the back of the book keeps its old meaning."""
    book = _book(["Cover", "Chapter 1", "Chapter 2", "Also by Andrew Givler", "Chapter 1"])
    kinds = classify_chapters(book)

    assert kinds[1] == "body"
    assert kinds[3] == "excerpt"
    assert kinds[4] == "excerpt"


def test_classifying_everything_as_non_body_raises():
    """A book with nothing readable is a classifier bug, never a real structure."""
    with pytest.raises(NoBodyChaptersError):
        classify_chapters(_book(["Cover", "Title Page", "Copyright"]))
