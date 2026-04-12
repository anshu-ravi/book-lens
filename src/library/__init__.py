"""Library state management."""

from src.library.manager import (
    create_series,
    get_series,
    load_library,
    remove_book,
    remove_series,
    save_library,
    upsert_book,
)

__all__ = [
    "load_library",
    "save_library",
    "get_series",
    "create_series",
    "upsert_book",
    "remove_series",
    "remove_book",
]
