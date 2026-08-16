"""Per-book reading position and the spoiler ceiling watermark.

See `docs/implementation-notes.md` for how position and ceiling differ.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

from booklens import db


@dataclass(frozen=True)
class BookProgress:
    """Where the reader is in one book, and how far they have ever been."""

    book_id: str
    status: str
    position_chapter_idx: int | None
    ceiling_seq: int


def _now() -> str:
    """Current UTC time, as stored in the timestamp columns."""
    return datetime.now(timezone.utc).isoformat()


def get_progress(pconn: sqlite3.Connection, book_id: str) -> BookProgress:
    """Return a book's progress, defaulting to unread/ceiling 0 if unset."""
    row = pconn.execute(
        "SELECT book_id, status, position_chapter_idx, ceiling_seq "
        "FROM book_progress WHERE book_id = ?",
        (book_id,),
    ).fetchone()
    if row is None:
        return BookProgress(
            book_id=book_id, status="unread", position_chapter_idx=None, ceiling_seq=0
        )
    return BookProgress(
        book_id=row["book_id"],
        status=row["status"],
        position_chapter_idx=row["position_chapter_idx"],
        ceiling_seq=row["ceiling_seq"],
    )


def _book_exists(iconn: sqlite3.Connection, book_id: str) -> bool:
    """Whether the book has been ingested into the index."""
    return (
        iconn.execute("SELECT 1 FROM book WHERE id = ?", (book_id,)).fetchone()
        is not None
    )


_CHAPTER_END_SEQ_SQL = (
    "SELECT end_seq FROM chapter WHERE book_id = ? AND chapter_idx = ? AND kind IN "
    + db.SERVABLE_KINDS_SQL
)
_BOOK_MAX_END_SEQ_SQL = (
    "SELECT MAX(end_seq) AS m FROM chapter WHERE book_id = ? AND kind IN " + db.SERVABLE_KINDS_SQL
)


def _chapter_end_seq(
    iconn: sqlite3.Connection, book_id: str, chapter_idx: int
) -> int:
    """End of a chapter the reader can actually claim to have finished.

    Excerpt and boilerplate chapters are excluded; neither is a valid
    position -- one belongs to another book, the other isn't the book proper.
    """
    row = iconn.execute(_CHAPTER_END_SEQ_SQL, (book_id, chapter_idx)).fetchone()
    if row is None:
        raise ValueError(f"unknown chapter_idx {chapter_idx} for book {book_id!r}")
    return row["end_seq"]


def _book_max_end_seq(iconn: sqlite3.Connection, book_id: str) -> int:
    """End of the book proper, so 'finished' never sets a ceiling into the
    back matter (an excerpt of the next book, or boilerplate like an
    afterword) that follows the book's own last chapter."""
    row = iconn.execute(_BOOK_MAX_END_SEQ_SQL, (book_id,)).fetchone()
    if row is None or row["m"] is None:
        # Nothing ingested for this book yet.
        return 0
    return row["m"]


def _series_and_order(iconn: sqlite3.Connection, book_id: str) -> tuple[str, int]:
    """A book's series and its order within that series."""
    row = iconn.execute(
        "SELECT series_id, book_order FROM book WHERE id = ?", (book_id,)
    ).fetchone()
    return row["series_id"], row["book_order"]


def _earlier_books_in_series(
    iconn: sqlite3.Connection, book_id: str
) -> list[str]:
    """Every book in the same series with a strictly lower `book_order`."""
    series_id, book_order = _series_and_order(iconn, book_id)
    rows = iconn.execute(
        "SELECT id FROM book WHERE series_id = ? AND book_order < ?",
        (series_id, book_order),
    ).fetchall()
    return [r["id"] for r in rows]


def set_position(
    pconn: sqlite3.Connection,
    iconn: sqlite3.Connection,
    book_id: str,
    *,
    status: str,
    chapter_idx: int | None = None,
) -> BookProgress:
    """Move the reader to a position, dragging the ceiling forward if needed.

    `chapter_idx` is the chapter just completed. The ceiling only ever rises
    here; moving backward leaves it where it was. Setting a book to `reading`
    or `finished` also cascades: no one reads a series out of order, so every
    earlier book in the same series is advanced to `finished` too (watermark
    rule still applies -- their ceilings only rise, never lower). `unread`
    does not cascade.
    """
    if status not in ("unread", "reading", "finished"):
        raise ValueError(f"invalid status {status!r}")
    if not _book_exists(iconn, book_id):
        raise ValueError(f"unknown book_id {book_id!r}")

    if status == "unread":
        candidate = 0
        chapter_idx = None
    elif status == "reading":
        if chapter_idx is None:
            candidate = 0
        else:
            candidate = _chapter_end_seq(iconn, book_id, chapter_idx)
    else:  # finished
        candidate = _book_max_end_seq(iconn, book_id)

    existing = get_progress(pconn, book_id)
    new_ceiling = max(existing.ceiling_seq, candidate)

    pconn.execute(
        """
        INSERT INTO book_progress(book_id, status, position_chapter_idx, ceiling_seq, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(book_id) DO UPDATE SET
            status = excluded.status,
            position_chapter_idx = excluded.position_chapter_idx,
            ceiling_seq = excluded.ceiling_seq,
            updated_at = excluded.updated_at
        """,
        (book_id, status, chapter_idx, new_ceiling, _now()),
    )
    pconn.commit()

    if status in ("reading", "finished"):
        for earlier_id in _earlier_books_in_series(iconn, book_id):
            earlier = get_progress(pconn, earlier_id)
            earlier_candidate = _book_max_end_seq(iconn, earlier_id)
            earlier_ceiling = max(earlier.ceiling_seq, earlier_candidate)
            pconn.execute(
                """
                INSERT INTO book_progress(book_id, status, position_chapter_idx, ceiling_seq, updated_at)
                VALUES (?, 'finished', ?, ?, ?)
                ON CONFLICT(book_id) DO UPDATE SET
                    status = 'finished',
                    position_chapter_idx = excluded.position_chapter_idx,
                    ceiling_seq = excluded.ceiling_seq,
                    updated_at = excluded.updated_at
                """,
                (earlier_id, earlier.position_chapter_idx, earlier_ceiling, _now()),
            )
        pconn.commit()

    return get_progress(pconn, book_id)


def reset_ceiling(
    pconn: sqlite3.Connection, book_id: str, ceiling_seq: int
) -> BookProgress:
    """Force a book's ceiling to a value, the only path that can lower one."""
    if ceiling_seq < 0:
        raise ValueError("ceiling_seq must be non-negative")

    existing = get_progress(pconn, book_id)
    pconn.execute(
        """
        INSERT INTO book_progress(book_id, status, position_chapter_idx, ceiling_seq, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(book_id) DO UPDATE SET
            ceiling_seq = excluded.ceiling_seq,
            updated_at = excluded.updated_at
        """,
        (book_id, existing.status, existing.position_chapter_idx, ceiling_seq, _now()),
    )
    pconn.commit()
    return get_progress(pconn, book_id)


def readable_ranges(
    pconn: sqlite3.Connection, iconn: sqlite3.Connection
) -> list[tuple[int, int]]:
    """Merged per-book readable spans, a true union that can have gaps.

    Each book with progress contributes `[book_order * 1_000_000, ceiling_seq]`
    -- its own floor, not zero. Unread books (`ceiling_seq == 0`) and books
    whose ceiling hasn't reached their own floor contribute nothing.
    """
    rows = pconn.execute(
        "SELECT book_id, ceiling_seq FROM book_progress WHERE ceiling_seq > 0"
    ).fetchall()

    ranges = []
    for r in rows:
        book = iconn.execute(
            "SELECT book_order FROM book WHERE id = ?", (r["book_id"],)
        ).fetchone()
        if book is None:
            continue  # book no longer in the index; nothing to contribute
        book_start = book["book_order"] * 1_000_000
        if r["ceiling_seq"] < book_start:
            continue
        ranges.append((book_start, r["ceiling_seq"]))
    ranges.sort()
    if not ranges:
        return []

    merged: list[list[int]] = [list(ranges[0])]
    for start, end in ranges[1:]:
        last = merged[-1]
        if start <= last[1] + 1:
            last[1] = max(last[1], end)
        else:
            merged.append([start, end])
    return [(s, e) for s, e in merged]


def ceiling_for(pconn: sqlite3.Connection, iconn: sqlite3.Connection) -> int:
    """The single scalar the tool layer filters on: the furthest point reached."""
    row = pconn.execute("SELECT MAX(ceiling_seq) AS m FROM book_progress").fetchone()
    if row is None or row["m"] is None:
        return 0
    return row["m"]
