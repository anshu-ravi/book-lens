"""Saved chat transcripts, grouped by book. Lives in `progress.db`: this is user state.

A conversation records the reading position it was started at, and every turn
records the position it was asked at, so reopening one can say what has changed
without pretending the old answers knew more than they did.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

TITLE_MAX = 90


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class Conversation:
    """One saved conversation and the position it was opened at."""

    id: str
    book_id: str
    title: str
    chapter_idx: int
    created_at: str
    updated_at: str
    turn_count: int


@dataclass(frozen=True)
class Turn:
    """One question and the answer it got, stamped with the position it was asked at."""

    ord: int
    question: str
    answer: str
    citations: list[str]
    chapter_idx: int
    cost_usd: float
    created_at: str


def _title_from(question: str) -> str:
    """A conversation is named after the question that opened it."""
    flat = " ".join(question.split())
    return flat if len(flat) <= TITLE_MAX else flat[: TITLE_MAX - 1].rstrip() + "…"


def _row_to_conversation(row: sqlite3.Row) -> Conversation:
    return Conversation(
        id=row["id"],
        book_id=row["book_id"],
        title=row["title"],
        chapter_idx=row["chapter_idx"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        turn_count=row["turn_count"],
    )


_SELECT = """
SELECT c.id, c.book_id, c.title, c.chapter_idx, c.created_at, c.updated_at,
       (SELECT COUNT(*) FROM conversation_turn t WHERE t.conversation_id = c.id) AS turn_count
  FROM conversation c
"""


def create(pconn: sqlite3.Connection, book_id: str, chapter_idx: int) -> Conversation:
    """Open an empty conversation on a book at the reader's current position."""
    cid = uuid.uuid4().hex
    stamp = _now()
    with pconn:
        pconn.execute(
            "INSERT INTO conversation(id, book_id, title, chapter_idx, created_at, updated_at)"
            " VALUES(?, ?, '', ?, ?, ?)",
            (cid, book_id, chapter_idx, stamp, stamp),
        )
    return Conversation(
        id=cid,
        book_id=book_id,
        title="",
        chapter_idx=chapter_idx,
        created_at=stamp,
        updated_at=stamp,
        turn_count=0,
    )


def get(pconn: sqlite3.Connection, conversation_id: str) -> Conversation | None:
    """One conversation, or None if it doesn't exist."""
    row = pconn.execute(_SELECT + " WHERE c.id = ?", (conversation_id,)).fetchone()
    return _row_to_conversation(row) if row else None


def for_book(pconn: sqlite3.Connection, book_id: str) -> list[Conversation]:
    """A book's conversations, most recently used first."""
    rows = pconn.execute(
        _SELECT + " WHERE c.book_id = ? ORDER BY c.updated_at DESC", (book_id,)
    ).fetchall()
    return [_row_to_conversation(r) for r in rows]


def all_conversations(pconn: sqlite3.Connection) -> list[Conversation]:
    """Every saved conversation, most recently used first."""
    rows = pconn.execute(_SELECT + " ORDER BY c.updated_at DESC").fetchall()
    return [_row_to_conversation(r) for r in rows]


def turns(pconn: sqlite3.Connection, conversation_id: str) -> list[Turn]:
    """A conversation's turns in the order they were asked."""
    rows = pconn.execute(
        "SELECT ord, question, answer, citations, chapter_idx, cost_usd, created_at"
        "  FROM conversation_turn WHERE conversation_id = ? ORDER BY ord",
        (conversation_id,),
    ).fetchall()
    return [
        Turn(
            ord=r["ord"],
            question=r["question"],
            answer=r["answer"],
            citations=json.loads(r["citations"]),
            chapter_idx=r["chapter_idx"],
            cost_usd=r["cost_usd"],
            created_at=r["created_at"],
        )
        for r in rows
    ]


def append_turn(
    pconn: sqlite3.Connection,
    conversation_id: str,
    *,
    question: str,
    answer: str,
    citations: list[str],
    chapter_idx: int,
    cost_usd: float,
) -> Turn:
    """Record one exchange, naming the conversation after it if it is the first."""
    stamp = _now()
    with pconn:
        row = pconn.execute(
            "SELECT COALESCE(MAX(ord), -1) AS last FROM conversation_turn WHERE conversation_id = ?",
            (conversation_id,),
        ).fetchone()
        ord_ = row["last"] + 1
        pconn.execute(
            "INSERT INTO conversation_turn"
            "(conversation_id, ord, question, answer, citations, chapter_idx, cost_usd, created_at)"
            " VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
            (
                conversation_id,
                ord_,
                question,
                answer,
                json.dumps(citations),
                chapter_idx,
                cost_usd,
                stamp,
            ),
        )
        if ord_ == 0:
            pconn.execute(
                "UPDATE conversation SET title = ?, updated_at = ? WHERE id = ?",
                (_title_from(question), stamp, conversation_id),
            )
        else:
            pconn.execute(
                "UPDATE conversation SET updated_at = ? WHERE id = ?", (stamp, conversation_id)
            )
    return Turn(
        ord=ord_,
        question=question,
        answer=answer,
        citations=citations,
        chapter_idx=chapter_idx,
        cost_usd=cost_usd,
        created_at=stamp,
    )


def drop_last_turn(pconn: sqlite3.Connection, conversation_id: str) -> None:
    """Remove the most recent turn -- how a cancelled question is undone."""
    with pconn:
        pconn.execute(
            "DELETE FROM conversation_turn WHERE conversation_id = ? AND ord ="
            " (SELECT MAX(ord) FROM conversation_turn WHERE conversation_id = ?)",
            (conversation_id, conversation_id),
        )


def rename(pconn: sqlite3.Connection, conversation_id: str, title: str) -> None:
    """Give a conversation a title of the reader's own."""
    with pconn:
        pconn.execute(
            "UPDATE conversation SET title = ? WHERE id = ?",
            (_title_from(title), conversation_id),
        )


def delete(pconn: sqlite3.Connection, conversation_id: str) -> None:
    """Remove a conversation and its turns."""
    with pconn:
        pconn.execute("DELETE FROM conversation_turn WHERE conversation_id = ?", (conversation_id,))
        pconn.execute("DELETE FROM conversation WHERE id = ?", (conversation_id,))


def delete_for_book(pconn: sqlite3.Connection, book_id: str) -> int:
    """Remove every conversation on a book; returns how many went."""
    with pconn:
        ids = [r["id"] for r in pconn.execute("SELECT id FROM conversation WHERE book_id = ?", (book_id,))]
        pconn.execute(
            "DELETE FROM conversation_turn WHERE conversation_id IN"
            " (SELECT id FROM conversation WHERE book_id = ?)",
            (book_id,),
        )
        pconn.execute("DELETE FROM conversation WHERE book_id = ?", (book_id,))
    return len(ids)
