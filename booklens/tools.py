"""The bounded tool layer: the only way an answering model touches book text.

Every query filters on the readable ranges in SQL. See `docs/implementation-notes.md`.
"""

from __future__ import annotations

import re
import sqlite3
import uuid

from booklens import db, progress

_TABLE_NAME_RE = re.compile(r"^readable_range_[0-9a-f]{32}$")

_CITATION_RE = re.compile(r"^(?P<book>[^:]+):(?P<spine>\d+):p(?P<para>\d+)$")

_SEARCH_LIMIT = 40
_READ_RAW_PARA_CAP = 800
_CONTEXT_WINDOW_CAP = 50
_CONTEXT_WINDOW_MIN = 0
_CHAPTER_RANGE_CAP = 2000  # bounds absurd from_ch/to_ch spans


def format_citation_id(book_id: str, spine_idx: int, para_idx: int) -> str:
    """Build the citation string that identifies one paragraph to the model."""
    if ":" in book_id:
        raise ValueError(f"book_id must not contain ':': {book_id!r}")
    if spine_idx < 0 or para_idx < 0:
        raise ValueError("spine_idx and para_idx must be non-negative")
    return f"{book_id}:{spine_idx}:p{para_idx}"


def parse_citation_id(citation_id: str) -> tuple[str, int, int]:
    """Split a citation back into its parts, rejecting anything malformed.

    Never guesses: a citation that does not parse exactly is an error, since
    silently resolving a near miss would corrupt the quote it points at.
    """
    if not isinstance(citation_id, str):
        raise ValueError("citation_id must be a string")
    m = _CITATION_RE.match(citation_id)
    if not m:
        raise ValueError(f"malformed citation id: {citation_id!r}")
    return m.group("book"), int(m.group("spine")), int(m.group("para"))


def _last_readable_chapter_label(
    iconn: sqlite3.Connection, book_id: str, ceiling: int
) -> str | None:
    """Label of the furthest chapter the reader has started, for the truncation marker."""
    row = iconn.execute(
        """
        SELECT label FROM chapter
        WHERE book_id = ? AND start_seq <= ? AND kind != 'excerpt'
        ORDER BY start_seq DESC LIMIT 1
        """,
        (book_id, ceiling),
    ).fetchone()
    return row["label"] if row is not None else None


def _truncation_marker(
    iconn: sqlite3.Connection, book_id: str, ceiling: int
) -> dict | None:
    """Tell the model a boundary exists, naming only a chapter it has reached."""
    label = _last_readable_chapter_label(iconn, book_id, ceiling)
    if label is None:
        return None
    return {"truncated_at": label, "reason": "reading position"}


def _book_has_content_above(
    iconn: sqlite3.Connection, book_id: str, ceiling: int
) -> bool:
    """Whether anything remains unread, without revealing what or how much."""
    row = iconn.execute(
        "SELECT 1 FROM chapter WHERE book_id = ? AND end_seq > ? AND kind != 'excerpt' LIMIT 1",
        (book_id, ceiling),
    ).fetchone()
    return row is not None


def _row_to_para_dict(row: sqlite3.Row) -> dict:
    """Shape a paragraph row into the cited form the model sees."""
    return {
        "citation_id": format_citation_id(row["book_id"], row["spine_idx"], row["para_idx"]),
        "chapter": row["chapter_label"],
        "text": row["text"],
    }


class Tools:
    """Bounded retrieval, fixed to the readable ranges captured when it was constructed.

    No method takes the ceiling or a range as an argument, so nothing a model
    asks for can raise it.
    """

    def __init__(self, iconn: sqlite3.Connection, pconn: sqlite3.Connection):
        """Bind to the reader's current readable ranges for the life of this object."""
        self._iconn = iconn
        self._pconn = pconn
        self._ceiling = progress.ceiling_for(pconn, iconn)
        self._closed = False
        # Unique per instance so two `Tools` sharing one connection each get
        # their own temp table -- bounds live on the object, not the connection.
        self._table = f"readable_range_{uuid.uuid4().hex}"
        assert _TABLE_NAME_RE.match(self._table), f"unsafe table name: {self._table!r}"
        db.register_regexp(iconn)
        self._install_readable_range(progress.readable_ranges(pconn, iconn))

    def _install_readable_range(self, ranges: list[tuple[int, int]]) -> None:
        """Create this instance's own temp table for every query's WHERE clause to join against."""
        self._iconn.execute(f"CREATE TEMP TABLE {self._table}(lo INTEGER NOT NULL, hi INTEGER NOT NULL)")
        self._iconn.executemany(
            f"INSERT INTO {self._table}(lo, hi) VALUES (?, ?)", ranges
        )
        self._iconn.commit()

    def close(self) -> None:
        """Drop this instance's temp table. Safe to call multiple times or never."""
        if self._closed:
            return
        self._iconn.execute(f"DROP TABLE IF EXISTS temp.{self._table}")
        self._iconn.commit()
        self._closed = True

    def __enter__(self) -> "Tools":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    def _book_ceiling(self, book_id: str) -> int:
        """This one book's own watermark, for naming a chapter it has actually reached."""
        return progress.get_progress(self._pconn, book_id).ceiling_seq

    # -- books / chapters --------------------------------------------------

    def list_books(self) -> list[dict]:
        """Every book in the library with the reader's standing in it."""
        rows = self._iconn.execute(
            "SELECT id, title, author, book_order, series_id FROM book "
            "ORDER BY series_id, book_order"
        ).fetchall()
        out = []
        for r in rows:
            prog = progress.get_progress(self._pconn, r["id"])
            entry = {
                "id": r["id"],
                "title": r["title"],
                "author": r["author"],
                "book_order": r["book_order"],
                "status": prog.status,
            }
            if prog.position_chapter_idx is not None:
                ch = self._iconn.execute(
                    f"""
                    SELECT label FROM chapter
                    WHERE book_id = ? AND chapter_idx = ? AND kind != 'excerpt'
                      AND EXISTS (SELECT 1 FROM {self._table} r WHERE start_seq BETWEEN r.lo AND r.hi)
                    """,
                    (r["id"], prog.position_chapter_idx),
                ).fetchone()
                if ch is not None:
                    entry["current_chapter"] = ch["label"]
            out.append(entry)
        return out

    def list_chapters(self, book: str, part: str | None = None) -> dict:
        """Chapters the reader has begun. Later ones are absent, not hidden."""
        if not isinstance(book, str) or not book:
            return {"book": book, "chapters": []}

        params: list = [book]
        part_clause = ""
        if part is not None:
            part_clause = " AND part_label = ?"
            params.append(part)

        rows = self._iconn.execute(
            f"""
            SELECT chapter_idx, label, part_label FROM chapter
            WHERE book_id = ? AND kind != 'excerpt'{part_clause}
              AND EXISTS (SELECT 1 FROM {self._table} r WHERE start_seq BETWEEN r.lo AND r.hi)
            ORDER BY chapter_idx
            """,
            params,
        ).fetchall()

        result: dict = {
            "book": book,
            "chapters": [
                {"chapter_idx": r["chapter_idx"], "label": r["label"], "part_label": r["part_label"]}
                for r in rows
            ],
        }
        book_ceiling = self._book_ceiling(book)
        marker = _truncation_marker(self._iconn, book, book_ceiling)
        if marker is not None and _book_has_content_above(self._iconn, book, book_ceiling):
            result.update(marker)
        return result

    # -- raw text -------------------------------------------------------

    def read_raw(self, book: str, from_ch: int, to_ch: int) -> dict:
        """Full text of a chapter range, cut off at the reader's position."""
        try:
            from_ch = int(from_ch)
            to_ch = int(to_ch)
        except (TypeError, ValueError):
            return {"book": book, "paragraphs": [], "error": "invalid chapter range"}

        lo, hi = sorted((from_ch, to_ch))
        lo = max(lo, 0)
        hi = min(hi, lo + _CHAPTER_RANGE_CAP)

        rows = self._iconn.execute(
            f"""
            SELECT book_id, spine_idx, para_idx, chapter_label, text
            FROM para
            WHERE book_id = ? AND chapter_idx BETWEEN ? AND ?
              AND kind != 'excerpt'
              AND EXISTS (SELECT 1 FROM {self._table} r WHERE global_seq BETWEEN r.lo AND r.hi)
            ORDER BY global_seq
            LIMIT ?
            """,
            (book, lo, hi, _READ_RAW_PARA_CAP + 1),
        ).fetchall()

        capped = len(rows) > _READ_RAW_PARA_CAP
        if capped:
            rows = rows[:_READ_RAW_PARA_CAP]

        result: dict = {
            "book": book,
            "paragraphs": [_row_to_para_dict(r) for r in rows],
        }
        if capped:
            result["capped"] = True

        was_clamped = self._iconn.execute(
            f"""
            SELECT 1 FROM para
            WHERE book_id = ? AND chapter_idx BETWEEN ? AND ?
              AND kind != 'excerpt'
              AND NOT EXISTS (SELECT 1 FROM {self._table} r WHERE global_seq BETWEEN r.lo AND r.hi)
            LIMIT 1
            """,
            (book, lo, hi),
        ).fetchone()
        if was_clamped is not None:
            marker = _truncation_marker(self._iconn, book, self._book_ceiling(book))
            if marker is not None:
                result.update(marker)

        return result

    # -- digests (Phase 0 stub) ------------------------------------------

    def read_digest(self, book: str, chapter: int | None = None, part: str | None = None) -> dict:
        """Stub until Phase 1 builds digests; still refuses out-of-range asks."""
        result: dict = {"digests": [], "note": "digests are not generated until Phase 1"}

        if chapter is not None:
            try:
                chapter = int(chapter)
            except (TypeError, ValueError):
                return result
            row = self._iconn.execute(
                f"""
                SELECT 1 FROM chapter
                WHERE book_id = ? AND chapter_idx = ? AND kind != 'excerpt'
                  AND EXISTS (SELECT 1 FROM {self._table} r WHERE start_seq BETWEEN r.lo AND r.hi)
                """,
                (book, chapter),
            ).fetchone()
            if row is None:
                marker = _truncation_marker(self._iconn, book, self._book_ceiling(book))
                if marker is not None:
                    result.update(marker)

        return result

    # -- search -----------------------------------------------------------

    def search(self, query: str, book: str | None = None, regex: bool = False) -> dict:
        """Find passages the reader has already read, ranked by relevance.

        Malformed queries come back as an error result rather than raising.
        """
        if not isinstance(query, str) or not query.strip():
            return {"results": [], "error": "empty query"}

        if regex:
            try:
                re.compile(query)
            except re.error:
                return {"results": [], "error": "invalid regex"}

            params: list = [query]
            book_clause = ""
            if book is not None:
                book_clause = " AND book_id = ?"
                params.append(book)

            try:
                rows = self._iconn.execute(
                    f"""
                    SELECT book_id, spine_idx, para_idx, chapter_label, text
                    FROM para
                    WHERE text REGEXP ? AND kind != 'excerpt'{book_clause}
                      AND EXISTS (SELECT 1 FROM {self._table} r WHERE global_seq BETWEEN r.lo AND r.hi)
                    ORDER BY global_seq
                    LIMIT ?
                    """,
                    (*params, _SEARCH_LIMIT),
                ).fetchall()
            except sqlite3.OperationalError:
                return {"results": [], "error": "invalid search query"}

            results = []
            for r in rows:
                m = re.search(query, r["text"])
                snippet = r["text"][:200] if m is None else _snippet_around(r["text"], m.start(), m.end())
                results.append(
                    {
                        "citation_id": format_citation_id(r["book_id"], r["spine_idx"], r["para_idx"]),
                        "chapter": r["chapter_label"],
                        "snippet": snippet,
                    }
                )
            return {"results": results}

        # FTS5 path
        params = [query]
        book_clause = ""
        if book is not None:
            book_clause = " AND p.book_id = ?"
            params.append(book)

        try:
            rows = self._iconn.execute(
                f"""
                SELECT p.book_id, p.spine_idx, p.para_idx, p.chapter_label,
                       snippet(para_fts, 0, '[', ']', '...', 10) AS snip
                FROM para_fts
                JOIN para p ON p.id = para_fts.rowid
                WHERE para_fts MATCH ? AND p.kind != 'excerpt'{book_clause}
                  AND EXISTS (SELECT 1 FROM {self._table} r WHERE p.global_seq BETWEEN r.lo AND r.hi)
                ORDER BY bm25(para_fts)
                LIMIT ?
                """,
                (*params, _SEARCH_LIMIT),
            ).fetchall()
        except sqlite3.OperationalError:
            return {"results": [], "error": "invalid search query"}

        results = [
            {
                "citation_id": format_citation_id(r["book_id"], r["spine_idx"], r["para_idx"]),
                "chapter": r["chapter_label"],
                "snippet": r["snip"],
            }
            for r in rows
        ]
        return {"results": results}

    # -- entities (Phase 0: text-search-backed) ----------------------------

    def first_seen(self, entity: str) -> dict:
        """Earliest mention the reader has met, else NOT_YET_SEEN.

        That answer is identical for something not yet reached and something
        that never appears, so absence reveals nothing.
        """
        if not isinstance(entity, str) or not entity.strip():
            return {"result": "NOT_YET_SEEN"}

        escaped = entity.replace('"', '""')
        try:
            row = self._iconn.execute(
                f"""
                SELECT p.book_id, p.spine_idx, p.para_idx, p.chapter_label
                FROM para_fts
                JOIN para p ON p.id = para_fts.rowid
                WHERE para_fts MATCH ? AND p.kind != 'excerpt'
                  AND EXISTS (SELECT 1 FROM {self._table} r WHERE p.global_seq BETWEEN r.lo AND r.hi)
                ORDER BY p.global_seq ASC
                LIMIT 1
                """,
                (f'"{escaped}"',),
            ).fetchone()
        except sqlite3.OperationalError:
            return {"result": "NOT_YET_SEEN"}

        if row is None:
            return {"result": "NOT_YET_SEEN"}

        return {
            "result": "FOUND",
            "citation_id": format_citation_id(row["book_id"], row["spine_idx"], row["para_idx"]),
            "chapter": row["chapter_label"],
        }

    def cast(self, book: str | None = None) -> dict:
        """Stub until Phase 1 builds the identity graph."""
        return {"cast": [], "note": "entity graph is not built until Phase 1"}

    # -- context expansion --------------------------------------------------

    def context(self, citation_id: str, window: int = 3) -> dict:
        """Surrounding paragraphs for a hit, never reaching past the ceiling.

        Expansion is bounded by sequence, not by chapter, so it may cross a
        chapter boundary backward.
        """
        book_id, spine_idx, para_idx = parse_citation_id(citation_id)

        try:
            window = int(window)
        except (TypeError, ValueError):
            window = 0
        window = max(_CONTEXT_WINDOW_MIN, min(window, _CONTEXT_WINDOW_CAP))

        center = self._iconn.execute(
            f"""
            SELECT book_id, spine_idx, para_idx, chapter_label, text, global_seq
            FROM para
            WHERE book_id = ? AND spine_idx = ? AND para_idx = ? AND kind != 'excerpt'
              AND EXISTS (SELECT 1 FROM {self._table} r WHERE global_seq BETWEEN r.lo AND r.hi)
            """,
            (book_id, spine_idx, para_idx),
        ).fetchone()
        if center is None:
            raise ValueError(f"unknown or unreadable citation id: {citation_id!r}")

        # book_id-scoped, so a gap from an earlier skipped book can never be
        # crossed -- expansion cannot leave the book the hit belongs to.
        before_rows = self._iconn.execute(
            f"""
            SELECT book_id, spine_idx, para_idx, chapter_label, text
            FROM para
            WHERE book_id = ? AND global_seq < ? AND kind != 'excerpt'
              AND EXISTS (SELECT 1 FROM {self._table} r WHERE global_seq BETWEEN r.lo AND r.hi)
            ORDER BY global_seq DESC
            LIMIT ?
            """,
            (book_id, center["global_seq"], window),
        ).fetchall()

        after_rows = self._iconn.execute(
            f"""
            SELECT book_id, spine_idx, para_idx, chapter_label, text
            FROM para
            WHERE book_id = ? AND global_seq > ? AND kind != 'excerpt'
              AND EXISTS (SELECT 1 FROM {self._table} r WHERE global_seq BETWEEN r.lo AND r.hi)
            ORDER BY global_seq ASC
            LIMIT ?
            """,
            (book_id, center["global_seq"], window),
        ).fetchall()

        paragraphs = [_row_to_para_dict(r) for r in reversed(before_rows)]
        paragraphs.append(_row_to_para_dict(center))
        paragraphs.extend(_row_to_para_dict(r) for r in after_rows)

        result: dict = {"citation_id": citation_id, "paragraphs": paragraphs}
        if len(after_rows) < window:
            book_ceiling = self._book_ceiling(book_id)
            marker = _truncation_marker(self._iconn, book_id, book_ceiling)
            if marker is not None and _book_has_content_above(self._iconn, book_id, book_ceiling):
                result.update(marker)
        return result


def _snippet_around(text: str, start: int, end: int, pad: int = 60) -> str:
    """Trim a paragraph to the neighbourhood of a regex match."""
    lo = max(0, start - pad)
    hi = min(len(text), end + pad)
    prefix = "..." if lo > 0 else ""
    suffix = "..." if hi < len(text) else ""
    return f"{prefix}{text[lo:hi]}{suffix}"
