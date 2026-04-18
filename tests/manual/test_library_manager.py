#!/usr/bin/env python3
"""Manual tests for the library manager CRUD functions.

Tests the manager functions directly without a running server.

Usage:
    poetry run python tests/manual/test_library_manager.py
"""

from pathlib import Path
from unittest.mock import patch

from src.models import Book, BookStatus, Chapter, Library
from src.library.manager import (
    create_series,
    get_series,
    load_library,
    remove_book,
    remove_series,
    save_library,
    update_book_status,
    upsert_book,
)

_TEST_LIBRARY_PATH = Path("./test_library_tmp.json")


def _patched_load() -> Library:
    """Load from the test path instead of the real library path."""
    from src.models import Library

    if not _TEST_LIBRARY_PATH.exists():
        return Library(series=[])
    return Library.model_validate_json(_TEST_LIBRARY_PATH.read_text(encoding="utf-8"))


def _patched_save(library: Library) -> None:
    """Save to the test path instead of the real library path."""
    import json

    _TEST_LIBRARY_PATH.write_text(
        json.dumps(library.model_dump(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def test_load_missing_file() -> None:
    """load_library returns empty Library when file does not exist."""
    with patch("src.library.manager.settings") as mock_settings:
        mock_settings.library_path = Path("./nonexistent_library.json")
        library = load_library()
    assert library.series == []
    print("  ✅ load_library: returns empty Library for missing file")


def test_create_series() -> None:
    """create_series adds a series to the library."""
    library = Library(series=[])
    updated = create_series(library, "red-rising", "Red Rising Saga")
    assert len(updated.series) == 1
    assert updated.series[0].id == "red-rising"
    assert updated.series[0].name == "Red Rising Saga"
    assert updated.series[0].books == []
    print("  ✅ create_series: series added correctly")


def test_create_series_duplicate() -> None:
    """create_series raises ValueError for duplicate series_id."""
    library = Library(series=[])
    updated = create_series(library, "red-rising", "Red Rising Saga")
    try:
        create_series(updated, "red-rising", "Duplicate")
        assert False, "Expected ValueError"
    except ValueError as exc:
        assert "already exists" in str(exc)
    print("  ✅ create_series: raises ValueError for duplicate id")


def test_get_series() -> None:
    """get_series finds the right series or returns None."""
    library = Library(series=[])
    library = create_series(library, "red-rising", "Red Rising Saga")

    found = get_series(library, "red-rising")
    assert found is not None
    assert found.id == "red-rising"

    missing = get_series(library, "nonexistent")
    assert missing is None
    print("  ✅ get_series: finds series and returns None for missing")


def test_upsert_book() -> None:
    """upsert_book adds a book to a series."""
    library = Library(series=[])
    library = create_series(library, "red-rising", "Red Rising Saga")

    book = Book(
        index=0,
        title="Red Rising",
        status=BookStatus.NOT_STARTED,
        chapters=[Chapter(index=0, label="Chapter 1")],
    )
    updated = upsert_book(library, "red-rising", book)

    series = get_series(updated, "red-rising")
    assert series is not None
    assert len(series.books) == 1
    assert series.books[0].title == "Red Rising"
    print("  ✅ upsert_book: book added to series")


def test_upsert_book_replace() -> None:
    """upsert_book replaces a book with the same index."""
    library = Library(series=[])
    library = create_series(library, "red-rising", "Red Rising Saga")

    book_v1 = Book(index=0, title="Red Rising v1", status=BookStatus.NOT_STARTED, chapters=[])
    book_v2 = Book(index=0, title="Red Rising v2", status=BookStatus.READING, chapters=[])
    library = upsert_book(library, "red-rising", book_v1)
    library = upsert_book(library, "red-rising", book_v2)

    series = get_series(library, "red-rising")
    assert series is not None
    assert len(series.books) == 1
    assert series.books[0].title == "Red Rising v2"
    print("  ✅ upsert_book: replaces book with same index (idempotent)")


def test_upsert_book_unknown_series() -> None:
    """upsert_book raises ValueError for unknown series."""
    library = Library(series=[])
    book = Book(index=0, title="Orphan", status=BookStatus.NOT_STARTED, chapters=[])
    try:
        upsert_book(library, "nonexistent", book)
        assert False, "Expected ValueError"
    except ValueError as exc:
        assert "not found" in str(exc)
    print("  ✅ upsert_book: raises ValueError for unknown series")


def test_save_load_roundtrip() -> None:
    """save_library + load_library preserves all data."""
    library = Library(series=[])
    library = create_series(library, "hail-mary", "Standalone")
    book = Book(
        index=0,
        title="Project Hail Mary",
        status=BookStatus.READING,
        chapters=[
            Chapter(index=0, label="Chapter 1"),
            Chapter(index=1, label="Chapter 2"),
        ],
        current_chapter_index=1,
    )
    library = upsert_book(library, "hail-mary", book)

    with patch("src.library.manager.settings") as mock_settings:
        mock_settings.library_path = _TEST_LIBRARY_PATH
        save_library(library)
        reloaded = load_library()

    series = get_series(reloaded, "hail-mary")
    assert series is not None
    assert len(series.books) == 1
    assert series.books[0].title == "Project Hail Mary"
    assert series.books[0].status == BookStatus.READING
    assert series.books[0].current_chapter_index == 1
    assert len(series.books[0].chapters) == 2
    print("  ✅ save/load round-trip: all data preserved")


def test_remove_series() -> None:
    """remove_series deletes the series from the library."""
    library = Library(series=[])
    library = create_series(library, "red-rising", "Red Rising Saga")
    library = create_series(library, "hail-mary", "Project Hail Mary")

    updated = remove_series(library, "red-rising")
    assert get_series(updated, "red-rising") is None
    assert get_series(updated, "hail-mary") is not None
    print("  ✅ remove_series: series removed, others untouched")


def test_remove_series_unknown() -> None:
    """remove_series raises ValueError for unknown series."""
    library = Library(series=[])
    try:
        remove_series(library, "nonexistent")
        assert False, "Expected ValueError"
    except ValueError as exc:
        assert "not found" in str(exc)
    print("  ✅ remove_series: raises ValueError for unknown series")


def test_remove_book() -> None:
    """remove_book deletes the book from a series."""
    library = Library(series=[])
    library = create_series(library, "red-rising", "Red Rising Saga")
    book0 = Book(index=0, title="Red Rising", status=BookStatus.NOT_STARTED, chapters=[])
    book1 = Book(index=1, title="Golden Son", status=BookStatus.NOT_STARTED, chapters=[])
    library = upsert_book(library, "red-rising", book0)
    library = upsert_book(library, "red-rising", book1)

    updated = remove_book(library, "red-rising", 0)
    series = get_series(updated, "red-rising")
    assert series is not None
    assert len(series.books) == 1
    assert series.books[0].title == "Golden Son"
    print("  ✅ remove_book: book removed, others untouched")


def test_remove_book_unknown_series() -> None:
    """remove_book raises ValueError for unknown series."""
    library = Library(series=[])
    try:
        remove_book(library, "nonexistent", 0)
        assert False, "Expected ValueError"
    except ValueError as exc:
        assert "not found" in str(exc)
    print("  ✅ remove_book: raises ValueError for unknown series")


def test_remove_book_unknown_index() -> None:
    """remove_book raises ValueError for unknown book index."""
    library = Library(series=[])
    library = create_series(library, "red-rising", "Red Rising Saga")
    try:
        remove_book(library, "red-rising", 99)
        assert False, "Expected ValueError"
    except ValueError as exc:
        assert "not found" in str(exc)
    print("  ✅ remove_book: raises ValueError for unknown book index")


def test_update_book_status_to_reading() -> None:
    """update_book_status sets READING with chapter index."""
    library = Library(series=[])
    library = create_series(library, "red-rising", "Red Rising Saga")
    book = Book(
        index=0,
        title="Red Rising",
        status=BookStatus.NOT_STARTED,
        chapters=[Chapter(index=i, label=f"Chapter {i}") for i in range(10)],
    )
    library = upsert_book(library, "red-rising", book)

    updated = update_book_status(library, "red-rising", 0, BookStatus.READING, 4)
    series = get_series(updated, "red-rising")
    assert series is not None
    assert series.books[0].status == BookStatus.READING
    assert series.books[0].current_chapter_index == 4
    print("  ✅ update_book_status: READING with chapter index set")


def test_update_book_status_to_completed() -> None:
    """update_book_status sets COMPLETED and clears chapter index."""
    library = Library(series=[])
    library = create_series(library, "red-rising", "Red Rising Saga")
    book = Book(
        index=0,
        title="Red Rising",
        status=BookStatus.READING,
        chapters=[],
        current_chapter_index=5,
    )
    library = upsert_book(library, "red-rising", book)

    updated = update_book_status(library, "red-rising", 0, BookStatus.COMPLETED, None)
    series = get_series(updated, "red-rising")
    assert series is not None
    assert series.books[0].status == BookStatus.COMPLETED
    assert series.books[0].current_chapter_index is None
    print("  ✅ update_book_status: COMPLETED clears current_chapter_index")


def test_update_book_status_unknown() -> None:
    """update_book_status raises ValueError for unknown series/book."""
    library = Library(series=[])
    try:
        update_book_status(library, "nonexistent", 0, BookStatus.COMPLETED, None)
        assert False, "Expected ValueError"
    except ValueError as exc:
        assert "not found" in str(exc)
    print("  ✅ update_book_status: raises ValueError for unknown series")


def cleanup() -> None:
    """Remove test library file."""
    if _TEST_LIBRARY_PATH.exists():
        _TEST_LIBRARY_PATH.unlink()
    print("  ✅ Cleanup: test file removed")


def main() -> None:
    """Run all library manager tests."""
    print("=" * 60)
    print("Library Manager Tests")
    print("=" * 60)

    test_load_missing_file()
    test_create_series()
    test_create_series_duplicate()
    test_get_series()
    test_upsert_book()
    test_upsert_book_replace()
    test_upsert_book_unknown_series()
    test_save_load_roundtrip()
    test_remove_series()
    test_remove_series_unknown()
    test_remove_book()
    test_remove_book_unknown_series()
    test_remove_book_unknown_index()
    test_update_book_status_to_reading()
    test_update_book_status_to_completed()
    test_update_book_status_unknown()
    cleanup()

    print("\n✅ All library manager tests passed!")


if __name__ == "__main__":
    main()
