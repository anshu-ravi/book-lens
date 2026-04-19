#!/usr/bin/env python3
"""Manual tests for the knowledge store (load, save, filter, delete).

Tests all store functions without any LLM calls — pure data layer validation.

Usage:
    poetry run python tests/manual/test_knowledge_store.py
"""

import tempfile
from pathlib import Path
from unittest.mock import patch

from src.knowledge.models import (
    ChapterRef,
    ChapterSummary,
    CharacterEntity,
    CharacterEvent,
    KnowledgeBase,
    Relationship,
    RelationshipMoment,
    WorldFact,
)
from src.knowledge.store import (
    delete_book_knowledge,
    delete_series_knowledge,
    filter_to_progress,
    is_chapter_extracted,
    load_knowledge,
    save_knowledge,
)
from src.models import Book, BookStatus, Chapter, Series

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TMP_DIR: Path = Path()  # Set in main()


def _patch_knowledge_dir(fn):  # type: ignore[no-untyped-def]
    """Decorator that patches settings.knowledge_dir to _TMP_DIR."""

    def wrapper(*args, **kwargs):  # type: ignore[no-untyped-def]
        with patch("src.knowledge.store.settings") as mock_settings:
            mock_settings.knowledge_dir = str(_TMP_DIR)
            return fn(*args, **kwargs)

    return wrapper


def _make_series(
    *,
    book0_status: BookStatus = BookStatus.NOT_STARTED,
    book0_chapter: int | None = None,
    book1_status: BookStatus = BookStatus.NOT_STARTED,
    book1_chapter: int | None = None,
) -> Series:
    """Build a two-book Series with given statuses."""
    books = [
        Book(
            index=0,
            title="Book One",
            status=book0_status,
            chapters=[Chapter(index=i, label=f"Ch {i}") for i in range(20)],
            current_chapter_index=book0_chapter,
        ),
        Book(
            index=1,
            title="Book Two",
            status=book1_status,
            chapters=[Chapter(index=i, label=f"Ch {i}") for i in range(20)],
            current_chapter_index=book1_chapter,
        ),
    ]
    return Series(id="test-series", name="Test Series", books=books)


def _make_full_kb() -> KnowledgeBase:
    """Build a KnowledgeBase with rich sample data spanning two books."""
    darrow = CharacterEntity(
        name="Darrow",
        aliases=["the reaper", "darrow of lykos"],
        faction="Red",
        role="protagonist",
        description="A Red miner who infiltrates the Golds.",
        first_appearance=ChapterRef(book_index=0, chapter_index=0),
        key_events=[
            CharacterEvent(description="Eo is executed", book_index=0, chapter_index=2),
            CharacterEvent(description="Carved into a Gold", book_index=0, chapter_index=5),
            CharacterEvent(description="Wins the Institute", book_index=0, chapter_index=15),
            CharacterEvent(description="Joins the Senate", book_index=1, chapter_index=3),
        ],
    )
    sevro = CharacterEntity(
        name="Sevro",
        aliases=["goblin"],
        faction="Gold",
        role="ally",
        description="A fierce and unpredictable fighter, Darrow's closest ally.",
        first_appearance=ChapterRef(book_index=0, chapter_index=8),
        key_events=[
            CharacterEvent(description="Joins Darrow's house", book_index=0, chapter_index=8),
            CharacterEvent(description="Becomes a Howler", book_index=1, chapter_index=1),
        ],
    )
    rel = Relationship(
        character_a="Darrow",
        character_b="Sevro",
        type="ally",
        description="Darrow's most loyal and unpredictable ally.",
        moments=[
            RelationshipMoment(description="First meeting at the Institute", book_index=0, chapter_index=8),
            RelationshipMoment(description="Sevro pledges loyalty", book_index=0, chapter_index=10),
            RelationshipMoment(description="Fight side-by-side in Book 2", book_index=1, chapter_index=5),
        ],
    )
    world_fact_b0 = WorldFact(
        category="concept",
        name="Color System",
        description="Society is divided by birth into colors: Gold at the top, Red at the bottom.",
        book_index=0,
        chapter_index=0,
    )
    world_fact_b1 = WorldFact(
        category="faction",
        name="Sons of Ares",
        description="The rebel group fighting to overthrow the Gold hierarchy.",
        book_index=1,
        chapter_index=0,
    )
    summary_b0 = ChapterSummary(
        book_index=0,
        chapter_index=0,
        chapter_label="Chapter 1",
        summary="Darrow works as a helldiver in the mines of Mars.",
        characters_present=["Darrow"],
        key_events=["Darrow wins the song competition"],
    )
    summary_b1 = ChapterSummary(
        book_index=1,
        chapter_index=0,
        chapter_label="Chapter 1",
        summary="Darrow navigates politics in the Senate.",
        characters_present=["Darrow", "Sevro"],
        key_events=["Senate session"],
    )
    return KnowledgeBase(
        series_id="test-series",
        characters=[darrow, sevro],
        relationships=[rel],
        world_facts=[world_fact_b0, world_fact_b1],
        summaries=[summary_b0, summary_b1],
        alias_registry={
            "the reaper": "Darrow",
            "darrow of lykos": "Darrow",
            "goblin": "Sevro",
        },
        extracted_chapters=[
            ChapterRef(book_index=0, chapter_index=0),
            ChapterRef(book_index=1, chapter_index=0),
        ],
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@_patch_knowledge_dir
def test_load_returns_empty_for_missing_file() -> None:
    """load_knowledge returns an empty KnowledgeBase when the file doesn't exist."""
    kb = load_knowledge("no-such-series")
    assert kb.series_id == "no-such-series"
    assert kb.characters == []
    assert kb.summaries == []
    assert kb.alias_registry == {}
    print("  PASS: load returns empty KB for missing file")


@_patch_knowledge_dir
def test_save_and_load_roundtrip() -> None:
    """save_knowledge + load_knowledge roundtrip preserves all data."""
    original = _make_full_kb()
    save_knowledge(original)
    loaded = load_knowledge("test-series")

    assert loaded.series_id == "test-series"
    assert len(loaded.characters) == 2
    assert loaded.characters[0].name == "Darrow"
    assert loaded.characters[0].aliases == ["the reaper", "darrow of lykos"]
    assert len(loaded.characters[0].key_events) == 4
    assert len(loaded.relationships) == 1
    assert loaded.relationships[0].type == "ally"
    assert len(loaded.world_facts) == 2
    assert len(loaded.summaries) == 2
    assert loaded.alias_registry["goblin"] == "Sevro"
    assert len(loaded.extracted_chapters) == 2
    print("  PASS: save + load roundtrip")


@_patch_knowledge_dir
def test_is_chapter_extracted() -> None:
    """is_chapter_extracted correctly identifies processed chapters."""
    kb = _make_full_kb()
    assert is_chapter_extracted(kb, book_index=0, chapter_index=0) is True
    assert is_chapter_extracted(kb, book_index=1, chapter_index=0) is True
    assert is_chapter_extracted(kb, book_index=0, chapter_index=5) is False
    assert is_chapter_extracted(kb, book_index=2, chapter_index=0) is False
    print("  PASS: is_chapter_extracted")


@_patch_knowledge_dir
def test_filter_not_started_excludes_all() -> None:
    """filter_to_progress returns empty KB when all books are NOT_STARTED."""
    kb = _make_full_kb()
    series = _make_series()  # both books NOT_STARTED
    filtered = filter_to_progress(kb, series)

    assert filtered.characters == []
    assert filtered.relationships == []
    assert filtered.world_facts == []
    assert filtered.summaries == []
    assert filtered.alias_registry == {}
    print("  PASS: filter_to_progress excludes NOT_STARTED books")


@_patch_knowledge_dir
def test_filter_completed_includes_all() -> None:
    """filter_to_progress returns all data when both books are COMPLETED."""
    kb = _make_full_kb()
    series = _make_series(
        book0_status=BookStatus.COMPLETED,
        book1_status=BookStatus.COMPLETED,
    )
    filtered = filter_to_progress(kb, series)

    assert len(filtered.characters) == 2
    # All key_events for Darrow (4 total across both books)
    darrow = next(c for c in filtered.characters if c.name == "Darrow")
    assert len(darrow.key_events) == 4
    assert len(filtered.relationships) == 1
    assert len(filtered.relationships[0].moments) == 3
    assert len(filtered.world_facts) == 2
    assert len(filtered.summaries) == 2
    print("  PASS: filter_to_progress includes all for COMPLETED books")


@_patch_knowledge_dir
def test_filter_reading_truncates_events() -> None:
    """filter_to_progress truncates character events and relationship moments to reading progress."""
    kb = _make_full_kb()
    # Book 0 completed, Book 1 reading at chapter 2 (before ch 3 and ch 5 events)
    series = _make_series(
        book0_status=BookStatus.COMPLETED,
        book1_status=BookStatus.READING,
        book1_chapter=2,
    )
    filtered = filter_to_progress(kb, series)

    darrow = next(c for c in filtered.characters if c.name == "Darrow")
    # Should have 3 book-0 events + 0 book-1 events (ch3 is beyond current ch2)
    assert len(darrow.key_events) == 3
    assert all(e.book_index == 0 for e in darrow.key_events)

    sevro = next(c for c in filtered.characters if c.name == "Sevro")
    # Sevro's book-1 event is at ch1, which is <= ch2 (in scope)
    assert len(sevro.key_events) == 2  # book-0 ch8 + book-1 ch1

    # Relationship: book-1 moment at ch5 is beyond ch2, should be excluded
    rel = filtered.relationships[0]
    assert len(rel.moments) == 2  # book-0 ch8 + book-0 ch10
    assert all(m.book_index == 0 for m in rel.moments)

    # World facts: book-1 fact at ch0 <= ch2, should be included
    assert len(filtered.world_facts) == 2

    print("  PASS: filter_to_progress truncates events for READING books")


@_patch_knowledge_dir
def test_filter_not_started_book_excludes_its_content() -> None:
    """filter_to_progress excludes everything from a NOT_STARTED book."""
    kb = _make_full_kb()
    # Book 0 completed, Book 1 not started
    series = _make_series(book0_status=BookStatus.COMPLETED)
    filtered = filter_to_progress(kb, series)

    darrow = next(c for c in filtered.characters if c.name == "Darrow")
    # Only book-0 events (3 of them), book-1 event excluded
    assert len(darrow.key_events) == 3

    # Sevro's only book-1 event (ch1) is excluded
    sevro = next(c for c in filtered.characters if c.name == "Sevro")
    assert len(sevro.key_events) == 1  # only book-0 ch8

    # Relationship's book-1 moment excluded
    rel = filtered.relationships[0]
    assert len(rel.moments) == 2

    # World fact from book-1 excluded
    assert len(filtered.world_facts) == 1
    assert filtered.world_facts[0].name == "Color System"

    print("  PASS: filter_to_progress excludes NOT_STARTED book content")


@_patch_knowledge_dir
def test_filter_rebuilds_alias_registry() -> None:
    """filter_to_progress only includes aliases for visible characters."""
    kb = _make_full_kb()
    # Book 0 not started — Darrow first appears in book 0 → excluded
    # Sevro also first appears in book 0 → both excluded
    series = _make_series()
    filtered = filter_to_progress(kb, series)

    assert filtered.alias_registry == {}
    print("  PASS: filter_to_progress rebuilds alias_registry for visible characters")


@_patch_knowledge_dir
def test_delete_series_knowledge() -> None:
    """delete_series_knowledge removes the file; subsequent load returns empty KB."""
    kb = _make_full_kb()
    save_knowledge(kb)

    delete_series_knowledge("test-series")
    loaded = load_knowledge("test-series")
    assert loaded.characters == []
    print("  PASS: delete_series_knowledge removes file")


@_patch_knowledge_dir
def test_delete_book_knowledge_removes_book_data() -> None:
    """delete_book_knowledge removes all entries for the given book."""
    kb = _make_full_kb()
    save_knowledge(kb)

    updated = delete_book_knowledge("test-series", book_index=1)

    # Characters who first appeared in book 1: none — Darrow and Sevro both start in book 0
    assert len(updated.characters) == 2

    # Darrow's book-1 event should be gone
    darrow = next(c for c in updated.characters if c.name == "Darrow")
    assert len(darrow.key_events) == 3
    assert all(e.book_index == 0 for e in darrow.key_events)

    # Relationship: book-1 moment removed
    rel = updated.relationships[0]
    assert len(rel.moments) == 2

    # World fact from book-1 removed
    assert len(updated.world_facts) == 1
    assert updated.world_facts[0].name == "Color System"

    # Summaries: book-1 summary removed
    assert len(updated.summaries) == 1
    assert updated.summaries[0].book_index == 0

    # extracted_chapters: book-1 entry removed
    assert len(updated.extracted_chapters) == 1
    assert updated.extracted_chapters[0].book_index == 0

    print("  PASS: delete_book_knowledge removes all book-1 entries")


@_patch_knowledge_dir
def test_delete_book_removes_character_first_appearing_in_it() -> None:
    """Characters whose first_appearance is in the deleted book are removed entirely."""
    # Add a character who only appears in book-1
    kb = _make_full_kb()
    book1_only = CharacterEntity(
        name="Mustang",
        aliases=["mustang", "virginia au augustus"],
        faction="Gold",
        role="love interest",
        description="A Gold who helps Darrow.",
        first_appearance=ChapterRef(book_index=1, chapter_index=2),
        key_events=[
            CharacterEvent(description="Meets Darrow", book_index=1, chapter_index=2),
        ],
    )
    kb.characters.append(book1_only)
    kb.alias_registry["mustang"] = "Mustang"
    kb.alias_registry["virginia au augustus"] = "Mustang"
    save_knowledge(kb)

    updated = delete_book_knowledge("test-series", book_index=1)

    names = {c.name for c in updated.characters}
    assert "Mustang" not in names
    assert "mustang" not in updated.alias_registry
    print("  PASS: delete_book_knowledge removes characters first-appearing in deleted book")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    """Run all tests."""
    global _TMP_DIR

    with tempfile.TemporaryDirectory() as tmp:
        _TMP_DIR = Path(tmp)
        print("Running knowledge store tests...")

        test_load_returns_empty_for_missing_file()
        test_save_and_load_roundtrip()
        test_is_chapter_extracted()
        test_filter_not_started_excludes_all()
        test_filter_completed_includes_all()
        test_filter_reading_truncates_events()
        test_filter_not_started_book_excludes_its_content()
        test_filter_rebuilds_alias_registry()
        test_delete_series_knowledge()
        test_delete_book_knowledge_removes_book_data()
        test_delete_book_removes_character_first_appearing_in_it()

        print("\nAll knowledge store tests passed.")


if __name__ == "__main__":
    main()
