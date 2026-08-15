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


def test_readable_ranges_merges_and_sorts(pconn, iconn):
    progress.set_position(pconn, iconn, "b2", status="finished")
    progress.set_position(pconn, iconn, "b1", status="reading", chapter_idx=0)
    ranges = progress.readable_ranges(pconn, iconn)
    # b1 ceiling 1000999, b2 ceiling 2001999 -> two disjoint [0, ceiling] ranges
    # that merge into one because both start at 0.
    assert ranges == [(0, 2001999)]


def test_readable_ranges_empty_when_nothing_read(pconn, iconn):
    assert progress.readable_ranges(pconn, iconn) == []


def test_readable_ranges_excludes_unread_zero_ceiling_books(pconn, iconn):
    progress.set_position(pconn, iconn, "b1", status="unread")
    assert progress.readable_ranges(pconn, iconn) == []
