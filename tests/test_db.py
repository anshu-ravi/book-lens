"""Tests for booklens.db: schema DDL, global_seq math, and FTS5 sync triggers."""

import sqlite3

import pytest

from booklens import db


def test_global_seq_formula():
    assert db.global_seq(1, 0, 0) == db.BOOK_STRIDE
    assert db.global_seq(2, 78, 14) == 2 * db.BOOK_STRIDE + 78 * db.SPINE_STRIDE + 14
    assert db.global_seq(0, 0, 0) == 0


@pytest.mark.parametrize(
    "book_order,spine_idx,para_idx",
    [
        (-1, 0, 0),
        (0, -1, 0),
        (0, 0, -1),
        (0, db.MAX_SPINE_IDX, 0),
        (0, 0, db.MAX_PARA_IDX),
        (0, db.MAX_SPINE_IDX * 2, db.MAX_PARA_IDX * 2),
    ],
)
def test_global_seq_rejects_out_of_range(book_order, spine_idx, para_idx):
    with pytest.raises(ValueError):
        db.global_seq(book_order, spine_idx, para_idx)


def test_global_seq_accepts_a_thousand_paragraphs_in_one_spine_document():
    """A single spine document with 1000+ paragraphs is ordinary; the widened
    layout must not collide on it the way the old 1000/1000 layout did."""
    assert db.global_seq(0, 5, 1000) == 5 * db.SPINE_STRIDE + 1000
    assert db.global_seq(0, 1000, 5) == 1000 * db.SPINE_STRIDE + 5


def test_global_seq_accepts_boundary_values():
    assert db.global_seq(0, db.MAX_SPINE_IDX - 1, db.MAX_PARA_IDX - 1) == (
        (db.MAX_SPINE_IDX - 1) * db.SPINE_STRIDE + (db.MAX_PARA_IDX - 1)
    )


def test_book_floor_seq():
    assert db.book_floor_seq(0) == 0
    assert db.book_floor_seq(1) == db.BOOK_STRIDE
    assert db.book_floor_seq(3) == 3 * db.BOOK_STRIDE


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
        "INSERT INTO para(book_id, spine_idx, para_idx, global_seq, chapter_idx, chapter_label, text) "
        "VALUES ('b1', 0, 0, ?, 0, 'Chapter 1', 'the quick brown fox')",
        (db.global_seq(1, 0, 0),),
    )
    conn.commit()
    hits = conn.execute("SELECT rowid FROM para_fts WHERE para_fts MATCH 'quick'").fetchall()
    assert len(hits) == 1


def test_para_fts_delete_sync(tmp_path):
    conn = _make_index_conn(tmp_path)
    _insert_book(conn)
    conn.execute(
        "INSERT INTO para(id, book_id, spine_idx, para_idx, global_seq, chapter_idx, chapter_label, text) "
        "VALUES (1, 'b1', 0, 0, ?, 0, 'Chapter 1', 'the quick brown fox')",
        (db.global_seq(1, 0, 0),),
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
        "INSERT INTO para(id, book_id, spine_idx, para_idx, global_seq, chapter_idx, chapter_label, text) "
        "VALUES (1, 'b1', 0, 0, ?, 0, 'Chapter 1', 'the quick brown fox')",
        (db.global_seq(1, 0, 0),),
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
        "INSERT INTO para(id, book_id, spine_idx, para_idx, global_seq, chapter_idx, chapter_label, text) "
        "VALUES (1, 'b1', 0, 0, ?, 0, 'Chapter 1', 'hello world')",
        (db.global_seq(1, 0, 0),),
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
        "INSERT INTO para(book_id, spine_idx, para_idx, global_seq, chapter_idx, chapter_label, text) "
        "VALUES ('b1', 0, 0, ?, 0, 'Chapter 1', 'x')",
        (db.global_seq(1, 0, 0),),
    )
    conn.commit()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO para(book_id, spine_idx, para_idx, global_seq, chapter_idx, chapter_label, text) "
            "VALUES ('b1', 0, 1, ?, 0, 'Chapter 1', 'y')",
            (db.global_seq(1, 0, 0),),
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
    shared_seq = db.global_seq(1, 0, 0)
    for book_id in ("a1", "b1"):
        conn.execute(
            "INSERT INTO para(book_id, spine_idx, para_idx, global_seq, chapter_idx, "
            "chapter_label, text) VALUES (?, 0, 0, ?, 0, 'Chapter 0', 'text')",
            (book_id, shared_seq),
        )
    conn.commit()  # must not raise: both books legitimately share the same global_seq

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO para(book_id, spine_idx, para_idx, global_seq, chapter_idx, "
            "chapter_label, text) VALUES ('a1', 0, 1, ?, 0, 'Chapter 0', 'dup')",
            (shared_seq,),
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


# -- seq layout migration (SCHEMA_VERSION=7: widened from 1000/1000) ----------


def _legacy_seq(book_order: int, spine_idx: int, para_idx: int) -> int:
    """The old 1000/1000-layout formula, reconstructed for test fixtures only."""
    return book_order * 1_000_000 + spine_idx * 1000 + para_idx


def test_index_seq_layout_migrates_in_place(tmp_path):
    """A database written under the old 1000/1000 layout (user_version 0) is
    rescaled to the new layout on the next connect, exactly and idempotently."""
    db_path = tmp_path / "index.db"
    raw = sqlite3.connect(str(db_path))
    raw.row_factory = sqlite3.Row
    raw.execute("PRAGMA foreign_keys = ON")
    raw.executescript(db._INDEX_DDL)
    raw.execute(
        """
        INSERT INTO book(id, sha256, title, author, source_path, series_id,
                          book_order, sequence_tier, label_tier, ingested_at)
        VALUES ('b1', 'sha-b1', 'A Book', NULL, '/a.epub', 's1', 2, 'L1', 'L1', 'now')
        """
    )
    # Two paragraphs, in reading order, with legacy-layout seq values.
    raw.execute(
        "INSERT INTO para(id, book_id, spine_idx, para_idx, global_seq, chapter_idx, "
        "chapter_label, text) VALUES (1, 'b1', 0, 0, ?, 0, 'Chapter 1', 'first paragraph')",
        (_legacy_seq(2, 0, 0),),
    )
    raw.execute(
        "INSERT INTO para(id, book_id, spine_idx, para_idx, global_seq, chapter_idx, "
        "chapter_label, text) VALUES (2, 'b1', 0, 1, ?, 0, 'Chapter 1', 'second paragraph')",
        (_legacy_seq(2, 0, 1),),
    )
    raw.execute(
        "INSERT INTO chapter(book_id, chapter_idx, label, start_seq, end_seq) "
        "VALUES ('b1', 0, 'Chapter 1', ?, ?)",
        (_legacy_seq(2, 0, 0), _legacy_seq(2, 0, 1)),
    )
    raw.execute(
        "INSERT INTO digest(book_id, level, chapter_idx, source_start_seq, source_end_seq, "
        "path, generator, prompt_hash, schema_version, created_at) "
        "VALUES ('b1', 'chapter', 0, ?, ?, 'p', 'g', 'h', 1, 'now')",
        (_legacy_seq(2, 0, 0), _legacy_seq(2, 0, 1)),
    )
    raw.execute(
        "INSERT INTO entity_node(id, book_id, designator, node_kind, first_seq, cite_para_id) "
        "VALUES (1, 'b1', 'Someone', 'named', ?, 1)",
        (_legacy_seq(2, 0, 0),),
    )
    raw.execute(
        "INSERT INTO entity_edge(id, src_node_id, dst_node_id, edge_type, revealed_at_seq) "
        "VALUES (1, 1, 1, 'stated', ?)",
        (_legacy_seq(2, 0, 1),),
    )
    raw.execute(
        "INSERT INTO entity_attr(id, node_id, attr_kind, value, first_seq) "
        "VALUES (1, 1, 'k', 'v', ?)",
        (_legacy_seq(2, 0, 0),),
    )
    assert raw.execute("PRAGMA user_version").fetchone()[0] == 0
    raw.commit()
    raw.close()

    conn = db.connect_index(db_path)

    expected_first = db.global_seq(2, 0, 0)
    expected_second = db.global_seq(2, 0, 1)

    paras = {
        r["id"]: r["global_seq"]
        for r in conn.execute("SELECT id, global_seq FROM para ORDER BY id")
    }
    assert paras == {1: expected_first, 2: expected_second}
    # Ordering is preserved through the rescale.
    assert paras[1] < paras[2]

    chapter = conn.execute("SELECT start_seq, end_seq FROM chapter WHERE book_id = 'b1'").fetchone()
    assert (chapter["start_seq"], chapter["end_seq"]) == (expected_first, expected_second)

    digest = conn.execute(
        "SELECT source_start_seq, source_end_seq FROM digest WHERE book_id = 'b1'"
    ).fetchone()
    assert (digest["source_start_seq"], digest["source_end_seq"]) == (expected_first, expected_second)

    node = conn.execute("SELECT first_seq FROM entity_node WHERE id = 1").fetchone()
    assert node["first_seq"] == expected_first

    edge = conn.execute("SELECT revealed_at_seq FROM entity_edge WHERE id = 1").fetchone()
    assert edge["revealed_at_seq"] == expected_second

    attr = conn.execute("SELECT first_seq FROM entity_attr WHERE id = 1").fetchone()
    assert attr["first_seq"] == expected_first

    assert conn.execute("PRAGMA user_version").fetchone()[0] == 7

    # FTS still finds the migrated rows -- the UPDATE trigger fired correctly.
    hits = conn.execute("SELECT rowid FROM para_fts WHERE para_fts MATCH 'first'").fetchall()
    assert len(hits) == 1

    conn.close()

    # A second reopen is a no-op: nothing changes, nothing raises.
    reopened = db.connect_index(db_path)
    paras_again = {
        r["id"]: r["global_seq"]
        for r in reopened.execute("SELECT id, global_seq FROM para ORDER BY id")
    }
    assert paras_again == paras
    assert reopened.execute("PRAGMA user_version").fetchone()[0] == 7


def test_progress_seq_layout_migrates_in_place(tmp_path):
    """book_progress.ceiling_seq is rescaled the same way; a 0 (unread) ceiling
    is left untouched by the migration."""
    db_path = tmp_path / "progress.db"
    raw = sqlite3.connect(str(db_path))
    raw.row_factory = sqlite3.Row
    raw.execute("PRAGMA foreign_keys = ON")
    raw.executescript(db._PROGRESS_DDL)
    raw.execute(
        "INSERT INTO book_progress(book_id, status, position_chapter_idx, ceiling_seq, updated_at) "
        "VALUES ('b1', 'reading', 0, ?, 'now')",
        (_legacy_seq(2, 0, 1),),
    )
    raw.execute(
        "INSERT INTO book_progress(book_id, status, position_chapter_idx, ceiling_seq, updated_at) "
        "VALUES ('b2', 'unread', NULL, 0, 'now')"
    )
    raw.commit()
    raw.close()

    conn = db.connect_progress(db_path)

    b1 = conn.execute("SELECT ceiling_seq FROM book_progress WHERE book_id = 'b1'").fetchone()
    assert b1["ceiling_seq"] == db.global_seq(2, 0, 1)

    b2 = conn.execute("SELECT ceiling_seq FROM book_progress WHERE book_id = 'b2'").fetchone()
    assert b2["ceiling_seq"] == 0  # unread stays 0, not rescaled

    assert conn.execute("PRAGMA user_version").fetchone()[0] == 7

    conn.close()
    reopened = db.connect_progress(db_path)
    b1_again = reopened.execute("SELECT ceiling_seq FROM book_progress WHERE book_id = 'b1'").fetchone()
    assert b1_again["ceiling_seq"] == db.global_seq(2, 0, 1)
