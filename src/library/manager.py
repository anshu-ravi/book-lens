"""Library state persistence and CRUD operations.

The library is stored as a single JSON file (library.json). It is read on every
request and written on every mutation — acceptable for a single-user app with a
small file. All functions are pure: they take and return Library objects without
holding state themselves.
"""

import json

from src.config import settings
from src.models import Book, BookStatus, Library, Series


def load_library() -> Library:
    """Read library state from disk.

    Returns:
        Persisted Library, or an empty Library if the file does not exist yet.
    """
    path = settings.library_path
    if not path.exists():
        return Library(series=[])
    return Library.model_validate_json(path.read_text(encoding="utf-8"))


def save_library(library: Library) -> None:
    """Write library state to disk.

    Args:
        library: Current library state to persist.
    """
    path = settings.library_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(library.model_dump(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def get_series(library: Library, series_id: str) -> Series | None:
    """Find a series by ID.

    Args:
        library: Current library state.
        series_id: Series identifier to look up.

    Returns:
        Matching Series, or None if not found.
    """
    for series in library.series:
        if series.id == series_id:
            return series
    return None


def create_series(library: Library, series_id: str, name: str) -> Library:
    """Add a new series to the library.

    Args:
        library: Current library state.
        series_id: Unique identifier for the series (e.g. "red-rising").
        name: Human-readable series name (e.g. "Red Rising Saga").

    Returns:
        Updated Library with the new series appended.

    Raises:
        ValueError: If a series with series_id already exists.
    """
    if get_series(library, series_id) is not None:
        raise ValueError(f"Series '{series_id}' already exists.")
    new_series = Series(id=series_id, name=name, books=[])
    return Library(series=library.series + [new_series])


def remove_series(library: Library, series_id: str) -> Library:
    """Remove a series and all its books from the library.

    Args:
        library: Current library state.
        series_id: Series to remove.

    Returns:
        Updated Library without the series.

    Raises:
        ValueError: If series_id does not exist.
    """
    if get_series(library, series_id) is None:
        raise ValueError(f"Series '{series_id}' not found.")
    return Library(series=[s for s in library.series if s.id != series_id])


def remove_book(library: Library, series_id: str, book_index: int) -> Library:
    """Remove a single book from a series.

    Args:
        library: Current library state.
        series_id: Series containing the book.
        book_index: 0-based index of the book to remove.

    Returns:
        Updated Library with the book removed.

    Raises:
        ValueError: If series_id does not exist.
        ValueError: If no book with book_index exists in the series.
    """
    series = get_series(library, series_id)
    if series is None:
        raise ValueError(f"Series '{series_id}' not found.")
    if not any(b.index == book_index for b in series.books):
        raise ValueError(f"Book {book_index} not found in series '{series_id}'.")

    updated_series = [
        (
            Series(
                id=s.id,
                name=s.name,
                books=[b for b in s.books if b.index != book_index],
            )
            if s.id == series_id
            else s
        )
        for s in library.series
    ]
    return Library(series=updated_series)


def update_book_status(
    library: Library,
    series_id: str,
    book_index: int,
    status: BookStatus,
    current_chapter_index: int | None,
) -> Library:
    """Update a book's reading status and current chapter progress.

    Args:
        library: Current library state.
        series_id: Series containing the book.
        book_index: 0-based index of the book to update.
        status: New reading status.
        current_chapter_index: Chapter the user is currently reading (required
            when status is READING, ignored otherwise).

    Returns:
        Updated Library.

    Raises:
        ValueError: If series_id or book_index does not exist.
    """
    series = get_series(library, series_id)
    if series is None:
        raise ValueError(f"Series '{series_id}' not found.")

    book = next((b for b in series.books if b.index == book_index), None)
    if book is None:
        raise ValueError(f"Book {book_index} not found in series '{series_id}'.")

    updated_book = Book(
        index=book.index,
        title=book.title,
        status=status,
        chapters=book.chapters,
        current_chapter_index=current_chapter_index if status == BookStatus.READING else None,
    )
    return upsert_book(library, series_id, updated_book)


def upsert_book(library: Library, series_id: str, book: Book) -> Library:
    """Add or replace a book within a series.

    If a book with the same index already exists in the series it is replaced,
    making re-uploads idempotent.

    Args:
        library: Current library state.
        series_id: Series to update.
        book: Book to add or replace (matched by book.index).

    Returns:
        Updated Library.

    Raises:
        ValueError: If series_id does not exist.
    """
    if get_series(library, series_id) is None:
        raise ValueError(f"Series '{series_id}' not found.")

    updated_series = []
    for series in library.series:
        if series.id != series_id:
            updated_series.append(series)
            continue
        existing_books = [b for b in series.books if b.index != book.index]
        updated_series.append(Series(id=series.id, name=series.name, books=existing_books + [book]))

    return Library(series=updated_series)
