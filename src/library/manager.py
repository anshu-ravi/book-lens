"""Library state persistence and CRUD operations.

The library is stored as a single JSON file (library.json). It is read on every
request and written on every mutation — acceptable for a single-user app with a
small file. All functions are pure: they take and return Library objects without
holding state themselves.
"""

import json

from src.config import settings
from src.models import Book, BookStatus, Library, Series


import json
from typing import Optional

from src.supabase_client import get_supabase_client
from src.models import Book, BookStatus, Library, Series, Chapter

async def load_library(user_id: str) -> Library:
    """Read library state from Supabase for a specific user.

    Args:
        user_id: The authenticated user's ID.

    Returns:
        Library object containing all series and books.
    """
    client = get_supabase_client()
    
    # Fetch series for this user
    series_resp = client.table("series").select("*").filter("user_id", "eq", user_id).execute()
    series_list = []
    
    for s_data in series_resp.data:
        # Fetch books for this series and user
        books_resp = client.table("books").select("*").filter("series_id", "eq", s_data["id"]).filter("user_id", "eq", user_id).execute()
        books = []
        for b_data in books_resp.data:
            # Parse chapters from JSONB
            chapters_data = b_data.get("chapters", [])
            chapters = [Chapter(index=c["index"], label=c["label"]) for c in chapters_data]
            
            books.append(Book(
                index=b_data["index"],
                title=b_data["title"],
                status=BookStatus(b_data["status"]),
                chapters=chapters,
                current_chapter_index=b_data.get("current_chapter_index"),
                has_cover=b_data.get("has_cover", False)
            ))
        
        series_list.append(Series(
            id=s_data["id"],
            name=s_data["name"],
            books=books
        ))
        
    return Library(series=series_list)


async def get_series(series_id: str, user_id: str) -> Series | None:
    """Find a series by ID and user_id in Supabase."""
    client = get_supabase_client()
    resp = client.table("series").select("*").filter("id", "eq", series_id).filter("user_id", "eq", user_id).execute()
    if not resp.data:
        return None
    
    s_data = resp.data[0]
    # Fetch books
    books_resp = client.table("books").select("*").filter("series_id", "eq", series_id).filter("user_id", "eq", user_id).execute()
    books = []
    for b_data in books_resp.data:
        chapters_data = b_data.get("chapters", [])
        chapters = [Chapter(index=c["index"], label=c["label"]) for c in chapters_data]
        books.append(Book(
            index=b_data["index"],
            title=b_data["title"],
            status=BookStatus(b_data["status"]),
            chapters=chapters,
            current_chapter_index=b_data.get("current_chapter_index"),
            has_cover=b_data.get("has_cover", False)
        ))
        
    return Series(id=s_data["id"], name=s_data["name"], books=books)


async def create_series(series_id: str, name: str, user_id: str) -> None:
    """Add a new series to Supabase for a user."""
    client = get_supabase_client()
    client.table("series").insert({"id": series_id, "name": name, "user_id": user_id}).execute()


async def remove_series(series_id: str, user_id: str) -> None:
    """Remove a series and all its books."""
    client = get_supabase_client()
    client.table("series").delete().filter("id", "eq", series_id).filter("user_id", "eq", user_id).execute()


async def remove_book(series_id: str, book_index: int, user_id: str) -> None:
    """Remove a single book from a series."""
    client = get_supabase_client()
    client.table("books").delete().filter("series_id", "eq", series_id).filter("index", "eq", book_index).filter("user_id", "eq", user_id).execute()


async def update_book_status(
    series_id: str,
    book_index: int,
    status: BookStatus,
    current_chapter_index: int | None,
    user_id: str,
) -> None:
    """Update a book's reading status."""
    client = get_supabase_client()
    update_data = {"status": status.value}
    if status == BookStatus.READING:
        update_data["current_chapter_index"] = current_chapter_index
    else:
        update_data["current_chapter_index"] = None
        
    client.table("books").update(update_data).filter("series_id", "eq", series_id).filter("index", "eq", book_index).filter("user_id", "eq", user_id).execute()


async def upsert_book(series_id: str, book: Book, user_id: str) -> None:
    """Add or replace a book within a series."""
    client = get_supabase_client()
    book_data = {
        "series_id": series_id,
        "user_id": user_id,
        "index": book.index,
        "title": book.title,
        "status": book.status.value,
        "chapters": [c.model_dump() for c in book.chapters],
        "current_chapter_index": book.current_chapter_index,
        "has_cover": book.has_cover
    }
    client.table("books").upsert(book_data).execute()
