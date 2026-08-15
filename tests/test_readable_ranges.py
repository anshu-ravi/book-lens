"""Union-of-ranges retrieval: the case a single ceiling cannot represent --
a reader who skipped a middle book. See CLAUDE.md's "one invariant" and
DECISIONS.md section 4.
"""

from __future__ import annotations

import json
import random

import pytest

from booklens import db, progress, tools

NUM_CHAPTERS = 3
PARAS_PER_CHAPTER = 5

BOOK2_TOKEN = "BOOK2ONLY_TOKEN_44N1"
BOOK3_TOKEN = "BOOK3ONLY_TOKEN_77Q2"

BOOK_ORDER = {"b1": 1, "b2": 2, "b3": 3}


def build_three_book_fixture(tmp_path):
    """A synthetic 3-book series, one spine document per chapter.

    BOOK2_TOKEN appears once in b2 (chapter 1, para 0); BOOK3_TOKEN once in b3
    (chapter 1, para 0). Also seeds one 'excerpt' row per book, at the very
    start of global_seq space for that book, to double as a quarantine check.

    Returns (iconn, pconn, meta) with meta["books"][book_id]["chapters"].
    """
    iconn = db.connect_index(tmp_path / "index.db")
    pconn = db.connect_progress(tmp_path / "progress.db")

    meta = {"books": {}}
    for book_id, book_order in BOOK_ORDER.items():
        iconn.execute(
            """
            INSERT INTO book(id, sha256, title, author, source_path, series_id,
                              book_order, sequence_tier, label_tier, ingested_at)
            VALUES (?, ?, ?, 'Some Author', '/x.epub', 's1', ?, 'S1', 'L1', '2026-01-01')
            """,
            (book_id, f"sha-{book_id}", f"Book {book_order}", book_order),
        )

        # An excerpt paragraph/chapter sitting below the book's own body --
        # must never surface no matter what the readable ranges allow.
        excerpt_seq = db.global_seq(book_order, 0, 0) - 1 if book_order > 1 else None

        chapters = []
        for ch in range(NUM_CHAPTERS):
            para_rows = []
            for p in range(PARAS_PER_CHAPTER):
                gseq = db.global_seq(book_order, ch, p)
                text = f"lorem {book_id} chapter {ch} paragraph {p} ipsum dolor sit amet"
                if book_id == "b2" and ch == 1 and p == 0:
                    text += f" {BOOK2_TOKEN} appears here"
                if book_id == "b3" and ch == 1 and p == 0:
                    text += f" {BOOK3_TOKEN} appears here"
                iconn.execute(
                    """
                    INSERT INTO para(book_id, spine_idx, para_idx, global_seq,
                                      chapter_idx, chapter_label, text)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (book_id, ch, p, gseq, ch, f"Chapter {ch}", text),
                )
                para_rows.append(gseq)
            start, end = para_rows[0], para_rows[-1]
            iconn.execute(
                """
                INSERT INTO chapter(book_id, chapter_idx, label, part_label, start_seq, end_seq)
                VALUES (?, ?, ?, NULL, ?, ?)
                """,
                (book_id, ch, f"Chapter {ch}", start, end),
            )
            chapters.append(
                {"chapter_idx": ch, "label": f"Chapter {ch}", "start_seq": start, "end_seq": end}
            )
        meta["books"][book_id] = {"book_order": book_order, "chapters": chapters}

    iconn.commit()
    pconn.commit()
    return iconn, pconn, meta


def _finish(pconn, iconn, book_id):
    progress.set_position(pconn, iconn, book_id, status="finished")


def _all_tool_calls(t: tools.Tools, meta, query="lorem"):
    """Exercise every public method across all three books; return results."""
    calls = []
    calls.append(("list_books", t.list_books()))
    for book_id in meta["books"]:
        calls.append((f"list_chapters:{book_id}", t.list_chapters(book_id)))
        calls.append((f"read_raw:{book_id}", t.read_raw(book_id, 0, NUM_CHAPTERS - 1)))
        calls.append((f"read_digest:{book_id}", t.read_digest(book_id, chapter=NUM_CHAPTERS - 1)))
    calls.append(("search", t.search(query)))
    calls.append(("search_regex", t.search(query, regex=True)))
    calls.append(("first_seen_b2", t.first_seen(BOOK2_TOKEN)))
    calls.append(("first_seen_b3", t.first_seen(BOOK3_TOKEN)))
    for book_id, book in meta["books"].items():
        for ch in book["chapters"]:
            cid = tools.format_citation_id(book_id, ch["chapter_idx"], 0)
            try:
                calls.append((f"context:{cid}", t.context(cid, window=10)))
            except ValueError:
                calls.append((f"context:{cid}", {}))
    return calls


def _blob(result) -> str:
    return json.dumps(result, default=str)


# -- 1. the case the whole change exists for ---------------------------------


def test_skipped_middle_book_never_surfaces(tmp_path):
    iconn, pconn, meta = build_three_book_fixture(tmp_path)
    _finish(pconn, iconn, "b1")
    # b2 left unread entirely.
    _finish(pconn, iconn, "b3")
    t = tools.Tools(iconn, pconn)

    saw_b1 = False
    saw_b3 = False
    for name, result in _all_tool_calls(t, meta):
        blob = _blob(result)
        assert "b2:" not in blob and BOOK2_TOKEN not in blob, f"{name} leaked book 2: {result!r}"
        if "b1:" in blob:
            saw_b1 = True
        if "b3:" in blob:
            saw_b3 = True

    assert t.list_chapters("b2")["chapters"] == []
    assert t.first_seen(BOOK2_TOKEN) == {"result": "NOT_YET_SEEN"}
    assert t.first_seen(BOOK3_TOKEN)["result"] == "FOUND"
    assert saw_b1 and saw_b3, "finished books 1 and 3 should both surface rows"


# -- 2. nothing read at all ----------------------------------------------------


def test_nothing_read_every_tool_returns_empty(tmp_path):
    iconn, pconn, meta = build_three_book_fixture(tmp_path)
    t = tools.Tools(iconn, pconn)

    assert progress.readable_ranges(pconn, iconn) == []
    for book_id in meta["books"]:
        assert t.list_chapters(book_id)["chapters"] == []
        assert t.read_raw(book_id, 0, NUM_CHAPTERS - 1)["paragraphs"] == []
    assert t.search("lorem")["results"] == []
    assert t.search("lorem", regex=True)["results"] == []
    assert t.first_seen(BOOK2_TOKEN) == {"result": "NOT_YET_SEEN"}
    assert t.first_seen(BOOK3_TOKEN) == {"result": "NOT_YET_SEEN"}
    with pytest.raises(ValueError):
        t.context(tools.format_citation_id("b1", 0, 0))


# -- 3. merge behaviour + mid-book truncation ---------------------------------


def test_mid_book_ceiling_truncates_only_that_book(tmp_path):
    iconn, pconn, meta = build_three_book_fixture(tmp_path)
    _finish(pconn, iconn, "b1")
    ch1_start = meta["books"]["b2"]["chapters"][1]["start_seq"]
    progress.reset_ceiling(pconn, "b2", ch1_start)  # partway into b2 chapter 1
    t = tools.Tools(iconn, pconn)

    b1_chapters = t.list_chapters("b1")["chapters"]
    assert len(b1_chapters) == NUM_CHAPTERS  # b1 fully readable, untouched by b2's cap

    b2_chapters = t.list_chapters("b2")["chapters"]
    assert len(b2_chapters) == 2  # chapter 0 fully, chapter 1 just begun

    assert t.list_chapters("b3")["chapters"] == []


def test_ranges_merge_when_overlapping(tmp_path):
    iconn, pconn, meta = build_three_book_fixture(tmp_path)
    # Contrived overlap: b1's ceiling reaches into b2's own floor.
    progress.reset_ceiling(pconn, "b1", db.global_seq(2, 0, 0) + 500)
    progress.set_position(pconn, iconn, "b2", status="reading", chapter_idx=0)
    ranges = progress.readable_ranges(pconn, iconn)
    assert len(ranges) == 1
    assert ranges[0][0] == 1_000_000


# -- 4. context() must not tunnel across a gap --------------------------------


def test_context_does_not_cross_gap_into_skipped_book(tmp_path):
    iconn, pconn, meta = build_three_book_fixture(tmp_path)
    _finish(pconn, iconn, "b1")
    # b2 skipped.
    _finish(pconn, iconn, "b3")
    t = tools.Tools(iconn, pconn)

    # A citation inside the skipped book is simply unreadable.
    with pytest.raises(ValueError):
        t.context(tools.format_citation_id("b2", 1, 0), window=50)

    # A wide window from the start of b3 must never reach back into b2 or b1.
    b3_ch0_start_cid = tools.format_citation_id("b3", 0, 0)
    result = t.context(b3_ch0_start_cid, window=50)
    cids = [p["citation_id"] for p in result["paragraphs"]]
    assert all(cid.startswith("b3:") for cid in cids)
    assert BOOK2_TOKEN not in _blob(result)


# -- 5. property: every returned row sits inside the union of ranges ---------


def test_property_rows_always_inside_union_of_ranges(tmp_path):
    iconn, pconn, meta = build_three_book_fixture(tmp_path)
    rng = random.Random(20260815)

    book_ids = list(meta["books"])
    for _ in range(30):
        for book_id in book_ids:
            choice = rng.choice(["unread", "partial", "finished"])
            if choice == "unread":
                progress.reset_ceiling(pconn, book_id, 0)
            elif choice == "finished":
                _finish(pconn, iconn, book_id)
            else:
                ch = rng.choice(meta["books"][book_id]["chapters"])
                offset = rng.randint(0, PARAS_PER_CHAPTER - 1)
                progress.reset_ceiling(pconn, book_id, ch["start_seq"] + offset)

        ranges = progress.readable_ranges(pconn, iconn)
        t = tools.Tools(iconn, pconn)

        def inside_any_range(gseq):
            return any(lo <= gseq <= hi for lo, hi in ranges)

        for name, result in _all_tool_calls(t, meta, query="lorem"):
            for book_id in book_ids:
                for spine_idx in range(NUM_CHAPTERS):
                    for para_idx in range(PARAS_PER_CHAPTER):
                        cid = tools.format_citation_id(book_id, spine_idx, para_idx)
                        if cid in _blob(result):
                            gseq = db.global_seq(BOOK_ORDER[book_id], spine_idx, para_idx)
                            assert inside_any_range(gseq), (
                                f"{name} returned {cid} (global_seq={gseq}) "
                                f"outside readable ranges {ranges}"
                            )


# -- 6. excerpt quarantine still holds at every progress state ---------------


def test_excerpt_rows_unreachable_at_every_progress_state(tmp_path):
    iconn, pconn, meta = build_three_book_fixture(tmp_path)
    excerpt_book, excerpt_chapter_idx = "b2", NUM_CHAPTERS  # a chapter_idx not used by body
    excerpt_seq = db.global_seq(BOOK_ORDER[excerpt_book], excerpt_chapter_idx, 0)
    excerpt_token = "EXCERPT_QUARANTINE_TOKEN_88Z"
    iconn.execute(
        """
        INSERT INTO para(book_id, spine_idx, para_idx, global_seq,
                          chapter_idx, chapter_label, text, kind)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'excerpt')
        """,
        (
            excerpt_book,
            excerpt_chapter_idx,
            0,
            excerpt_seq,
            excerpt_chapter_idx,
            "Excerpt",
            f"a preview from another book {excerpt_token}",
        ),
    )
    iconn.execute(
        """
        INSERT INTO chapter(book_id, chapter_idx, label, part_label, start_seq, end_seq, kind)
        VALUES (?, ?, 'Excerpt', NULL, ?, ?, 'excerpt')
        """,
        (excerpt_book, excerpt_chapter_idx, excerpt_seq, excerpt_seq),
    )
    iconn.commit()

    for book_id in meta["books"]:
        _finish(pconn, iconn, book_id)
    # Push b2's ceiling past the excerpt's own global_seq so this test isolates
    # the kind='excerpt' predicate, not just the range boundary.
    progress.reset_ceiling(pconn, excerpt_book, excerpt_seq + 10)
    t = tools.Tools(iconn, pconn)

    for name, result in _all_tool_calls(t, meta, query=excerpt_token):
        assert excerpt_token not in _blob(result), f"{name} leaked an excerpt row: {result!r}"
    assert "Excerpt" not in [c["label"] for c in t.list_chapters(excerpt_book)["chapters"]]


# -- 7. two live Tools over one connection do not share bounds ---------------


def test_second_tools_on_same_connection_does_not_widen_first(tmp_path):
    """The bug this whole change exists for: constructing a second `Tools`
    over the same `iconn` used to rewrite the first instance's temp table,
    silently widening what it would serve. Reproduced across several
    methods, not just one, since any of them could have been fixed in
    isolation while others still shared the connection-wide table."""
    iconn, pconn, meta = build_three_book_fixture(tmp_path)
    _finish(pconn, iconn, "b1")
    # b2 left unread -- reader A must never see it, even after B is built.
    a = tools.Tools(iconn, pconn)

    a_search_before = a.search("lorem")["results"]
    a_read_before = a.read_raw("b1", 0, NUM_CHAPTERS - 1)["paragraphs"]
    a_chapters_before = a.list_chapters("b1")["chapters"]
    cid = tools.format_citation_id("b1", 0, 0)
    a_context_before = a.context(cid, window=10)["paragraphs"]

    # Advance progress and build a second Tools on the SAME connection.
    _finish(pconn, iconn, "b2")
    b = tools.Tools(iconn, pconn)

    # B correctly sees the wider world.
    b_search = b.search("lorem")["results"]
    assert len(b_search) > len(a_search_before)
    assert b.list_chapters("b2")["chapters"] != []

    # A must be completely unaffected by B's existence.
    assert a.search("lorem")["results"] == a_search_before
    assert a.read_raw("b1", 0, NUM_CHAPTERS - 1)["paragraphs"] == a_read_before
    assert a.list_chapters("b1")["chapters"] == a_chapters_before
    assert a.context(cid, window=10)["paragraphs"] == a_context_before
    assert a.list_chapters("b2")["chapters"] == []
    assert BOOK2_TOKEN not in _blob(a.search("lorem"))
    for name, result in _all_tool_calls(a, meta):
        assert "b2:" not in _blob(result) and BOOK2_TOKEN not in _blob(result), (
            f"A leaked book 2 after B was constructed on the same connection: {name} -> {result!r}"
        )


def test_two_tools_instances_have_distinct_table_names_and_close_is_scoped(tmp_path):
    """Each `Tools` gets its own temp table name, and `close()` drops only
    its own -- a sibling built on the same connection must stay queryable."""
    iconn, pconn, meta = build_three_book_fixture(tmp_path)
    _finish(pconn, iconn, "b1")
    a = tools.Tools(iconn, pconn)
    b = tools.Tools(iconn, pconn)

    assert a._table != b._table
    assert a._table.startswith("readable_range_")
    assert b._table.startswith("readable_range_")

    b_before = b.list_chapters("b1")["chapters"]
    a.close()

    # b is untouched by a's close().
    assert b.list_chapters("b1")["chapters"] == b_before
    # a's own table is actually gone.
    row = iconn.execute(
        "SELECT name FROM sqlite_temp_master WHERE type='table' AND name=?",
        (a._table,),
    ).fetchone()
    assert row is None


def test_unclosed_tools_remains_correct_and_does_not_corrupt_sibling(tmp_path):
    """An un-closed `Tools` is untidy, never unsafe: it must still serve
    correct bounds and must not corrupt a still-live sibling that outlives
    it, or one constructed after it without ever closing."""
    iconn, pconn, meta = build_three_book_fixture(tmp_path)
    _finish(pconn, iconn, "b1")
    a = tools.Tools(iconn, pconn)  # never closed
    a_chapters = a.list_chapters("b1")["chapters"]

    _finish(pconn, iconn, "b2")
    b = tools.Tools(iconn, pconn)  # also never closed
    assert a.list_chapters("b1")["chapters"] == a_chapters
    assert a.list_chapters("b2")["chapters"] == []
    assert b.list_chapters("b2")["chapters"] != []


def test_tools_context_manager_closes_on_exit(tmp_path):
    """`Tools` works as a context manager and drops its table on exit."""
    iconn, pconn, meta = build_three_book_fixture(tmp_path)
    _finish(pconn, iconn, "b1")
    with tools.Tools(iconn, pconn) as t:
        table = t._table
        assert t.list_chapters("b1")["chapters"] != []

    row = iconn.execute(
        "SELECT name FROM sqlite_temp_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    assert row is None
