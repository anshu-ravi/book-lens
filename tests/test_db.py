"""Tests for booklens.db: schema DDL, global_seq math, and FTS5 sync triggers."""

import sqlite3

import pytest

from booklens import db


def test_global_seq_formula():
    assert db.global_seq(1, 0, 0) == 1_000_000
    assert db.global_seq(2, 78, 14) == 2_000_000 + 78_000 + 14
    assert db.global_seq(0, 0, 0) == 0


@pytest.mark.parametrize(
    "book_order,spine_idx,para_idx",
    [
        (-1, 0, 0),
        (0, -1, 0),
        (0, 0, -1),
        (0, 1000, 0),
        (0, 0, 1000),
        (0, 5000, 5000),
    ],
)
def test_global_seq_rejects_out_of_range(book_order, spine_idx, para_idx):
    with pytest.raises(ValueError):
        db.global_seq(book_order, spine_idx, para_idx)


def test_global_seq_accepts_boundary_values():
    assert db.global_seq(0, 999, 999) == 999_999


def _make_index_conn(tmp_path):
    return db.connect_index(tmp_path / "index.db")


def _make_progress_conn(tmp_path):
    return db.connect_progress(tmp_path / "progress.db")


def test_connect_index_sets_row_factory_and_foreign_keys(tmp_path):
    conn = _make_index_conn(tmp_path)
    assert conn.row_factory is sqlite3.Row
    fk = conn.execute("PRAGMA foreign_keys").fetchone()[0]
    assert fk == 1


def test_connect_progress_sets_row_factory_and_foreign_keys(tmp_path):
    conn = _make_progress_conn(tmp_path)
    assert conn.row_factory is sqlite3.Row
    fk = conn.execute("PRAGMA foreign_keys").fetchone()[0]
    assert fk == 1


def test_init_index_is_idempotent(tmp_path):
    conn = _make_index_conn(tmp_path)
    db.init_index(conn)
    db.init_index(conn)  # must not raise
    tables = {
        r["name"]
        for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert {"book", "chapter", "para"} <= tables


def test_init_progress_is_idempotent(tmp_path):
    conn = _make_progress_conn(tmp_path)
    db.init_progress(conn)
    db.init_progress(conn)  # must not raise
    tables = {
        r["name"]
        for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert {"book_progress", "setting"} <= tables


def _insert_book(conn, book_id="b1", series_id="s1", book_order=1):
    conn.execute(
        """
        INSERT INTO book(id, sha256, title, author, source_path, series_id,
                          book_order, sequence_tier, label_tier, ingested_at)
        VALUES (?, ?, 'Title', 'Author', '/x.epub', ?, ?, 'S1', 'L1', '2026-01-01')
        """,
        (book_id, f"sha-{book_id}", series_id, book_order),
    )
    conn.commit()


def test_para_fts_insert_sync(tmp_path):
    conn = _make_index_conn(tmp_path)
    _insert_book(conn)
    conn.execute(
        """
        INSERT INTO para(book_id, spine_idx, para_idx, global_seq, chapter_idx, chapter_label, text)
        VALUES ('b1', 0, 0, 1000000, 0, 'Chapter 1', 'the quick brown fox')
        """
    )
    conn.commit()
    hits = conn.execute("SELECT rowid FROM para_fts WHERE para_fts MATCH 'quick'").fetchall()
    assert len(hits) == 1


def test_para_fts_delete_sync(tmp_path):
    conn = _make_index_conn(tmp_path)
    _insert_book(conn)
    conn.execute(
        """
        INSERT INTO para(id, book_id, spine_idx, para_idx, global_seq, chapter_idx, chapter_label, text)
        VALUES (1, 'b1', 0, 0, 1000000, 0, 'Chapter 1', 'the quick brown fox')
        """
    )
    conn.commit()
    assert len(conn.execute("SELECT rowid FROM para_fts WHERE para_fts MATCH 'quick'").fetchall()) == 1

    conn.execute("DELETE FROM para WHERE id = 1")
    conn.commit()
    assert conn.execute("SELECT rowid FROM para_fts WHERE para_fts MATCH 'quick'").fetchall() == []


def test_para_fts_update_sync(tmp_path):
    conn = _make_index_conn(tmp_path)
    _insert_book(conn)
    conn.execute(
        """
        INSERT INTO para(id, book_id, spine_idx, para_idx, global_seq, chapter_idx, chapter_label, text)
        VALUES (1, 'b1', 0, 0, 1000000, 0, 'Chapter 1', 'the quick brown fox')
        """
    )
    conn.commit()

    conn.execute("UPDATE para SET text = 'a slow green turtle' WHERE id = 1")
    conn.commit()

    assert conn.execute("SELECT rowid FROM para_fts WHERE para_fts MATCH 'quick'").fetchall() == []
    assert len(conn.execute("SELECT rowid FROM para_fts WHERE para_fts MATCH 'turtle'").fetchall()) == 1


def test_para_book_id_foreign_key_cascade(tmp_path):
    conn = _make_index_conn(tmp_path)
    _insert_book(conn)
    conn.execute(
        """
        INSERT INTO para(id, book_id, spine_idx, para_idx, global_seq, chapter_idx, chapter_label, text)
        VALUES (1, 'b1', 0, 0, 1000000, 0, 'Chapter 1', 'hello world')
        """
    )
    conn.commit()
    conn.execute("DELETE FROM book WHERE id = 'b1'")
    conn.commit()
    assert conn.execute("SELECT * FROM para").fetchall() == []


def test_book_order_unique_within_series(tmp_path):
    conn = _make_index_conn(tmp_path)
    _insert_book(conn, book_id="b1", series_id="s1", book_order=1)
    with pytest.raises(sqlite3.IntegrityError):
        _insert_book(conn, book_id="b2", series_id="s1", book_order=1)


def test_para_global_seq_unique(tmp_path):
    conn = _make_index_conn(tmp_path)
    _insert_book(conn)
    conn.execute(
        """
        INSERT INTO para(book_id, spine_idx, para_idx, global_seq, chapter_idx, chapter_label, text)
        VALUES ('b1', 0, 0, 1000000, 0, 'Chapter 1', 'x')
        """
    )
    conn.commit()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """
            INSERT INTO para(book_id, spine_idx, para_idx, global_seq, chapter_idx, chapter_label, text)
            VALUES ('b1', 0, 1, 1000000, 0, 'Chapter 1', 'y')
            """
        )


def test_register_regexp(tmp_path):
    conn = _make_index_conn(tmp_path)
    db.register_regexp(conn)
    row = conn.execute("SELECT 'hello world' REGEXP 'wor.d' AS m").fetchone()
    assert row["m"] == 1
    row = conn.execute("SELECT 'hello world' REGEXP 'zzz' AS m").fetchone()
    assert row["m"] == 0


def test_register_regexp_bad_pattern_does_not_raise(tmp_path):
    conn = _make_index_conn(tmp_path)
    db.register_regexp(conn)
    row = conn.execute("SELECT 'hello world' REGEXP '(unclosed' AS m").fetchone()
    assert row["m"] == 0
