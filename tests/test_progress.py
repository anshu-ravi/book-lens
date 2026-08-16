"""Tests for booklens.progress: watermark monotonicity, ranges, ceiling_for."""

import pytest

from booklens import db, progress


@pytest.fixture
def iconn(tmp_path):
    conn = db.connect_index(tmp_path / "index.db")
    conn.execute(
        """
        INSERT INTO book(id, sha256, title, author, source_path, series_id,
                          book_order, sequence_tier, label_tier, ingested_at)
        VALUES ('b1', 'sha1', 'Book One', 'Auth', '/x.epub', 's1', 1, 'S1', 'L1', '2026-01-01')
        """
    )
    conn.execute(
        """
        INSERT INTO book(id, sha256, title, author, source_path, series_id,
                          book_order, sequence_tier, label_tier, ingested_at)
        VALUES ('b2', 'sha2', 'Book Two', 'Auth', '/y.epub', 's1', 2, 'S1', 'L1', '2026-01-01')
        """
    )
    # b1: 3 chapters
    for i, (start, end) in enumerate([(1000000, 1000999), (1001000, 1001999), (1002000, 1002999)]):
        conn.execute(
            "INSERT INTO chapter(book_id, chapter_idx, label, part_label, start_seq, end_seq) "
            "VALUES ('b1', ?, ?, NULL, ?, ?)",
            (i, f"Chapter {i}", start, end),
        )
    # b2: 2 chapters
    for i, (start, end) in enumerate([(2000000, 2000999), (2001000, 2001999)]):
        conn.execute(
            "INSERT INTO chapter(book_id, chapter_idx, label, part_label, start_seq, end_seq) "
            "VALUES ('b2', ?, ?, NULL, ?, ?)",
            (i, f"Chapter {i}", start, end),
        )
    conn.commit()
    return conn


@pytest.fixture
def pconn(tmp_path):
    return db.connect_progress(tmp_path / "progress.db")


def test_get_progress_defaults_to_unread(pconn):
    p = progress.get_progress(pconn, "nonexistent")
    assert p.status == "unread"
    assert p.position_chapter_idx is None
    assert p.ceiling_seq == 0


def test_set_position_unread(pconn, iconn):
    p = progress.set_position(pconn, iconn, "b1", status="unread")
    assert p.ceiling_seq == 0
    assert p.status == "unread"


def test_set_position_reading_advances_ceiling(pconn, iconn):
    p = progress.set_position(pconn, iconn, "b1", status="reading", chapter_idx=1)
    assert p.ceiling_seq == 1001999
    assert p.status == "reading"
    assert p.position_chapter_idx == 1


def test_set_position_reading_no_chapter_idx(pconn, iconn):
    p = progress.set_position(pconn, iconn, "b1", status="reading", chapter_idx=None)
    assert p.ceiling_seq == 0


def test_set_position_finished_uses_max_end_seq(pconn, iconn):
    p = progress.set_position(pconn, iconn, "b1", status="finished")
    assert p.ceiling_seq == 1002999


def test_watermark_never_lowers_via_set_position(pconn, iconn):
    progress.set_position(pconn, iconn, "b1", status="finished")
    p = progress.set_position(pconn, iconn, "b1", status="reading", chapter_idx=0)
    # Dropping back to chapter 0 must NOT lower the ceiling below "finished".
    assert p.ceiling_seq == 1002999
    # But the current position DOES move back.
    assert p.position_chapter_idx == 0
    assert p.status == "reading"


def test_reset_ceiling_is_the_only_way_down(pconn, iconn):
    progress.set_position(pconn, iconn, "b1", status="finished")
    p = progress.reset_ceiling(pconn, "b1", 1000500)
    assert p.ceiling_seq == 1000500


def test_reset_ceiling_rejects_negative(pconn):
    with pytest.raises(ValueError):
        progress.reset_ceiling(pconn, "b1", -5)


def test_set_position_unknown_book_raises(pconn, iconn):
    with pytest.raises(ValueError):
        progress.set_position(pconn, iconn, "nope", status="reading", chapter_idx=0)


def test_set_position_out_of_range_chapter_raises(pconn, iconn):
    with pytest.raises(ValueError):
        progress.set_position(pconn, iconn, "b1", status="reading", chapter_idx=99)


def test_set_position_invalid_status_raises(pconn, iconn):
    with pytest.raises(ValueError):
        progress.set_position(pconn, iconn, "b1", status="bogus")


def test_ceiling_for_is_max_across_books(pconn, iconn):
    progress.set_position(pconn, iconn, "b1", status="reading", chapter_idx=0)
    progress.set_position(pconn, iconn, "b2", status="finished")
    assert progress.ceiling_for(pconn, iconn) == 2001999


def test_ceiling_for_with_no_progress_is_zero(pconn, iconn):
    assert progress.ceiling_for(pconn, iconn) == 0


def test_readable_ranges_is_a_true_union(pconn, iconn):
    progress.set_position(pconn, iconn, "b2", status="finished")
    # Finishing b2 cascades b1 to finished too (series read in order); pull
    # b1 back to a partial ceiling with reset_ceiling, the only way down, to
    # exercise a genuinely disjoint union.
    progress.reset_ceiling(pconn, "b1", 1000999)
    ranges = progress.readable_ranges(pconn, iconn)
    # b1's range floors at its own book_order * 1_000_000, not 0, so the two
    # stay disjoint -- this is exactly the union DECISIONS.md section 4 calls for.
    assert ranges == [(1000000, 1000999), (2000000, 2001999)]


def test_readable_ranges_merges_overlapping_books(pconn, iconn):
    # Contrived but valid: b1's ceiling reaches into b2's own floor, so the
    # two per-book ranges overlap and the merge step collapses them into one.
    progress.reset_ceiling(pconn, "b1", 2000500)
    progress.set_position(pconn, iconn, "b2", status="reading", chapter_idx=0)
    ranges = progress.readable_ranges(pconn, iconn)
    assert ranges == [(1000000, 2000999)]


def test_readable_ranges_empty_when_nothing_read(pconn, iconn):
    assert progress.readable_ranges(pconn, iconn) == []


def test_readable_ranges_excludes_unread_zero_ceiling_books(pconn, iconn):
    progress.set_position(pconn, iconn, "b1", status="unread")
    assert progress.readable_ranges(pconn, iconn) == []


@pytest.fixture
def iconn3(tmp_path):
    """Three-book series, for cascade tests that need a book after the pair."""
    conn = db.connect_index(tmp_path / "index3.db")
    for book_id, order, path in [("b1", 1, "/x.epub"), ("b2", 2, "/y.epub"), ("b3", 3, "/z.epub")]:
        conn.execute(
            """
            INSERT INTO book(id, sha256, title, author, source_path, series_id,
                              book_order, sequence_tier, label_tier, ingested_at)
            VALUES (?, ?, ?, 'Auth', ?, 's1', ?, 'S1', 'L1', '2026-01-01')
            """,
            (book_id, f"sha-{book_id}", f"Book {order}", path, order),
        )
    for book_id, chapters in [
        ("b1", [(1000000, 1000999), (1001000, 1001999)]),
        ("b2", [(2000000, 2000999), (2001000, 2001999)]),
        ("b3", [(3000000, 3000999), (3001000, 3001999)]),
    ]:
        for i, (start, end) in enumerate(chapters):
            conn.execute(
                "INSERT INTO chapter(book_id, chapter_idx, label, part_label, start_seq, end_seq) "
                "VALUES (?, ?, ?, NULL, ?, ?)",
                (book_id, i, f"Chapter {i}", start, end),
            )
    conn.commit()
    return conn


def test_set_position_reading_cascades_earlier_books_to_finished(pconn, iconn3):
    """Marking book 3 'reading' assumes books 1 and 2 were finished."""
    progress.set_position(pconn, iconn3, "b3", status="reading", chapter_idx=0)
    b1 = progress.get_progress(pconn, "b1")
    b2 = progress.get_progress(pconn, "b2")
    assert b1.status == "finished"
    assert b1.ceiling_seq == 1001999
    assert b2.status == "finished"
    assert b2.ceiling_seq == 2001999


def test_set_position_on_first_book_does_not_touch_later_books(pconn, iconn3):
    """Marking book 1 'reading' has no later books to cascade to; books 2 and 3 stay untouched."""
    progress.set_position(pconn, iconn3, "b1", status="reading", chapter_idx=0)
    b2 = progress.get_progress(pconn, "b2")
    b3 = progress.get_progress(pconn, "b3")
    assert b2.status == "unread"
    assert b2.ceiling_seq == 0
    assert b3.status == "unread"
    assert b3.ceiling_seq == 0


def test_cascade_is_confined_to_the_same_series(pconn, iconn3):
    """A book in a different series must never be advanced by another series' cascade."""
    iconn3.execute(
        """
        INSERT INTO book(id, sha256, title, author, source_path, series_id,
                          book_order, sequence_tier, label_tier, ingested_at)
        VALUES ('other', 'sha-other', 'Other Series Book 1', 'Auth', '/o.epub', 's2', 1, 'S1', 'L1', '2026-01-01')
        """
    )
    iconn3.execute(
        "INSERT INTO chapter(book_id, chapter_idx, label, part_label, start_seq, end_seq) "
        "VALUES ('other', 0, 'Chapter 0', NULL, 9000000, 9000999)"
    )
    iconn3.commit()
    progress.set_position(pconn, iconn3, "b3", status="finished")
    other = progress.get_progress(pconn, "other")
    assert other.status == "unread"
    assert other.ceiling_seq == 0


def test_set_position_unread_does_not_cascade(pconn, iconn3):
    """Setting book 3 to 'unread' must not touch books 1 or 2."""
    progress.set_position(pconn, iconn3, "b1", status="finished")
    progress.set_position(pconn, iconn3, "b3", status="unread")
    b1 = progress.get_progress(pconn, "b1")
    assert b1.status == "finished"
    assert b1.ceiling_seq == 1001999


def test_cascade_never_lowers_an_existing_higher_ceiling(pconn, iconn3):
    """If an earlier book's ceiling is already ahead of its own finish point, the cascade must not lower it."""
    progress.reset_ceiling(pconn, "b1", 2001999)  # already exposed to book 2's content
    progress.set_position(pconn, iconn3, "b3", status="reading", chapter_idx=0)
    b1 = progress.get_progress(pconn, "b1")
    assert b1.ceiling_seq == 2001999


def test_set_position_unread_lowers_the_ceiling(pconn, iconn):
    """'unread' is an explicit denial, not a move backward: it must clear the watermark."""
    progress.set_position(pconn, iconn, "b1", status="finished")
    assert progress.get_progress(pconn, "b1").ceiling_seq > 0

    progress.set_position(pconn, iconn, "b1", status="unread")
    assert progress.get_progress(pconn, "b1").ceiling_seq == 0
    assert progress.readable_ranges(pconn, iconn) == []
