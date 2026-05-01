"""Library state management."""

from src.library.manager import (
    load_library,
    upsert_canonical_book,
    upsert_user_book,
    get_series_by_canonical_id,
    get_book_by_canonical_id,
    remove_user_book,
    remove_user_series,
    other_users_have_book,
    other_users_have_series,
    update_user_book_status,
    set_user_book_cover,
)

__all__ = [
    "load_library",
    "upsert_canonical_book",
    "upsert_user_book",
    "get_series_by_canonical_id",
    "get_book_by_canonical_id",
    "remove_user_book",
    "remove_user_series",
    "other_users_have_book",
    "other_users_have_series",
    "update_user_book_status",
    "set_user_book_cover",
]
