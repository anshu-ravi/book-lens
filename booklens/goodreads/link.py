"""Links a Goodreads shelf entry to an ingested EPUB, keyed on normalised title.

The link lives in `goodreads.db` (see the table in `store._DDL`) so
`index.db` can be rebuilt from EPUBs without losing it, and `progress.db`
(precious user state) is never touched by this module.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


_PAREN_RE = re.compile(r"\([^)]*\)")
_COLON_TAIL_RE = re.compile(r":.*$")
_COLON_HEAD_RE = re.compile(r"^[^:]+:\s*")
_STOPWORD_RE = re.compile(r"^(the|a|an)\s+")
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")
# A dash surrounded by whitespace: hyphen-minus, en dash, em dash. Requires
# whitespace on both sides so "Spider-Man" and an unspaced em dash don't split.
_SPACED_DASH_RE = re.compile(r"\s[-–—]\s")


def _normalise(v: str) -> str:
    """Strip a leading stopword and squeeze to alphanumeric-only, lowercase."""
    v = _STOPWORD_RE.sub("", v.strip())
    return _NON_ALNUM_RE.sub("", v)


def match_keys(title: str) -> set[str]:
    """Several normalised forms of a title; a match on any one is a match."""
    s = _PAREN_RE.sub("", (title or "").lower()).strip()
    variants = [s, _COLON_TAIL_RE.sub("", s), _COLON_HEAD_RE.sub("", s)]

    dash_spans = list(_SPACED_DASH_RE.finditer(s))
    if dash_spans:
        variants.append(s[: dash_spans[0].start()])
        variants.append(s[dash_spans[-1].end() :])

    out = set()
    for v in variants:
        v = _normalise(v)
        if v:
            out.add(v)
    return out


@dataclass(frozen=True)
class Link:
    """A proposed or applied book_id -> goodreads_book_id link."""

    book_id: str
    goodreads_book_id: str


@dataclass(frozen=True)
class Unmatched:
    """A library book that `propose_links` could not resolve to exactly one Goodreads entry."""

    book_id: str
    title: str
    reason: str  # "no_match" | "ambiguous"
    candidates: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class LinkReport:
    """Outcome of an `autolink` pass."""

    linked: int
    already_linked: int
    ambiguous: int
    unmatched: int
    ambiguous_books: tuple[Unmatched, ...] = field(default_factory=tuple)
    unmatched_books: tuple[Unmatched, ...] = field(default_factory=tuple)


def _linked_book_ids(gconn: sqlite3.Connection) -> set[str]:
    """The `book_id`s (index.db side) that already have a link, any source."""
    return {r["book_id"] for r in gconn.execute("SELECT book_id FROM goodreads_link")}


def _goodreads_key_index(gconn: sqlite3.Connection) -> dict[str, set[str]]:
    """Every cached Goodreads book's normalised key set, inverted to key -> book_ids."""
    index: dict[str, set[str]] = {}
    rows = gconn.execute("SELECT DISTINCT book_id, title FROM goodreads_book").fetchall()
    for row in rows:
        for key in match_keys(row["title"]):
            index.setdefault(key, set()).add(row["book_id"])
    return index


def propose_links(
    iconn: sqlite3.Connection, gconn: sqlite3.Connection
) -> tuple[list[Link], list[Unmatched]]:
    """Match every not-yet-linked library book against the cached Goodreads shelf.

    Pure: reads both databases, writes nothing. A library book whose title
    keys intersect exactly one Goodreads entry's keys is a `Link`; zero or
    more than one is an `Unmatched`, never a guess.
    """
    already_linked = _linked_book_ids(gconn)
    gr_index = _goodreads_key_index(gconn)
    library_books = iconn.execute("SELECT id, title FROM book").fetchall()

    links: list[Link] = []
    unmatched: list[Unmatched] = []
    for row in library_books:
        book_id = row["id"]
        if book_id in already_linked:
            continue
        candidates: set[str] = set()
        for key in match_keys(row["title"]):
            candidates |= gr_index.get(key, set())
        if len(candidates) == 1:
            links.append(Link(book_id=book_id, goodreads_book_id=next(iter(candidates))))
        elif len(candidates) == 0:
            unmatched.append(Unmatched(book_id=book_id, title=row["title"], reason="no_match"))
        else:
            unmatched.append(
                Unmatched(
                    book_id=book_id,
                    title=row["title"],
                    reason="ambiguous",
                    candidates=tuple(sorted(candidates)),
                )
            )
    return links, unmatched


def apply_links(gconn: sqlite3.Connection, links: list[Link], *, source: str = "auto") -> int:
    """Upsert links, never overwriting a row whose existing `source` is `'manual'`.

    Returns the number of rows actually written (an existing manual link
    that a link in `links` would have overwritten is skipped, not counted).
    """
    now = _now()
    written = 0
    for link in links:
        cur = gconn.execute(
            """
            INSERT INTO goodreads_link(book_id, goodreads_book_id, linked_at, source)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(book_id) DO UPDATE SET
                goodreads_book_id = excluded.goodreads_book_id,
                linked_at = excluded.linked_at,
                source = excluded.source
            WHERE goodreads_link.source != 'manual'
            """,
            (link.book_id, link.goodreads_book_id, now, source),
        )
        written += cur.rowcount
    gconn.commit()
    return written


def set_link(
    gconn: sqlite3.Connection, book_id: str, goodreads_book_id: str, *, source: str = "manual"
) -> None:
    """Write a link unconditionally, overwriting whatever was there.

    The explicit-action counterpart to `apply_links`: a person choosing a
    link (or changing one they chose earlier) always wins, unlike the
    autolink pass, which must never clobber a manual choice.
    """
    now = _now()
    gconn.execute(
        """
        INSERT INTO goodreads_link(book_id, goodreads_book_id, linked_at, source)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(book_id) DO UPDATE SET
            goodreads_book_id = excluded.goodreads_book_id,
            linked_at = excluded.linked_at,
            source = excluded.source
        """,
        (book_id, goodreads_book_id, now, source),
    )
    gconn.commit()


def link_for_book(gconn: sqlite3.Connection, book_id: str) -> str | None:
    """The `goodreads_book_id` linked to `book_id`, or `None` if unlinked."""
    row = gconn.execute(
        "SELECT goodreads_book_id FROM goodreads_link WHERE book_id = ?", (book_id,)
    ).fetchone()
    return row["goodreads_book_id"] if row is not None else None


def linked_book_ids(gconn: sqlite3.Connection) -> dict[str, str]:
    """Every link, as `goodreads_book_id -> book_id`."""
    rows = gconn.execute("SELECT book_id, goodreads_book_id FROM goodreads_link").fetchall()
    return {r["goodreads_book_id"]: r["book_id"] for r in rows}


def remove_link(gconn: sqlite3.Connection, book_id: str) -> None:
    """Delete a book's link, manual or auto."""
    gconn.execute("DELETE FROM goodreads_link WHERE book_id = ?", (book_id,))
    gconn.commit()


def autolink(iconn: sqlite3.Connection, gconn: sqlite3.Connection) -> LinkReport:
    """Propose and apply new auto links, reporting what was linked, skipped, and left ambiguous."""
    already_linked = _linked_book_ids(gconn)
    library_book_ids = {r["id"] for r in iconn.execute("SELECT id FROM book")}
    already_linked_count = len(already_linked & library_book_ids)

    links, unmatched = propose_links(iconn, gconn)
    linked_count = apply_links(gconn, links, source="auto")

    ambiguous_books = tuple(u for u in unmatched if u.reason == "ambiguous")
    unmatched_books = tuple(u for u in unmatched if u.reason == "no_match")

    return LinkReport(
        linked=linked_count,
        already_linked=already_linked_count,
        ambiguous=len(ambiguous_books),
        unmatched=len(unmatched_books),
        ambiguous_books=ambiguous_books,
        unmatched_books=unmatched_books,
    )
