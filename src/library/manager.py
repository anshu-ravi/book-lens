"""Library state persistence using canonical_books + user_books tables."""

import logging
import re
from typing import Optional

from src.config import settings
from src.supabase_client import get_supabase_client
from src.models import Book, BookStatus, CanonicalBook, Chapter, Library, Series, UserBook

logger = logging.getLogger(__name__)


def _cover_url(user_id: str, canonical_book_id: str) -> str:
    """Return the public Supabase Storage URL for a book cover."""
    return f"{settings.supabase_url}/storage/v1/object/public/covers/{user_id}/{canonical_book_id}/cover.jpg"


def _book_from_rows(cb_data: dict, ub_data: dict, book_index: int, user_id: str) -> Book:
    """Build a Book from canonical_books + user_books rows."""
    chapters_data = cb_data.get("chapters") or []
    chapters = [Chapter(index=c["index"], label=c["label"]) for c in chapters_data]
    has_cover = ub_data.get("has_cover", False)
    canonical_book_id = cb_data["id"]
    return Book(
        index=book_index,
        canonical_book_id=canonical_book_id,
        title=cb_data["title"],
        author=cb_data.get("author"),
        status=BookStatus(ub_data.get("status", "not_started")),
        chapters=chapters,
        current_chapter_index=ub_data.get("current_chapter_index"),
        has_cover=has_cover,
        cover_url=_cover_url(user_id, canonical_book_id) if has_cover else None,
        series_position=cb_data.get("series_position"),
        series_name=cb_data.get("series_name"),
    )


def upsert_canonical_book(cb: CanonicalBook) -> None:
    """Insert or update a canonical book row (idempotent on id)."""
    client = get_supabase_client()
    client.table("canonical_books").upsert({
        "id": cb.id,
        "ol_id": cb.ol_id,
        "title": cb.title,
        "author": cb.author,
        "series_name": cb.series_name,
        "series_position": cb.series_position,
        "canonical_series_id": cb.canonical_series_id,
        "cover_url": cb.cover_url,
        "chapters": [c.model_dump() for c in cb.chapters],
    }).execute()


def upsert_user_book(ub: UserBook) -> None:
    """Insert or update a user_books row."""
    client = get_supabase_client()
    client.table("user_books").upsert({
        "user_id": ub.user_id,
        "canonical_book_id": ub.canonical_book_id,
        "status": ub.status.value,
        "current_chapter_index": ub.current_chapter_index,
        "epub_path": ub.epub_path,
        "has_cover": ub.has_cover,
    }, on_conflict="user_id,canonical_book_id").execute()


def update_canonical_book_series(
    canonical_book_id: str,
    series_name: Optional[str],
    series_position: Optional[float],
) -> None:
    """Update only series metadata on a canonical_books row.

    Auto-derives canonical_series_id from series_name using the same slug
    rule as the upload flow. If series_name is None/empty, treats book as
    standalone (canonical_series_id = canonical_book_id).
    """
    client = get_supabase_client()

    if series_name and series_name.strip():
        slug = series_name.strip().lower()
        slug = re.sub(r'[^a-z0-9\s-]', '', slug)
        slug = re.sub(r'\s+', '-', slug)
        slug = re.sub(r'-+', '-', slug)
        canonical_series_id = slug
    else:
        series_name = None
        canonical_series_id = canonical_book_id  # standalone convention

    client.table("canonical_books").update({
        "series_name": series_name,
        "series_position": series_position,
        "canonical_series_id": canonical_series_id,
    }).eq("id", canonical_book_id).execute()


def _group_into_series(rows: list[dict], user_id: str) -> list[Series]:
    """Group (canonical_books + user_books) rows into Series objects."""
    groups: dict[str, list[dict]] = {}
    for row in rows:
        csid = row["canonical_series_id"]
        groups.setdefault(csid, []).append(row)

    series_list: list[Series] = []
    for canonical_series_id, group_rows in groups.items():
        group_rows.sort(key=lambda r: r.get("series_position") or float("inf"))

        books: list[Book] = []
        for book_index, row in enumerate(group_rows):
            cb_data = {k: row[k] for k in ("id", "title", "author", "series_name", "series_position", "cover_url", "chapters")}
            ub_data = {k: row.get(k) for k in ("status", "current_chapter_index", "epub_path", "has_cover")}
            books.append(_book_from_rows(cb_data, ub_data, book_index, user_id))  # series_name passed via cb_data

        series_name = group_rows[0].get("series_name") or group_rows[0]["title"]
        series_list.append(Series(id=canonical_series_id, name=series_name, books=books))

    return series_list


async def load_library(user_id: str) -> Library:
    """Read library state from Supabase for a specific user."""
    client = get_supabase_client()
    resp = (
        client.table("user_books")
        .select("*, canonical_books(*)")
        .filter("user_id", "eq", user_id)
        .execute()
    )
    if not resp.data:
        return Library(series=[])

    rows: list[dict] = []
    for ub_row in resp.data:
        cb = ub_row.pop("canonical_books", {}) or {}
        # Start with ub_row fields, then overlay cb fields so cb["id"] wins over ub_row["id"]
        merged = {**ub_row, **cb}
        # Re-apply user_books-specific fields that cb may have clobbered
        for ub_key in ("status", "current_chapter_index", "epub_path", "has_cover", "user_id", "canonical_book_id"):
            if ub_key in ub_row:
                merged[ub_key] = ub_row[ub_key]
        rows.append(merged)

    return Library(series=_group_into_series(rows, user_id))


async def get_series_by_canonical_id(canonical_series_id: str, user_id: str) -> Series | None:
    """Find a series by canonical_series_id for this user."""
    client = get_supabase_client()
    resp = (
        client.table("user_books")
        .select("*, canonical_books(*)")
        .filter("user_id", "eq", user_id)
        .execute()
    )
    if not resp.data:
        return None

    rows: list[dict] = []
    for ub_row in resp.data:
        cb = ub_row.pop("canonical_books", {}) or {}
        if not cb:
            continue
        if cb.get("canonical_series_id") != canonical_series_id:
            continue
        merged = {**ub_row, **cb}
        for ub_key in ("status", "current_chapter_index", "epub_path", "has_cover", "user_id", "canonical_book_id"):
            if ub_key in ub_row:
                merged[ub_key] = ub_row[ub_key]
        rows.append(merged)

    if not rows:
        return None

    series_list = _group_into_series(rows, user_id)
    return series_list[0] if series_list else None


async def get_book_by_canonical_id(canonical_book_id: str, user_id: str) -> Book | None:
    """Fetch a single book and its series context."""
    client = get_supabase_client()
    resp = (
        client.table("user_books")
        .select("*, canonical_books(*)")
        .filter("user_id", "eq", user_id)
        .filter("canonical_book_id", "eq", canonical_book_id)
        .execute()
    )
    if not resp.data:
        return None
    ub_row = resp.data[0]
    cb = ub_row.pop("canonical_books", {}) or {}
    series = await get_series_by_canonical_id(cb.get("canonical_series_id", canonical_book_id), user_id)
    if series is None:
        return None
    return next((b for b in series.books if b.canonical_book_id == canonical_book_id), None)


async def remove_user_book(canonical_book_id: str, user_id: str) -> None:
    """Remove a user_books row (does not touch canonical_books or knowledge)."""
    client = get_supabase_client()
    client.table("user_books").delete().filter("canonical_book_id", "eq", canonical_book_id).filter("user_id", "eq", user_id).execute()


async def remove_user_series(canonical_series_id: str, user_id: str) -> None:
    """Remove all user_books for a series (user-scoped)."""
    client = get_supabase_client()
    resp = (
        client.table("user_books")
        .select("canonical_book_id, canonical_books(canonical_series_id)")
        .filter("user_id", "eq", user_id)
        .execute()
    )
    ids_to_delete = [
        row["canonical_book_id"]
        for row in (resp.data or [])
        if (row.get("canonical_books") or {}).get("canonical_series_id") == canonical_series_id
    ]
    for cid in ids_to_delete:
        client.table("user_books").delete().filter("canonical_book_id", "eq", cid).filter("user_id", "eq", user_id).execute()


async def other_users_have_book(canonical_book_id: str, excluding_user_id: str) -> bool:
    """Return True if any other user has this canonical book in their library."""
    client = get_supabase_client()
    resp = (
        client.table("user_books")
        .select("id")
        .filter("canonical_book_id", "eq", canonical_book_id)
        .neq("user_id", excluding_user_id)
        .limit(1)
        .execute()
    )
    return bool(resp.data)


async def other_users_have_series(canonical_series_id: str, excluding_user_id: str) -> bool:
    """Return True if any other user has any book from this series."""
    client = get_supabase_client()
    resp = (
        client.table("user_books")
        .select("canonical_book_id, canonical_books(canonical_series_id)")
        .neq("user_id", excluding_user_id)
        .execute()
    )
    for row in (resp.data or []):
        if (row.get("canonical_books") or {}).get("canonical_series_id") == canonical_series_id:
            return True
    return False


async def update_user_book_status(
    canonical_book_id: str,
    status: BookStatus,
    current_chapter_index: int | None,
    user_id: str,
) -> None:
    """Update reading status for a user_books row."""
    client = get_supabase_client()
    update_data: dict = {"status": status.value}
    if status == BookStatus.READING:
        update_data["current_chapter_index"] = current_chapter_index
    else:
        update_data["current_chapter_index"] = None
    client.table("user_books").update(update_data).filter("canonical_book_id", "eq", canonical_book_id).filter("user_id", "eq", user_id).execute()


async def set_user_book_cover(canonical_book_id: str, user_id: str, has_cover: bool) -> None:
    """Mark whether this user has a cover for their copy of the book."""
    client = get_supabase_client()
    client.table("user_books").update({"has_cover": has_cover}).filter("canonical_book_id", "eq", canonical_book_id).filter("user_id", "eq", user_id).execute()
