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

# Recognise the *shape* of a reader-facing chapter label -- never used to
# reorder anything; spine order (chapter_idx) remains the only sequence.
_PART_DIVIDER_RE = re.compile(r"^\s*part\b", re.IGNORECASE)
_NAMED_DIVISION_RE = re.compile(r"^\s*(prologue|epilogue|interlude\w*)\b", re.IGNORECASE)
_PRINTED_NUMBER_RE = re.compile(r"^\s*(?:chapter\s+)?(\d+)\b", re.IGNORECASE)

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


def _printed_identity(label: str) -> tuple[str, str | int] | None:
    """Read a chapter label the way a reader would name it.

    Returns ('number', N) for something like "20: The House Mars" or
    "Chapter 20", ('name', 'prologue') for a named division, or None if the
    label carries no reader-facing identity at all (e.g. a part divider).
    """
    stripped = label.strip()
    m = _NAMED_DIVISION_RE.match(stripped)
    if m:
        return ("name", stripped.lower())
    m = _PRINTED_NUMBER_RE.match(stripped)
    if m:
        return ("number", int(m.group(1)))
    return None


def count_addressable_chapters(iconn: sqlite3.Connection, book_id: str) -> int:
    """Total structural chapters for a book, excluding part dividers.

    Not spoiler-bearing: it is a count of structure, not titles, so it is
    safe to show above the ceiling (DECISIONS.md section 4). `book_id` is
    never user-supplied SQL text; `db.ADDRESSABLE_KINDS_SQL` is a code
    constant rendered the same way every other query in this module does.
    """
    query = "SELECT label FROM chapter WHERE book_id = ? AND kind IN " + db.ADDRESSABLE_KINDS_SQL
    rows = iconn.execute(query, (book_id,)).fetchall()
    return sum(1 for r in rows if not _PART_DIVIDER_RE.match(r["label"].strip()))


def chapter_ref_for(iconn: sqlite3.Connection, book_id: str, chapter_idx: int) -> str | None:
    """The reader-facing reference for an internal `chapter_idx`, the inverse of `resolve_chapter_ref`.

    None when the chapter carries no reader-facing identity (a part divider,
    or an unlabelled division). The internal index is not the printed number,
    so a UI must round-trip through this rather than assume they match.
    """
    row = iconn.execute(
        f"SELECT label FROM chapter WHERE book_id = ? AND chapter_idx = ? AND kind IN {db.ADDRESSABLE_KINDS_SQL}",
        (book_id, chapter_idx),
    ).fetchone()
    if row is None:
        return None
    identity = _printed_identity(row["label"])
    return None if identity is None else str(identity[1])


def resolve_chapter_ref(iconn: sqlite3.Connection, book_id: str, ref: str | int) -> int:
    """Map a reader-facing chapter reference to the internal `chapter_idx`.

    Accepts a printed number ("20") or a named division ("prologue",
    "epilogue", an interlude's label). Part dividers are structure, not
    reading positions, and are never resolvable here. Only recognises the
    *shape* of a label to identify what the reader would type -- spine order
    (chapter_idx) remains the only sequence, per `DECISIONS.md` section 3.
    Raises `ValueError` naming what is valid; never clamps to something close.
    """
    rows = iconn.execute(
        f"SELECT chapter_idx, label FROM chapter WHERE book_id = ? AND kind IN {db.ADDRESSABLE_KINDS_SQL} "
        "ORDER BY chapter_idx",
        (book_id,),
    ).fetchall()
    if not rows:
        raise ValueError(f"unknown book_id {book_id!r}")

    numbers: dict[int, int] = {}
    names: dict[str, int] = {}
    for r in rows:
        label = r["label"]
        if _PART_DIVIDER_RE.match(label.strip()):
            continue
        identity = _printed_identity(label)
        if identity is None:
            continue
        kind, value = identity
        if kind == "number":
            numbers.setdefault(value, r["chapter_idx"])
        else:
            names.setdefault(value, r["chapter_idx"])

    if isinstance(ref, int):
        query_number, query_name = ref, None
    else:
        text = str(ref).strip()
        query_number, query_name = (int(text), None) if text.isdigit() else (None, text.lower())

    if query_number is not None and query_number in numbers:
        return numbers[query_number]
    if query_name is not None and query_name in names:
        return names[query_name]

    valid_numbers = sorted(numbers)
    number_range = f"{valid_numbers[0]}-{valid_numbers[-1]}" if valid_numbers else "none"
    valid_names = ", ".join(sorted(names)) if names else "none"
    raise ValueError(
        f"unknown chapter reference {ref!r} for book {book_id!r}; "
        f"valid printed chapters: {number_range}; valid named divisions: {valid_names}"
    )


def _last_readable_chapter_label(
    iconn: sqlite3.Connection, book_id: str, ceiling: int
) -> str | None:
    """Label of the furthest chapter the reader has started, for the truncation marker."""
    row = iconn.execute(
        f"""
        SELECT label FROM chapter
        WHERE book_id = ? AND start_seq <= ? AND kind IN {db.SERVABLE_KINDS_SQL}
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
        f"SELECT 1 FROM chapter WHERE book_id = ? AND end_seq > ? AND kind IN {db.SERVABLE_KINDS_SQL} LIMIT 1",
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
        """Bind to the reader's current readable ranges for the life of this object.

        Checks `iconn` against the current schema unconditionally -- `iconn`
        may have been opened with plain `sqlite3.connect` rather than
        `db.connect_index`, and a stale schema must fail loudly here rather
        than silently serving fewer rows than it should (DECISIONS.md
        section 3: fail loudly, never silently).
        """
        db.check_schema_compat(iconn)
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

    def _install_readable_range(self, ranges: list[tuple[str, int, int]]) -> None:
        """Create this instance's own temp table for every query's WHERE clause to join against."""
        self._iconn.execute(
            f"CREATE TEMP TABLE {self._table}"
            "(book_id TEXT NOT NULL, lo INTEGER NOT NULL, hi INTEGER NOT NULL)"
        )
        self._iconn.executemany(
            f"INSERT INTO {self._table}(book_id, lo, hi) VALUES (?, ?, ?)", ranges
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
                    SELECT label FROM chapter AS c
                    WHERE c.book_id = ? AND c.chapter_idx = ? AND c.kind IN {db.SERVABLE_KINDS_SQL}
                      AND EXISTS (
                        SELECT 1 FROM {self._table} r
                        WHERE r.book_id = c.book_id AND c.start_seq BETWEEN r.lo AND r.hi
                      )
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
            SELECT chapter_idx, label, part_label FROM chapter AS c
            WHERE c.book_id = ? AND c.kind IN {db.SERVABLE_KINDS_SQL}{part_clause}
              AND EXISTS (
                SELECT 1 FROM {self._table} r
                WHERE r.book_id = c.book_id AND c.start_seq BETWEEN r.lo AND r.hi
              )
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

    def list_chapter_positions(self, book: str) -> dict:
        """The reading-position picker: reader-facing numbers for the whole book.

        Structure -- printed numbers and part boundaries -- is visible for
        every chapter so the reader can orient, but a chapter's title is
        withheld until its start_seq is inside the readable range. Section 4:
        the picker must not reveal titles above the ceiling. Never the
        internal chapter_idx.
        """
        rows = self._iconn.execute(
            "SELECT label, part_label, start_seq FROM chapter "
            f"WHERE book_id = ? AND kind IN {db.ADDRESSABLE_KINDS_SQL} ORDER BY chapter_idx",
            (book,),
        ).fetchall()
        ceiling = self._book_ceiling(book)

        positions: list[dict] = []
        seen_parts: set[str] = set()
        for r in rows:
            label = r["label"]
            if _PART_DIVIDER_RE.match(label.strip()):
                if label not in seen_parts:
                    positions.append({"part": label})
                    seen_parts.add(label)
                continue
            identity = _printed_identity(label)
            entry: dict = {}
            if identity is not None:
                key = "number" if identity[0] == "number" else "name"
                entry[key] = identity[1]
            if r["start_seq"] <= ceiling:
                entry["label"] = label
            positions.append(entry)

        return {"book": book, "positions": positions}

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
            FROM para AS p
            WHERE p.book_id = ? AND p.chapter_idx BETWEEN ? AND ?
              AND p.kind IN {db.SERVABLE_KINDS_SQL}
              AND EXISTS (
                SELECT 1 FROM {self._table} r
                WHERE r.book_id = p.book_id AND p.global_seq BETWEEN r.lo AND r.hi
              )
            ORDER BY p.global_seq
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
            SELECT 1 FROM para AS p
            WHERE p.book_id = ? AND p.chapter_idx BETWEEN ? AND ?
              AND p.kind IN {db.SERVABLE_KINDS_SQL}
              AND NOT EXISTS (
                SELECT 1 FROM {self._table} r
                WHERE r.book_id = p.book_id AND p.global_seq BETWEEN r.lo AND r.hi
              )
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
                SELECT 1 FROM chapter AS c
                WHERE c.book_id = ? AND c.chapter_idx = ? AND c.kind IN {db.SERVABLE_KINDS_SQL}
                  AND EXISTS (
                    SELECT 1 FROM {self._table} r
                    WHERE r.book_id = c.book_id AND c.start_seq BETWEEN r.lo AND r.hi
                  )
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
                    FROM para AS p
                    WHERE text REGEXP ? AND kind IN {db.SERVABLE_KINDS_SQL}{book_clause}
                      AND EXISTS (
                        SELECT 1 FROM {self._table} r
                        WHERE r.book_id = p.book_id AND p.global_seq BETWEEN r.lo AND r.hi
                      )
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
                WHERE para_fts MATCH ? AND p.kind IN {db.SERVABLE_KINDS_SQL}{book_clause}
                  AND EXISTS (
                    SELECT 1 FROM {self._table} r
                    WHERE r.book_id = p.book_id AND p.global_seq BETWEEN r.lo AND r.hi
                  )
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
                WHERE para_fts MATCH ? AND p.kind IN {db.SERVABLE_KINDS_SQL}
                  AND EXISTS (
                    SELECT 1 FROM {self._table} r
                    WHERE r.book_id = p.book_id AND p.global_seq BETWEEN r.lo AND r.hi
                  )
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
            FROM para AS p
            WHERE p.book_id = ? AND p.spine_idx = ? AND p.para_idx = ? AND p.kind IN {db.SERVABLE_KINDS_SQL}
              AND EXISTS (
                SELECT 1 FROM {self._table} r
                WHERE r.book_id = p.book_id AND p.global_seq BETWEEN r.lo AND r.hi
              )
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
            FROM para AS p
            WHERE p.book_id = ? AND p.global_seq < ? AND p.kind IN {db.SERVABLE_KINDS_SQL}
              AND EXISTS (
                SELECT 1 FROM {self._table} r
                WHERE r.book_id = p.book_id AND p.global_seq BETWEEN r.lo AND r.hi
              )
            ORDER BY global_seq DESC
            LIMIT ?
            """,
            (book_id, center["global_seq"], window),
        ).fetchall()

        after_rows = self._iconn.execute(
            f"""
            SELECT book_id, spine_idx, para_idx, chapter_label, text
            FROM para AS p
            WHERE p.book_id = ? AND p.global_seq > ? AND p.kind IN {db.SERVABLE_KINDS_SQL}
              AND EXISTS (
                SELECT 1 FROM {self._table} r
                WHERE r.book_id = p.book_id AND p.global_seq BETWEEN r.lo AND r.hi
              )
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
