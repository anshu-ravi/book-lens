"""Persistence for cached Goodreads shelf data, in its own `goodreads.db`.

A refetchable cache like `index.db`, but kept out of both `index.db` (which
`booklens reindex` rebuilds from EPUBs and would otherwise destroy this) and
`progress.db` (precious user state this must never touch).
"""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Sequence

from booklens import paths
from booklens.goodreads.enrich import fetch_genres, fetch_review_rows
from booklens.goodreads.feed import (GoodreadsBook, GoodreadsError,
                                      ShelfFetch, fetch_all_shelves)

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

CREATE TABLE IF NOT EXISTS goodreads_setting(
  key    TEXT PRIMARY KEY,
  value  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS goodreads_link(
  book_id            TEXT PRIMARY KEY,
  goodreads_book_id  TEXT NOT NULL,
  linked_at          TEXT NOT NULL,
  source             TEXT NOT NULL
);
"""


@dataclass(frozen=True)
class SyncReport:
    shelf_counts: dict[str, int]
    truncated_shelves: tuple[str, ...]
    total_books: int


def connect(path: Path | None = None, *, check_same_thread: bool = True) -> sqlite3.Connection:
    """Open the Goodreads cache database, creating it if needed.

    `check_same_thread=False` is for a connection handed off to live longer
    than the thread that opened it (e.g. a FastAPI request dependency).
    """
    p = path if path is not None else paths.goodreads_db_path()
    conn = sqlite3.connect(str(p), check_same_thread=check_same_thread)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    init(conn)
    return conn


def init(conn: sqlite3.Connection) -> None:
    """Create the schema if it doesn't already exist."""
    conn.executescript(_DDL)
    conn.commit()
    _apply_additive_migrations(conn)


# Enrichment columns added after the initial schema -- guarded ALTERs, one
# per column, so an existing goodreads.db picks them up without a rebuild.
_ADDITIVE_COLUMNS = {
    "read_count": "INTEGER",
    "genres": "TEXT",
    "genres_fetched_at": "TEXT",
    "enriched_at": "TEXT",
}


def _apply_additive_migrations(conn: sqlite3.Connection) -> None:
    """In-place migration for the cookie-enrichment columns."""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(goodreads_book)")}
    changed = False
    for name, decl in _ADDITIVE_COLUMNS.items():
        if name not in cols:
            conn.execute(f"ALTER TABLE goodreads_book ADD COLUMN {name} {decl}")
            changed = True
    if changed:
        conn.commit()


def get_setting(conn: sqlite3.Connection, key: str) -> str | None:
    """A stored setting value (`user_id` or `dnf_shelf`), or `None` if unset."""
    row = conn.execute("SELECT value FROM goodreads_setting WHERE key = ?", (key,)).fetchone()
    return row["value"] if row is not None else None


def set_setting(conn: sqlite3.Connection, key: str, value: str | None) -> None:
    """Store a setting value, or clear it when `value` is `None`."""
    if value is None:
        conn.execute("DELETE FROM goodreads_setting WHERE key = ?", (key,))
    else:
        conn.execute(
            "INSERT INTO goodreads_setting(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
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
                synced_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(review_id) DO UPDATE SET
                book_id=excluded.book_id, title=excluded.title, author=excluded.author,
                isbn=excluded.isbn, num_pages=excluded.num_pages,
                published_year=excluded.published_year, description=excluded.description,
                cover_small=excluded.cover_small, cover_medium=excluded.cover_medium,
                cover_large=excluded.cover_large, average_rating=excluded.average_rating,
                user_rating=excluded.user_rating, user_review=excluded.user_review,
                shelf=excluded.shelf, custom_shelves=excluded.custom_shelves,
                -- date_added is deliberately absent: RSS reports the last
                -- shelf change, so re-syncing a finished book would overwrite
                -- the true added date with its finish date. First insert wins,
                -- and enrichment corrects it from the authenticated table.
                date_read=excluded.date_read,
                date_created=excluded.date_created,
                synced_at=excluded.synced_at
            """,
            (
                book.review_id, book.book_id, book.title, book.author, book.isbn,
                book.num_pages, book.published_year, book.description,
                book.cover_small, book.cover_medium, book.cover_large,
                book.average_rating, book.user_rating, book.user_review,
                book.shelf, ",".join(book.custom_shelves), book.date_added,
                book.date_read, book.date_created, now,
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
    shelf fetch fails -- a partial sync is not silently accepted. Re-links
    against `index.db` at the end -- pure local computation, no network --
    so newly-synced shelf entries pick up an EPUB match immediately.
    """
    fetches = fetch_all_shelves(user_id, dnf_shelf=dnf_shelf, client=client)

    shelf_counts = {}
    truncated_shelves = []
    for shelf, fetch in fetches.items():
        upsert_shelf(conn, fetch)
        shelf_counts[shelf] = len(fetch.books)
        if fetch.truncated:
            truncated_shelves.append(shelf)

    from booklens import db as _db
    from booklens.goodreads.link import autolink

    iconn = _db.connect_index()
    try:
        autolink(iconn, conn)
    finally:
        iconn.close()

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


# -- cookie-authenticated enrichment ------------------------------------------


@dataclass(frozen=True)
class EnrichReport:
    rows_updated: int
    start_dates_found: int
    genres_fetched: int
    genres_skipped: int


def apply_review_rows(conn: sqlite3.Connection, rows: Iterable[ReviewRow]) -> int:
    """Fold authenticated review-table data into `goodreads_book`, additive only.

    Sets `date_started`, `read_count`, and `enriched_at` on every matching
    row; fills `date_read` only where it is currently null. Never deletes --
    a row with no matching `review_id` is simply left untouched.

    `date_added` is overwritten rather than filled, because RSS's version of
    it is the last shelf-entry change (the finish date, for a finished book)
    and only this table reports when the book was actually added.
    """
    now = _now()
    updated = 0
    for row in rows:
        cur = conn.execute(
            """
            UPDATE goodreads_book SET
                date_started = ?,
                read_count = ?,
                date_read = COALESCE(date_read, ?),
                date_added = COALESCE(?, date_added),
                enriched_at = ?
            WHERE review_id = ?
            """,
            (
                row.date_started,
                row.read_count,
                row.date_read,
                row.date_added,
                now,
                row.review_id,
            ),
        )
        updated += cur.rowcount
    conn.commit()
    return updated


def books_needing_genres(conn: sqlite3.Connection, *, refresh: bool = False) -> list[tuple[str, str]]:
    """`(book_id, title)` for every book missing a genre fetch, or all books when `refresh`."""
    if refresh:
        rows = conn.execute(
            "SELECT DISTINCT book_id, title FROM goodreads_book ORDER BY title"
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT DISTINCT book_id, title FROM goodreads_book "
            "WHERE genres_fetched_at IS NULL ORDER BY title"
        ).fetchall()
    return [(r["book_id"], r["title"]) for r in rows]


def apply_genres(conn: sqlite3.Connection, book_id: str, genres: Sequence[str]) -> None:
    """Persist one book's genre list, stamping `genres_fetched_at` even on an empty result."""
    conn.execute(
        "UPDATE goodreads_book SET genres = ?, genres_fetched_at = ? WHERE book_id = ?",
        (",".join(genres), _now(), book_id),
    )
    conn.commit()


def enrich(
    conn: sqlite3.Connection,
    user_id: str,
    *,
    cookie: str | None = None,
    genres: bool = True,
    refresh_genres: bool = False,
    throttle_seconds: float = 3.0,
    limit: int | None = None,
    client=None,
) -> EnrichReport:
    """Run the review-table pass, then the genre pass, committing incrementally.

    Raises `GoodreadsAuthError` (propagated from `fetch_review_rows`) if the
    cookie is missing or expired -- the review-table pass either fully
    succeeds or the whole call fails, since a partial page set can't be
    trusted. The genre pass is best-effort per book: throttled at
    `throttle_seconds` between requests, and it stops cleanly (returning
    what was gathered so far) on the first non-200 response rather than
    hammering a failing endpoint.
    """
    rows = fetch_review_rows(user_id, cookie=cookie, client=client)
    rows_updated = apply_review_rows(conn, rows)
    start_dates_found = sum(1 for r in rows if r.date_started is not None)

    genres_fetched = 0
    genres_skipped = 0
    if genres:
        targets = books_needing_genres(conn, refresh=refresh_genres)
        if limit is not None:
            targets = targets[:limit]
        for i, (book_id, _title) in enumerate(targets):
            if i > 0:
                time.sleep(throttle_seconds)
            try:
                fetched = fetch_genres(book_id, cookie=cookie, client=client)
            except GoodreadsError:
                break
            apply_genres(conn, book_id, fetched)
            if fetched:
                genres_fetched += 1
            else:
                genres_skipped += 1

    return EnrichReport(
        rows_updated=rows_updated,
        start_dates_found=start_dates_found,
        genres_fetched=genres_fetched,
        genres_skipped=genres_skipped,
    )
