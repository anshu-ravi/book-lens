"""Tests for booklens.reseq: moving a book to a new series position in place."""

from __future__ import annotations

import pytest

from booklens import db, reseq


def _insert_book(iconn, book_id, series_id, book_order):
    iconn.execute(
        """
        INSERT INTO book(id, sha256, title, author, source_path, series_id,
                          book_order, sequence_tier, label_tier, ingested_at)
        VALUES (?, ?, 'Title', 'Author', '/x.epub', ?, ?, 'S1', 'L1', '2026-01-01')
        """,
        (book_id, f"sha-{book_id}", series_id, book_order),
    )


def _insert_chapter(iconn, book_id, chapter_idx, book_order, spine_idx, num_paras):
    seqs = []
    for p in range(num_paras):
        gseq = db.global_seq(book_order, spine_idx, p)
        iconn.execute(
            """
            INSERT INTO para(book_id, spine_idx, para_idx, global_seq, chapter_idx,
                              chapter_label, text, kind)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'body')
            """,
            (book_id, spine_idx, p, gseq, chapter_idx, f"Chapter {chapter_idx}", f"para {p}"),
        )
        seqs.append(gseq)
    iconn.execute(
        """
        INSERT INTO chapter(book_id, chapter_idx, label, part_label, start_seq, end_seq, kind)
        VALUES (?, ?, ?, NULL, ?, ?, 'body')
        """,
        (book_id, chapter_idx, f"Chapter {chapter_idx}", seqs[0], seqs[-1]),
    )
    return seqs[0], seqs[-1]


@pytest.fixture
def iconn(tmp_path):
    return db.connect_index(tmp_path / "index.db")


@pytest.fixture
def pconn(tmp_path):
    return db.connect_progress(tmp_path / "progress.db")


def _build_book(iconn, book_id, book_order, num_chapters=2, paras_per_chapter=3):
    _insert_book(iconn, book_id, "s1", book_order)
    spans = [
        _insert_chapter(iconn, book_id, ch, book_order, ch, paras_per_chapter)
        for ch in range(num_chapters)
    ]
    iconn.commit()
    return spans


def test_rebase_shifts_para_and_chapter_seq_by_book_stride_delta(iconn, pconn):
    _build_book(iconn, "b1", 1)
    before = {
        r["id"]: r["global_seq"] for r in iconn.execute("SELECT id, global_seq FROM para WHERE book_id='b1'")
    }
    before_chapters = {
        r["chapter_idx"]: (r["start_seq"], r["end_seq"])
        for r in iconn.execute("SELECT chapter_idx, start_seq, end_seq FROM chapter WHERE book_id='b1'")
    }

    delta = reseq.rebase_book_order(iconn, pconn, "b1", 3)

    assert delta == 2 * db.BOOK_STRIDE

    after = {
        r["id"]: r["global_seq"] for r in iconn.execute("SELECT id, global_seq FROM para WHERE book_id='b1'")
    }
    for pid, old_seq in before.items():
        assert after[pid] == old_seq + delta

    after_chapters = {
        r["chapter_idx"]: (r["start_seq"], r["end_seq"])
        for r in iconn.execute("SELECT chapter_idx, start_seq, end_seq FROM chapter WHERE book_id='b1'")
    }
    for idx, (old_start, old_end) in before_chapters.items():
        new_start, new_end = after_chapters[idx]
        assert (new_start, new_end) == (old_start + delta, old_end + delta)

    book_order = iconn.execute("SELECT book_order FROM book WHERE id='b1'").fetchone()["book_order"]
    assert book_order == 3


def test_rebase_preserves_relative_order_within_the_book(iconn, pconn):
    _build_book(iconn, "b1", 1, num_chapters=3, paras_per_chapter=4)
    before_order = [
        r["id"]
        for r in iconn.execute("SELECT id FROM para WHERE book_id='b1' ORDER BY global_seq")
    ]

    reseq.rebase_book_order(iconn, pconn, "b1", 5)

    after_order = [
        r["id"]
        for r in iconn.execute("SELECT id FROM para WHERE book_id='b1' ORDER BY global_seq")
    ]
    assert after_order == before_order


def test_rebase_moves_the_ceiling_with_the_book(iconn, pconn):
    _build_book(iconn, "b1", 1)
    old_ceiling = db.global_seq(1, 0, 2)
    pconn.execute(
        "INSERT INTO book_progress(book_id, status, position_chapter_idx, ceiling_seq, updated_at) "
        "VALUES ('b1', 'reading', 0, ?, 'now')",
        (old_ceiling,),
    )
    pconn.commit()

    delta = reseq.rebase_book_order(iconn, pconn, "b1", 4)

    new_ceiling = pconn.execute(
        "SELECT ceiling_seq FROM book_progress WHERE book_id='b1'"
    ).fetchone()["ceiling_seq"]
    assert new_ceiling == old_ceiling + delta


def test_rebase_leaves_an_unread_zero_ceiling_at_zero(iconn, pconn):
    _build_book(iconn, "b1", 1)
    pconn.execute(
        "INSERT INTO book_progress(book_id, status, position_chapter_idx, ceiling_seq, updated_at) "
        "VALUES ('b1', 'unread', NULL, 0, 'now')"
    )
    pconn.commit()

    reseq.rebase_book_order(iconn, pconn, "b1", 4)

    ceiling = pconn.execute(
        "SELECT ceiling_seq FROM book_progress WHERE book_id='b1'"
    ).fetchone()["ceiling_seq"]
    assert ceiling == 0


def test_rebase_noop_move_returns_zero_and_changes_nothing(iconn, pconn):
    _build_book(iconn, "b1", 1)
    before = {
        r["id"]: r["global_seq"] for r in iconn.execute("SELECT id, global_seq FROM para WHERE book_id='b1'")
    }

    delta = reseq.rebase_book_order(iconn, pconn, "b1", 1)

    assert delta == 0
    after = {
        r["id"]: r["global_seq"] for r in iconn.execute("SELECT id, global_seq FROM para WHERE book_id='b1'")
    }
    assert after == before


def test_rebase_unknown_book_raises(iconn, pconn):
    with pytest.raises(ValueError):
        reseq.rebase_book_order(iconn, pconn, "nope", 2)


def test_rebase_rejects_negative_book_order(iconn, pconn):
    _build_book(iconn, "b1", 1)
    with pytest.raises(ValueError):
        reseq.rebase_book_order(iconn, pconn, "b1", -1)


def test_rebase_shifts_digest_and_entity_rows(iconn, pconn):
    _build_book(iconn, "b1", 1)
    start_seq = db.global_seq(1, 0, 0)
    end_seq = db.global_seq(1, 0, 2)
    iconn.execute(
        """
        INSERT INTO digest(book_id, level, chapter_idx, source_start_seq, source_end_seq,
                            path, generator, prompt_hash, schema_version, created_at)
        VALUES ('b1', 'chapter', 0, ?, ?, 'p', 'g', 'h', 1, 'now')
        """,
        (start_seq, end_seq),
    )
    cite_para_id = iconn.execute("SELECT id FROM para WHERE book_id='b1' LIMIT 1").fetchone()["id"]
    iconn.execute(
        """
        INSERT INTO entity_node(id, book_id, designator, node_kind, first_seq, cite_para_id)
        VALUES (1, 'b1', 'Someone', 'named', ?, ?)
        """,
        (start_seq, cite_para_id),
    )
    iconn.execute(
        "INSERT INTO entity_edge(id, src_node_id, dst_node_id, edge_type, revealed_at_seq) "
        "VALUES (1, 1, 1, 'stated', ?)",
        (end_seq,),
    )
    iconn.execute(
        "INSERT INTO entity_attr(id, node_id, attr_kind, value, first_seq) VALUES (1, 1, 'k', 'v', ?)",
        (start_seq,),
    )
    iconn.commit()

    delta = reseq.rebase_book_order(iconn, pconn, "b1", 2)

    digest = iconn.execute(
        "SELECT source_start_seq, source_end_seq FROM digest WHERE book_id='b1'"
    ).fetchone()
    assert (digest["source_start_seq"], digest["source_end_seq"]) == (start_seq + delta, end_seq + delta)

    node = iconn.execute("SELECT first_seq FROM entity_node WHERE id=1").fetchone()
    assert node["first_seq"] == start_seq + delta

    edge = iconn.execute("SELECT revealed_at_seq FROM entity_edge WHERE id=1").fetchone()
    assert edge["revealed_at_seq"] == end_seq + delta

    attr = iconn.execute("SELECT first_seq FROM entity_attr WHERE id=1").fetchone()
    assert attr["first_seq"] == start_seq + delta
