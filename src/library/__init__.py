"""Library state management."""

from src.library.manager import (
    load_library,
    upsert_book,
    get_series_by_id,
    get_book_by_id,
    remove_book,
    remove_series,
    update_book_status,
    set_book_cover,
    update_book_series,
)

__all__ = [
    "load_library",
    "upsert_book",
    "get_series_by_id",
    "get_book_by_id",
    "remove_book",
    "remove_series",
    "update_book_status",
    "set_book_cover",
    "update_book_series",
]
