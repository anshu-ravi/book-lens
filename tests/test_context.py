"""Invariant tests for booklens.context: the assembler must never emit above
the reader's cutoff, and must never emit `kind = 'excerpt'` content.

Builds its own synthetic fixture (rather than reusing tests/test_tools.py's)
so it can include an excerpt chapter -- the measured hazard from
DECISIONS.md section 3, where a book's back matter carries the next book's
opening paragraphs inside its own seq range. All text is invented; no real
book content, per project policy.
"""

from __future__ import annotations

import random
import re

import pytest

from booklens import context, db, progress, tools

NUM_CHAPTERS = 4
PARAS_PER_CHAPTER = 6
EXCERPT_PARAS = 5

EXCERPT_TOKEN = "EXCERPTTOKEN_QP7"

BOOK_ORDER = {"rr1": 1, "rr2": 2}

_CITATION_RE = re.compile(r"\[([a-zA-Z0-9_-]+):(\d+):p(\d+)\]")


def build_fixture(tmp_path):
    """Two-book series; rr1 carries a trailing excerpt chapter (next book's
    opening, sitting inside rr1's own seq range) to exercise the exclusion.

    Returns (iconn, pconn, meta) where meta["books"][id]["chapters"] lists
    every body chapter's {chapter_idx, label, start_seq, end_seq}, and
    meta["max_global_seq"] is the highest seq anywhere in the fixture
    (including the excerpt, which must never surface).
    """
    iconn = db.connect_index(tmp_path / "index.db")
    pconn = db.connect_progress(tmp_path / "progress.db")

    meta = {"books": {}}
    max_seq = 0
    for book_id, book_order in (("rr1", 1), ("rr2", 2)):
        iconn.execute(
            """
            INSERT INTO book(id, sha256, title, author, source_path, series_id,
                              book_order, sequence_tier, label_tier, ingested_at)
            VALUES (?, ?, ?, 'Some Author', '/x.epub', 's1', ?, 'S1', 'L1', '2026-01-01')
            """,
            (book_id, f"sha-{book_id}", f"Book {book_order}", book_order),
        )
        chapters = []
        next_chapter_idx = 0
        for ch in range(NUM_CHAPTERS):
            para_rows = []
            for p in range(PARAS_PER_CHAPTER):
                gseq = db.global_seq(book_order, ch, p)
                text = f"lorem {book_id} chapter {ch} paragraph {p} ipsum dolor sit amet"
                iconn.execute(
                    """
                    INSERT INTO para(book_id, spine_idx, para_idx, global_seq,
                                      chapter_idx, chapter_label, text, kind)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 'body')
                    """,
                    (book_id, ch, p, gseq, ch, f"Chapter {ch}", text),
                )
                para_rows.append(gseq)
                max_seq = max(max_seq, gseq)
            start, end = para_rows[0], para_rows[-1]
            iconn.execute(
                """
                INSERT INTO chapter(book_id, chapter_idx, label, part_label,
                                     start_seq, end_seq, kind)
                VALUES (?, ?, ?, NULL, ?, ?, 'body')
                """,
                (book_id, ch, f"Chapter {ch}", start, end),
            )
            chapters.append(
                {"chapter_idx": ch, "label": f"Chapter {ch}", "start_seq": start, "end_seq": end}
            )
            next_chapter_idx = ch + 1
        meta["books"][book_id] = {"book_order": book_order, "chapters": chapters}

        if book_id == "rr1":
            # Trailing excerpt: sits at a higher spine_idx (and thus higher
            # global_seq) than rr1's own body, but still well inside rr1's
            # book-order magnitude -- exactly the hazard section 3 measured.
            spine = NUM_CHAPTERS
            para_rows = []
            for p in range(EXCERPT_PARAS):
                gseq = db.global_seq(book_order, spine, p)
                text = f"lorem excerpt {p} {EXCERPT_TOKEN} preview of the next book"
                iconn.execute(
                    """
                    INSERT INTO para(book_id, spine_idx, para_idx, global_seq,
                                      chapter_idx, chapter_label, text, kind)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 'excerpt')
                    """,
                    (book_id, spine, p, gseq, next_chapter_idx, "Excerpt", text),
                )
                para_rows.append(gseq)
                max_seq = max(max_seq, gseq)
            iconn.execute(
                """
                INSERT INTO chapter(book_id, chapter_idx, label, part_label,
                                     start_seq, end_seq, kind)
                VALUES (?, ?, 'Excerpt', NULL, ?, ?, 'excerpt')
                """,
                (book_id, next_chapter_idx, para_rows[0], para_rows[-1]),
            )

    iconn.commit()
    pconn.commit()
    meta["max_global_seq"] = max_seq
    return iconn, pconn, meta


def _set_ceiling(pconn, book_id, ceiling_seq):
    progress.reset_ceiling(pconn, book_id, ceiling_seq)


def _citations_in_order(text):
    """(book, spine, para) tuples in the order they appear in assembled text."""
    return [(m.group(1), int(m.group(2)), int(m.group(3))) for m in _CITATION_RE.finditer(text)]


# -- the invariant -------------------------------------------------------------


def test_no_paragraph_above_ceiling_across_random_ceilings(tmp_path):
    iconn, pconn, meta = build_fixture(tmp_path)
    rng = random.Random(20260816)

    boundary_seqs = set()
    for book in meta["books"].values():
        for ch in book["chapters"]:
            boundary_seqs.add(ch["start_seq"])
            boundary_seqs.add(ch["end_seq"])
            boundary_seqs.add(ch["start_seq"] - 1)
            boundary_seqs.add(ch["end_seq"] + 1)
    ceilings = sorted(boundary_seqs) + [
        rng.randint(0, meta["max_global_seq"] + 10) for _ in range(30)
    ]
    ceilings = [max(0, c) for c in ceilings]

    checked = 0
    for ceiling in ceilings:
        _set_ceiling(pconn, "rr1", ceiling)
        _set_ceiling(pconn, "rr2", ceiling)
        with tools.Tools(iconn, pconn) as t:
            result = context.assemble(t)

        for book_id, spine_idx, para_idx in _citations_in_order(result.text):
            gseq = db.global_seq(BOOK_ORDER[book_id], spine_idx, para_idx)
            assert gseq <= ceiling, (
                f"leak: {book_id}:{spine_idx}:p{para_idx} (global_seq={gseq}) "
                f"exceeds ceiling={ceiling}"
            )
        checked += 1

    assert checked >= 30


def test_excerpt_paragraphs_never_appear_at_any_ceiling(tmp_path):
    iconn, pconn, meta = build_fixture(tmp_path)
    # Ceilings that deliberately span the excerpt chapter's own seq range,
    # including its exact end -- the case that must still exclude it.
    excerpt_start = db.global_seq(1, NUM_CHAPTERS, 0)
    excerpt_end = db.global_seq(1, NUM_CHAPTERS, EXCERPT_PARAS - 1)
    ceilings = [
        excerpt_start - 1,
        excerpt_start,
        excerpt_start + 1,
        excerpt_end,
        excerpt_end + 1,
        meta["max_global_seq"],
    ]
    for ceiling in ceilings:
        _set_ceiling(pconn, "rr1", ceiling)
        _set_ceiling(pconn, "rr2", 0)
        with tools.Tools(iconn, pconn) as t:
            result = context.assemble(t)
        assert EXCERPT_TOKEN not in result.text, f"excerpt leaked at ceiling={ceiling}"


def test_paragraph_order_strictly_ascending_by_global_seq(tmp_path):
    iconn, pconn, meta = build_fixture(tmp_path)
    _set_ceiling(pconn, "rr1", meta["books"]["rr1"]["chapters"][-1]["end_seq"])
    _set_ceiling(pconn, "rr2", meta["books"]["rr2"]["chapters"][-1]["end_seq"])
    with tools.Tools(iconn, pconn) as t:
        result = context.assemble(t)

    seqs = [
        db.global_seq(BOOK_ORDER[b], s, p) for b, s, p in _citations_in_order(result.text)
    ]
    assert len(seqs) == result.para_count
    assert seqs == sorted(seqs)
    assert len(set(seqs)) == len(seqs)  # strictly ascending, no repeats
    assert result.max_global_seq == seqs[-1]


def test_citations_round_trip_and_resolve_in_readable_set(tmp_path):
    iconn, pconn, meta = build_fixture(tmp_path)
    _set_ceiling(pconn, "rr1", meta["books"]["rr1"]["chapters"][1]["end_seq"])
    _set_ceiling(pconn, "rr2", 0)
    with tools.Tools(iconn, pconn) as t:
        result = context.assemble(t)
        for book_id, spine_idx, para_idx in _citations_in_order(result.text):
            cid = tools.format_citation_id(book_id, spine_idx, para_idx)
            assert tools.parse_citation_id(cid) == (book_id, spine_idx, para_idx)
            # Resolves via the same bounded tool that would back a citation
            # click -- raises if it were ever outside the readable set.
            resolved = t.context(cid, window=0)
            assert resolved["paragraphs"][0]["citation_id"] == cid


# -- byte stability --------------------------------------------------------


def test_byte_stable_across_repeated_assembly(tmp_path):
    iconn, pconn, meta = build_fixture(tmp_path)
    _set_ceiling(pconn, "rr1", meta["books"]["rr1"]["chapters"][2]["end_seq"])
    _set_ceiling(pconn, "rr2", meta["books"]["rr2"]["chapters"][0]["end_seq"])

    with tools.Tools(iconn, pconn) as t1:
        first = context.assemble(t1)
    with tools.Tools(iconn, pconn) as t2:
        second = context.assemble(t2)

    assert first.text == second.text
    assert first.content_hash == second.content_hash
    assert first.para_count == second.para_count
    assert first.chapter_span == second.chapter_span


def test_advancing_ceiling_only_appends_to_the_prefix(tmp_path):
    """The ceiling only ever moves forward -- assembling at a later ceiling
    must reproduce the earlier text as a literal prefix, or prompt caching
    (DECISIONS.md section 7) silently breaks."""
    iconn, pconn, meta = build_fixture(tmp_path)
    ch0_end = meta["books"]["rr1"]["chapters"][0]["end_seq"]
    ch1_end = meta["books"]["rr1"]["chapters"][1]["end_seq"]

    _set_ceiling(pconn, "rr1", ch0_end)
    _set_ceiling(pconn, "rr2", 0)
    with tools.Tools(iconn, pconn) as t:
        low = context.assemble(t)

    _set_ceiling(pconn, "rr1", ch1_end)
    with tools.Tools(iconn, pconn) as t:
        high = context.assemble(t)

    assert high.text.startswith(low.text)
    assert high.para_count > low.para_count


# -- empty and overflow ------------------------------------------------------


def test_nothing_read_gives_empty_context(tmp_path):
    iconn, pconn, meta = build_fixture(tmp_path)
    with tools.Tools(iconn, pconn) as t:
        result = context.assemble(t)

    assert result.text == ""
    assert result.para_count == 0
    assert result.max_global_seq is None
    assert result.chapter_span is None
    assert result.token_estimate == 0


def test_overflow_raises_rather_than_truncating(tmp_path):
    iconn, pconn, meta = build_fixture(tmp_path)
    _set_ceiling(pconn, "rr1", meta["books"]["rr1"]["chapters"][-1]["end_seq"])
    _set_ceiling(pconn, "rr2", meta["books"]["rr2"]["chapters"][-1]["end_seq"])

    with tools.Tools(iconn, pconn) as t:
        # Budget of 1 token cannot possibly hold this fixture's text.
        with pytest.raises(context.ContextOverflowError):
            context.assemble(t, max_tokens=1)

        # Sanity: the same reader position does not raise against the default.
        result = context.assemble(t)
        assert result.para_count > 0


def test_default_budget_fits_a_normal_reading_position(tmp_path):
    iconn, pconn, meta = build_fixture(tmp_path)
    _set_ceiling(pconn, "rr1", meta["books"]["rr1"]["chapters"][-1]["end_seq"])
    with tools.Tools(iconn, pconn) as t:
        result = context.assemble(t)  # default max_tokens; must not raise
    assert result.token_estimate < context.DEFAULT_MAX_TOKENS
