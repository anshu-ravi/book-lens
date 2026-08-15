"""The bounded generation window: the causality guard the digest pass runs inside.

`CausalWindow` is to generation-time causality what `Tools` is to retrieval-time
cutoff -- the bound is fixed at construction and no method can widen it.
"""

from __future__ import annotations

import sqlite3


class CausalWindow:
    """Reads only at or below a seq fixed when it was built.

    `max_seq` is captured once in `__init__` and never appears as a method
    parameter, so nothing downstream -- caller, prompt builder, or a bug in
    the pass loop -- can ask this window to see further than it was built to.
    """

    def __init__(self, iconn: sqlite3.Connection, max_seq: int):
        """Fix the bound for the lifetime of this window."""
        self._iconn = iconn
        self._max_seq = max_seq

    def chapters(self, book_id: str) -> list[dict]:
        """Chapters (front matter or body, never excerpts) entirely at or below the bound, in reading order."""
        rows = self._iconn.execute(
            """
            SELECT chapter_idx, label, part_label, kind, start_seq, end_seq
            FROM chapter
            WHERE book_id = ? AND kind != 'excerpt' AND end_seq <= ?
            ORDER BY start_seq
            """,
            (book_id, self._max_seq),
        ).fetchall()
        return [dict(r) for r in rows]

    def chapter_paragraphs(self, book_id: str, chapter_idx: int) -> list[dict]:
        """Full paragraph text of one chapter; raises rather than truncating if any of it sits above the bound."""
        ch = self._iconn.execute(
            "SELECT start_seq, end_seq, kind FROM chapter WHERE book_id = ? AND chapter_idx = ?",
            (book_id, chapter_idx),
        ).fetchone()
        if ch is None:
            raise ValueError(f"unknown chapter_idx {chapter_idx} for book {book_id!r}")
        if ch["kind"] == "excerpt":
            raise ValueError(f"chapter {chapter_idx} of {book_id!r} is an excerpt and cannot be windowed")
        if ch["end_seq"] > self._max_seq:
            raise ValueError(
                f"chapter {chapter_idx} of {book_id!r} ends at seq {ch['end_seq']}, "
                f"above this window's bound of {self._max_seq}"
            )
        return self.paragraphs_in_range(book_id, ch["start_seq"], ch["end_seq"])

    def paragraphs_in_range(self, book_id: str, start_seq: int, end_seq: int) -> list[dict]:
        """Raw paragraphs in a seq range; raises rather than clamping if the range reaches past the bound."""
        if end_seq > self._max_seq:
            raise ValueError(
                f"requested range end {end_seq} exceeds this window's bound of {self._max_seq}"
            )
        rows = self._iconn.execute(
            """
            SELECT id, book_id, spine_idx, para_idx, chapter_idx, chapter_label, global_seq, text
            FROM para
            WHERE book_id = ? AND global_seq BETWEEN ? AND ?
              AND kind != 'excerpt' AND global_seq <= ?
            ORDER BY global_seq
            """,
            (book_id, start_seq, end_seq, self._max_seq),
        ).fetchall()
        return [dict(r) for r in rows]

    def registry_state(self, book_id: str) -> dict:
        """Entity nodes, edges, and attributes knowable at or below the bound.

        This is what seeds a chapter's context: the registry as of the
        previous chapter, never anything this window's own chapter would add.
        """
        nodes = self._iconn.execute(
            """
            SELECT n.id, n.designator, n.node_kind, n.first_seq, n.cite_para_id
            FROM entity_node n
            JOIN para p ON p.id = n.cite_para_id
            WHERE n.book_id = ? AND n.first_seq <= ? AND p.kind != 'excerpt'
            ORDER BY n.first_seq
            """,
            (book_id, self._max_seq),
        ).fetchall()
        edges = self._iconn.execute(
            """
            SELECT e.id, e.src_node_id, e.dst_node_id, e.edge_type, e.revealed_at_seq, e.cite_para_id
            FROM entity_edge e
            JOIN entity_node src ON src.id = e.src_node_id
            LEFT JOIN para p ON p.id = e.cite_para_id
            WHERE src.book_id = ? AND e.revealed_at_seq <= ?
              AND (e.cite_para_id IS NULL OR p.kind != 'excerpt')
            ORDER BY e.revealed_at_seq
            """,
            (book_id, self._max_seq),
        ).fetchall()
        attrs = self._iconn.execute(
            """
            SELECT a.id, a.node_id, a.attr_kind, a.value, a.first_seq, a.cite_para_id
            FROM entity_attr a
            JOIN entity_node n ON n.id = a.node_id
            LEFT JOIN para p ON p.id = a.cite_para_id
            WHERE n.book_id = ? AND a.first_seq <= ?
              AND (a.cite_para_id IS NULL OR p.kind != 'excerpt')
            ORDER BY a.first_seq
            """,
            (book_id, self._max_seq),
        ).fetchall()
        return {
            "nodes": [dict(r) for r in nodes],
            "edges": [dict(r) for r in edges],
            "attrs": [dict(r) for r in attrs],
        }
