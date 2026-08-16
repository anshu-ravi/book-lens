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


# -- schema version guard (SCHEMA_VERSION=3: digest/entity tables) -----------


def test_v3_tables_exist_after_init(tmp_path):
    conn = _make_index_conn(tmp_path)
    tables = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"digest", "entity_node", "entity_edge", "entity_attr"} <= tables


def test_init_index_rejects_pre_v3_database(tmp_path):
    """A database already initialized under an older schema (has 'book' but
    lacks the digest/entity tables) must be rejected, not silently patched up."""
    path = tmp_path / "index.db"
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    # Hand-build a v2-shaped database: book/chapter/para with their v2 columns,
    # but none of the v3 digest/entity tables.
    conn.executescript(
        """
        CREATE TABLE book(
          id TEXT PRIMARY KEY, sha256 TEXT NOT NULL UNIQUE, title TEXT NOT NULL,
          author TEXT, source_path TEXT NOT NULL, series_id TEXT NOT NULL,
          book_order INTEGER NOT NULL, sequence_tier TEXT NOT NULL, label_tier TEXT NOT NULL,
          ingested_at TEXT NOT NULL, UNIQUE(series_id, book_order)
        );
        CREATE TABLE chapter(
          book_id TEXT NOT NULL, chapter_idx INTEGER NOT NULL, label TEXT NOT NULL,
          part_label TEXT, start_seq INTEGER NOT NULL, end_seq INTEGER NOT NULL,
          kind TEXT NOT NULL DEFAULT 'body', PRIMARY KEY(book_id, chapter_idx)
        );
        CREATE TABLE para(
          id INTEGER PRIMARY KEY, book_id TEXT NOT NULL, spine_idx INTEGER NOT NULL,
          para_idx INTEGER NOT NULL, global_seq INTEGER NOT NULL UNIQUE,
          chapter_idx INTEGER NOT NULL, chapter_label TEXT NOT NULL, text TEXT NOT NULL,
          kind TEXT NOT NULL DEFAULT 'body'
        );
        """
    )
    conn.commit()
    conn.close()

    reopened = sqlite3.connect(str(path))
    reopened.row_factory = sqlite3.Row
    with pytest.raises(db.SchemaVersionError, match="delete"):
        db.init_index(reopened)


def test_init_index_on_fresh_database_never_raises(tmp_path):
    """A brand-new, never-initialized file is not 'stale' -- it just gets the
    current schema, v3 tables included."""
    conn = _make_index_conn(tmp_path)  # must not raise
    tables = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"book", "digest", "entity_node", "entity_edge", "entity_attr"} <= tables


# -- schema version guard (SCHEMA_VERSION=5: para.global_seq scoped per book) -


def test_para_unique_is_scoped_per_book_not_global(tmp_path):
    """Two books can now share a global_seq value; only (book_id, global_seq) is unique."""
    conn = _make_index_conn(tmp_path)
    conn.execute(
        """
        INSERT INTO book(id, sha256, title, author, source_path, series_id,
                          book_order, sequence_tier, label_tier, ingested_at)
        VALUES ('a1', 'sha-a', 'A', NULL, '/a.epub', 'sA', 1, 'S1', 'L1', '2026-01-01')
        """
    )
    conn.execute(
        """
        INSERT INTO book(id, sha256, title, author, source_path, series_id,
                          book_order, sequence_tier, label_tier, ingested_at)
        VALUES ('b1', 'sha-b', 'B', NULL, '/b.epub', 'sB', 1, 'S1', 'L1', '2026-01-01')
        """
    )
    for book_id in ("a1", "b1"):
        conn.execute(
            "INSERT INTO para(book_id, spine_idx, para_idx, global_seq, chapter_idx, "
            "chapter_label, text) VALUES (?, 0, 0, 1000000, 0, 'Chapter 0', 'text')",
            (book_id,),
        )
    conn.commit()  # must not raise: both books legitimately share global_seq=1_000_000

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO para(book_id, spine_idx, para_idx, global_seq, chapter_idx, "
            "chapter_label, text) VALUES ('a1', 0, 1, 1000000, 0, 'Chapter 0', 'dup')"
        )


def test_init_index_rejects_pre_v5_global_seq_unique(tmp_path):
    """A database built under the old column-level UNIQUE on para.global_seq
    must be rejected with a message pointing at `booklens reindex`."""
    path = tmp_path / "index.db"
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(
        """
        CREATE TABLE book(
          id TEXT PRIMARY KEY, sha256 TEXT NOT NULL UNIQUE, title TEXT NOT NULL,
          author TEXT, source_path TEXT NOT NULL, series_id TEXT NOT NULL,
          book_order INTEGER NOT NULL, sequence_tier TEXT NOT NULL, label_tier TEXT NOT NULL,
          ingested_at TEXT NOT NULL, UNIQUE(series_id, book_order)
        );
        CREATE TABLE chapter(
          book_id TEXT NOT NULL, chapter_idx INTEGER NOT NULL, label TEXT NOT NULL,
          part_label TEXT, start_seq INTEGER NOT NULL, end_seq INTEGER NOT NULL,
          kind TEXT NOT NULL DEFAULT 'body'
              CHECK(kind IN ('body', 'reference', 'boilerplate', 'excerpt')),
          PRIMARY KEY(book_id, chapter_idx)
        );
        CREATE TABLE para(
          id INTEGER PRIMARY KEY, book_id TEXT NOT NULL, spine_idx INTEGER NOT NULL,
          para_idx INTEGER NOT NULL, global_seq INTEGER NOT NULL UNIQUE,
          chapter_idx INTEGER NOT NULL, chapter_label TEXT NOT NULL, text TEXT NOT NULL,
          kind TEXT NOT NULL DEFAULT 'body'
              CHECK(kind IN ('body', 'reference', 'boilerplate', 'excerpt'))
        );
        CREATE TABLE digest(id INTEGER PRIMARY KEY);
        CREATE TABLE entity_node(id INTEGER PRIMARY KEY);
        CREATE TABLE entity_edge(id INTEGER PRIMARY KEY);
        CREATE TABLE entity_attr(id INTEGER PRIMARY KEY);
        """
    )
    conn.commit()
    conn.close()

    reopened = sqlite3.connect(str(path))
    reopened.row_factory = sqlite3.Row
    with pytest.raises(db.SchemaVersionError, match="reindex"):
        db.init_index(reopened)


# -- additive migration (SCHEMA_VERSION=6: book.standalone) -------------------


def test_book_standalone_column_migrates_in_place(tmp_path):
    """A database predating `book.standalone` gains it on the next connect,
    existing rows default to 0, and no SchemaVersionError is raised."""
    db_path = tmp_path / "index.db"
    conn = _make_index_conn(tmp_path)
    conn.execute(
        """
        INSERT INTO book(id, sha256, title, author, source_path, series_id,
                          book_order, sequence_tier, label_tier, ingested_at)
        VALUES ('b1', 'deadbeef', 'A Book', NULL, '/tmp/a.epub', 's1', 1, 'L1', 'L1', 'now')
        """
    )
    conn.commit()
    # Simulate a pre-migration database by dropping the column back out.
    conn.execute("ALTER TABLE book DROP COLUMN standalone")
    conn.commit()
    conn.close()

    reopened = sqlite3.connect(str(db_path))
    reopened.row_factory = sqlite3.Row
    db.init_index(reopened)  # must not raise SchemaVersionError

    cols = {r["name"] for r in reopened.execute("PRAGMA table_info(book)")}
    assert "standalone" in cols
    row = reopened.execute("SELECT standalone FROM book WHERE id = 'b1'").fetchone()
    assert row["standalone"] == 0
