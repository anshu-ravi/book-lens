"""Per-book reading position and the spoiler ceiling watermark.

See `docs/implementation-notes.md` for how position and ceiling differ, and for
the Phase 0 limits of `readable_ranges`.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone


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


def _chapter_end_seq(
    iconn: sqlite3.Connection, book_id: str, chapter_idx: int
) -> int:
    """End of a chapter the reader can actually claim to have finished.

    Excerpt chapters are excluded; they belong to another book and are never a
    valid position in this one.
    """
    row = iconn.execute(
        "SELECT end_seq FROM chapter WHERE book_id = ? AND chapter_idx = ? AND kind != 'excerpt'",
        (book_id, chapter_idx),
    ).fetchone()
    if row is None:
        raise ValueError(f"unknown chapter_idx {chapter_idx} for book {book_id!r}")
    return row["end_seq"]


def _book_max_end_seq(iconn: sqlite3.Connection, book_id: str) -> int:
    """End of the book proper, so 'finished' never sets a ceiling into the
    next book's opening chapters sitting in this book's back matter."""
    row = iconn.execute(
        "SELECT MAX(end_seq) AS m FROM chapter WHERE book_id = ? AND kind != 'excerpt'",
        (book_id,),
    ).fetchone()
    if row is None or row["m"] is None:
        # Nothing ingested for this book yet.
        return 0
    return row["m"]


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
    here; moving backward leaves it where it was.
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
    """Merged readable spans across all books; unread books contribute nothing.

    Not yet consumed by the tool layer, and not yet a true union — see
    `docs/implementation-notes.md`.
    """
    rows = pconn.execute(
        "SELECT ceiling_seq FROM book_progress WHERE ceiling_seq > 0"
    ).fetchall()
    ranges = sorted((0, r["ceiling_seq"]) for r in rows)
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
