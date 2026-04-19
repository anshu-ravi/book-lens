"""Library state management."""

from src.library.manager import (
    create_series,
    get_series,
    load_library,
    remove_book,
    remove_series,
    update_book_status,
    upsert_book,
)

__all__ = [
    "load_library",
    "get_series",
    "create_series",
    "upsert_book",
    "remove_series",
    "remove_book",
    "update_book_status",
]
