"""Persistence for cached Goodreads shelf data, in its own `goodreads.db`.

A refetchable cache like `index.db`, but kept out of both `index.db` (which
`booklens reindex` rebuilds from EPUBs and would otherwise destroy this) and
`progress.db` (precious user state this must never touch).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from booklens import paths
from booklens.goodreads.feed import GoodreadsBook, ShelfFetch, fetch_all_shelves

_DDL = """
CREATE TABLE IF NOT EXISTS goodreads_book(
  review_id       TEXT PRIMARY KEY,
  book_id         TEXT NOT NULL,
  title           TEXT NOT NULL,
  author          TEXT NOT NULL,
  isbn            TEXT,
  num_pages       INTEGER,
  published_year  INTEGER,
  description     TEXT,
  cover_small     TEXT,
  cover_medium    TEXT,
  cover_large     TEXT,
  average_rating  REAL,
  user_rating     INTEGER,
  user_review     TEXT,
  shelf           TEXT NOT NULL,
  custom_shelves  TEXT NOT NULL DEFAULT '',
  date_added      TEXT,
  date_read       TEXT,
  date_created    TEXT,
  date_started    TEXT,
  synced_at       TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_goodreads_book_shelf ON goodreads_book(shelf);

CREATE TABLE IF NOT EXISTS goodreads_sync(
  id          INTEGER PRIMARY KEY,
  shelf       TEXT NOT NULL,
  item_count  INTEGER NOT NULL,
  truncated   INTEGER NOT NULL,
  synced_at   TEXT NOT NULL
);
"""


@dataclass(frozen=True)
class SyncReport:
    shelf_counts: dict[str, int]
    truncated_shelves: tuple[str, ...]
    total_books: int


def connect(path: Path | None = None) -> sqlite3.Connection:
    """Open the Goodreads cache database, creating it if needed."""
    p = path if path is not None else paths.goodreads_db_path()
    conn = sqlite3.connect(str(p))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    init(conn)
    return conn


def init(conn: sqlite3.Connection) -> None:
    """Create the schema if it doesn't already exist."""
    conn.executescript(_DDL)
    conn.commit()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_book(row: sqlite3.Row) -> GoodreadsBook:
    custom = tuple(s for s in row["custom_shelves"].split(",") if s)
    return GoodreadsBook(
        review_id=row["review_id"],
        book_id=row["book_id"],
        title=row["title"],
        author=row["author"],
        isbn=row["isbn"],
        num_pages=row["num_pages"],
        published_year=row["published_year"],
        description=row["description"],
        cover_small=row["cover_small"],
        cover_medium=row["cover_medium"],
        cover_large=row["cover_large"],
        average_rating=row["average_rating"],
        user_rating=row["user_rating"],
        user_review=row["user_review"],
        shelf=row["shelf"],
        custom_shelves=custom,
        date_added=row["date_added"],
        date_read=row["date_read"],
        date_created=row["date_created"],
        date_started=row["date_started"],
    )


def upsert_shelf(conn: sqlite3.Connection, fetch: ShelfFetch) -> int:
    """Write one shelf's fetched books, idempotently.

    A book already on this shelf, or moved here from another shelf, ends up
    as exactly one row on `fetch.shelf`. When the fetch was NOT truncated,
    any row still on this shelf but absent from `fetch.books` is deleted --
    it was removed from Goodreads. A truncated fetch never deletes anything,
    because a partial feed can't tell an absence from a page it didn't see.
    """
    now = _now()
    seen_ids = []
    for book in fetch.books:
        seen_ids.append(book.review_id)
        conn.execute(
            """
            INSERT INTO goodreads_book(
                review_id, book_id, title, author, isbn, num_pages,
                published_year, description, cover_small, cover_medium,
                cover_large, average_rating, user_rating, user_review,
                shelf, custom_shelves, date_added, date_read, date_created,
                date_started, synced_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(review_id) DO UPDATE SET
                book_id=excluded.book_id, title=excluded.title, author=excluded.author,
                isbn=excluded.isbn, num_pages=excluded.num_pages,
                published_year=excluded.published_year, description=excluded.description,
                cover_small=excluded.cover_small, cover_medium=excluded.cover_medium,
                cover_large=excluded.cover_large, average_rating=excluded.average_rating,
                user_rating=excluded.user_rating, user_review=excluded.user_review,
                shelf=excluded.shelf, custom_shelves=excluded.custom_shelves,
                date_added=excluded.date_added, date_read=excluded.date_read,
                date_created=excluded.date_created, date_started=excluded.date_started,
                synced_at=excluded.synced_at
            """,
            (
                book.review_id, book.book_id, book.title, book.author, book.isbn,
                book.num_pages, book.published_year, book.description,
                book.cover_small, book.cover_medium, book.cover_large,
                book.average_rating, book.user_rating, book.user_review,
                book.shelf, ",".join(book.custom_shelves), book.date_added,
                book.date_read, book.date_created, book.date_started, now,
            ),
        )

    if not fetch.truncated:
        if seen_ids:
            placeholders = ",".join("?" * len(seen_ids))
            conn.execute(
                f"DELETE FROM goodreads_book WHERE shelf = ? AND review_id NOT IN ({placeholders})",
                (fetch.shelf, *seen_ids),
            )
        else:
            # `NOT IN (NULL)` is always unknown, never true, so an empty
            # `seen_ids` needs its own branch -- otherwise a shelf emptied on
            # Goodreads (every book moved off it) never gets pruned locally.
            conn.execute("DELETE FROM goodreads_book WHERE shelf = ?", (fetch.shelf,))

    conn.execute(
        "INSERT INTO goodreads_sync(shelf, item_count, truncated, synced_at) VALUES (?, ?, ?, ?)",
        (fetch.shelf, len(fetch.books), int(fetch.truncated), now),
    )
    conn.commit()
    return len(fetch.books)


def sync(conn: sqlite3.Connection, user_id: str, *, dnf_shelf: str | None = None, client=None) -> SyncReport:
    """Fetch every configured shelf and persist it, returning a per-shelf report.

    Raises `GoodreadsError` (propagated from `fetch_all_shelves`) if any
    shelf fetch fails -- a partial sync is not silently accepted.
    """
    fetches = fetch_all_shelves(user_id, dnf_shelf=dnf_shelf, client=client)

    shelf_counts = {}
    truncated_shelves = []
    for shelf, fetch in fetches.items():
        upsert_shelf(conn, fetch)
        shelf_counts[shelf] = len(fetch.books)
        if fetch.truncated:
            truncated_shelves.append(shelf)

    return SyncReport(
        shelf_counts=shelf_counts,
        truncated_shelves=tuple(truncated_shelves),
        total_books=sum(shelf_counts.values()),
    )


def books_on_shelf(conn: sqlite3.Connection, shelf: str) -> list[GoodreadsBook]:
    """All cached books currently on one shelf."""
    rows = conn.execute(
        "SELECT * FROM goodreads_book WHERE shelf = ? ORDER BY title", (shelf,)
    ).fetchall()
    return [_row_to_book(r) for r in rows]


def all_books(conn: sqlite3.Connection) -> list[GoodreadsBook]:
    """Every cached book, across all shelves."""
    rows = conn.execute("SELECT * FROM goodreads_book ORDER BY shelf, title").fetchall()
    return [_row_to_book(r) for r in rows]
