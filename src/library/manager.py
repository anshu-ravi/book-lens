"""Library state persistence using the single per-user books table."""

import logging
import re
from typing import Optional

from src.config import settings
from src.supabase_client import get_supabase_client
from src.models import Book, BookRecord, BookStatus, Chapter, Library, Series

logger = logging.getLogger(__name__)


def _cover_url(user_id: str, book_id: str) -> str:
    """Return the public Supabase Storage URL for a book cover."""
    return f"{settings.supabase_url}/storage/v1/object/public/covers/{user_id}/{book_id}/cover.jpg"


def _book_from_row(row: dict, book_index: int, user_id: str) -> Book:
    """Build a Book from a books table row."""
    chapters_data = row.get("chapters") or []
    chapters = [Chapter(index=c["index"], label=c["label"]) for c in chapters_data]
    book_id = row["id"]
    has_cover = row.get("has_cover", False)
    return Book(
        id=book_id,
        index=book_index,
        title=row["title"],
        author=row.get("author"),
        status=BookStatus(row.get("status", "not_started")),
        chapters=chapters,
        current_chapter_index=row.get("current_chapter_index"),
        has_cover=has_cover,
        cover_url=_cover_url(user_id, book_id) if has_cover else None,
        position_in_series=row.get("position_in_series"),
        series_name=row.get("series_name"),
        is_series=row.get("is_series", False),
        uploaded_at=row.get("uploaded_at"),
    )


def upsert_book(record: BookRecord) -> None:
    """Insert or update a books row (idempotent on user_id, series_id, id)."""
    client = get_supabase_client()
    client.table("books").upsert(
        {
            "id": record.id,
            "user_id": record.user_id,
            "series_id": record.series_id,
            "title": record.title,
            "author": record.author,
            "series_name": record.series_name,
            "position_in_series": record.position_in_series,
            "is_series": record.is_series,
            "chapters": [c.model_dump() for c in record.chapters],
            "status": record.status.value,
            "current_chapter_index": record.current_chapter_index,
            "epub_path": record.epub_path,
            "has_cover": record.has_cover,
        },
        on_conflict="id",
    ).execute()


def _group_into_series(rows: list[dict], user_id: str) -> list[Series]:
    """Group books table rows into Series objects."""
    groups: dict[str, list[dict]] = {}
    for row in rows:
        sid = row["series_id"]
        groups.setdefault(sid, []).append(row)

    series_list: list[Series] = []
    for series_id, group_rows in groups.items():
        # Sort by position_in_series; nulls go last (insertion order)
        group_rows.sort(key=lambda r: (r.get("position_in_series") is None, r.get("position_in_series")))

        # Assign book indices 0, 1, 2, ... based on sorted order
        books = [_book_from_row(r, idx, user_id) for idx, r in enumerate(group_rows)]
        series_name = group_rows[0].get("series_name") or group_rows[0]["title"]
        series_list.append(Series(id=series_id, name=series_name, books=books))

    return series_list


async def load_library(user_id: str) -> Library:
    """Read library state from Supabase for a specific user."""
    client = get_supabase_client()
    resp = (
        client.table("books")
        .select("*")
        .filter("user_id", "eq", user_id)
        .execute()
    )
    if not resp.data:
        return Library(series=[])
    return Library(series=_group_into_series(resp.data, user_id))


async def get_series_by_id(series_id: str, user_id: str) -> Series | None:
    """Find a series by series_id for this user."""
    client = get_supabase_client()
    resp = (
        client.table("books")
        .select("*")
        .filter("user_id", "eq", user_id)
        .filter("series_id", "eq", series_id)
        .execute()
    )
    if not resp.data:
        return None
    series_list = _group_into_series(resp.data, user_id)
    return series_list[0] if series_list else None


async def get_book_by_id(book_id: str, user_id: str) -> Book | None:
    """Fetch a single book by its id."""
    client = get_supabase_client()
    resp = (
        client.table("books")
        .select("*")
        .filter("user_id", "eq", user_id)
        .filter("id", "eq", book_id)
        .execute()
    )
    if not resp.data:
        return None
    row = resp.data[0]
    return _book_from_row(row, row["book_index"], user_id)


async def remove_book(book_id: str, user_id: str) -> None:
    """Remove a single book row."""
    client = get_supabase_client()
    client.table("books").delete().filter("id", "eq", book_id).filter("user_id", "eq", user_id).execute()


async def remove_series(series_id: str, user_id: str) -> None:
    """Remove all books for a series (user-scoped)."""
    client = get_supabase_client()
    client.table("books").delete().filter("series_id", "eq", series_id).filter("user_id", "eq", user_id).execute()


async def update_book_status(
    book_id: str,
    status: BookStatus,
    current_chapter_index: int | None,
    user_id: str,
) -> None:
    """Update reading status for a books row."""
    client = get_supabase_client()
    update_data: dict = {"status": status.value}
    if status == BookStatus.READING:
        update_data["current_chapter_index"] = current_chapter_index
    else:
        update_data["current_chapter_index"] = None
    client.table("books").update(update_data).filter("id", "eq", book_id).filter("user_id", "eq", user_id).execute()


async def set_book_cover(book_id: str, user_id: str, has_cover: bool) -> None:
    """Mark whether this user has a cover for their copy of the book."""
    client = get_supabase_client()
    client.table("books").update({"has_cover": has_cover}).filter("id", "eq", book_id).filter("user_id", "eq", user_id).execute()


def update_book_series(
    book_id: str,
    user_id: str,
    series_name: Optional[str],
    position_in_series: Optional[float],
) -> None:
    """Update series metadata on a books row.

    Derives series_id from series_name slug. If series_name is empty,
    treats the book as standalone (series_id = slugified book title).
    """
    client = get_supabase_client()

    if series_name and series_name.strip():
        slug = series_name.strip().lower()
        slug = re.sub(r"[^a-z0-9\s-]", "", slug)
        slug = re.sub(r"\s+", "-", slug)
        slug = re.sub(r"-+", "-", slug)
        series_id = slug
    else:
        series_name = None
        series_id = book_id  # standalone convention

    client.table("books").update(
        {
            "series_name": series_name,
            "position_in_series": position_in_series,
            "series_id": series_id,
        }
    ).filter("id", "eq", book_id).filter("user_id", "eq", user_id).execute()
