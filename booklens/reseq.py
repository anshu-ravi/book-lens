"""Move a book to a new position in its series without re-reading its EPUB.

A change of `book_order` is a pure constant shift of every seq the book owns.
"""

from __future__ import annotations

import sqlite3

from booklens import db


def _book_order(iconn: sqlite3.Connection, book_id: str) -> int:
    """The book's current position in its series, raising if the book is unknown."""
    row = iconn.execute("SELECT book_order FROM book WHERE id = ?", (book_id,)).fetchone()
    if row is None:
        raise ValueError(f"unknown book_id {book_id!r}")
    return row["book_order"]


def _max_seq(iconn: sqlite3.Connection, book_id: str) -> int | None:
    """The book's highest `para.global_seq`, or None if it has no paragraphs."""
    row = iconn.execute("SELECT MAX(global_seq) AS m FROM para WHERE book_id = ?", (book_id,)).fetchone()
    return row["m"]


def rebase_book_order(
    iconn: sqlite3.Connection,
    pconn: sqlite3.Connection,
    book_id: str,
    new_book_order: int,
    series_id: str | None = None,
) -> int:
    """Shift every seq owned by a book to a new position in its series, returning the delta.

    When `series_id` is given, `book_order` and `series_id` are written in the
    same `UPDATE` -- `book` has `UNIQUE(series_id, book_order)`, and writing
    them separately can transiently collide with a row the final state does
    not collide with. Passing `series_id` also means an unchanged
    `new_book_order` is no longer a no-op: the series still has to move, even
    though the seq delta is 0.
    """
    if new_book_order < 0:
        raise ValueError(f"new_book_order must be non-negative, got {new_book_order}")

    old_book_order = _book_order(iconn, book_id)
    if old_book_order == new_book_order and series_id is None:
        return 0

    delta = (new_book_order - old_book_order) * db.BOOK_STRIDE

    max_seq = _max_seq(iconn, book_id)
    if max_seq is not None:
        shifted = max_seq + delta
        bo = shifted // db.BOOK_STRIDE
        sp = (shifted % db.BOOK_STRIDE) // db.SPINE_STRIDE
        pa = shifted % db.SPINE_STRIDE
        try:
            db.global_seq(bo, sp, pa)
        except ValueError as exc:
            raise ValueError(
                f"moving book {book_id!r} to book_order {new_book_order} pushes its "
                f"highest seq out of range: {exc}"
            ) from exc

    try:
        iconn.execute("UPDATE para SET global_seq = global_seq + ? WHERE book_id = ?", (delta, book_id))
        iconn.execute(
            "UPDATE chapter SET start_seq = start_seq + ?, end_seq = end_seq + ? WHERE book_id = ?",
            (delta, delta, book_id),
        )
        iconn.execute(
            "UPDATE digest SET source_start_seq = source_start_seq + ?, "
            "source_end_seq = source_end_seq + ? WHERE book_id = ?",
            (delta, delta, book_id),
        )
        iconn.execute(
            "UPDATE entity_node SET first_seq = first_seq + ? WHERE book_id = ?", (delta, book_id)
        )
        iconn.execute(
            "UPDATE entity_edge SET revealed_at_seq = revealed_at_seq + ? "
            "WHERE src_node_id IN (SELECT id FROM entity_node WHERE book_id = ?)",
            (delta, book_id),
        )
        iconn.execute(
            "UPDATE entity_attr SET first_seq = first_seq + ? "
            "WHERE node_id IN (SELECT id FROM entity_node WHERE book_id = ?)",
            (delta, book_id),
        )
        if series_id is None:
            iconn.execute("UPDATE book SET book_order = ? WHERE id = ?", (new_book_order, book_id))
        else:
            iconn.execute(
                "UPDATE book SET book_order = ?, series_id = ? WHERE id = ?",
                (new_book_order, series_id, book_id),
            )
        iconn.commit()
    except Exception:
        iconn.rollback()
        raise

    pconn.execute(
        "UPDATE book_progress SET ceiling_seq = ceiling_seq + ? WHERE book_id = ? AND ceiling_seq > 0",
        (delta, book_id),
    )
    pconn.commit()

    return delta
