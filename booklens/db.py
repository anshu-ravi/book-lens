"""SQLite storage: `progress.db` holds user state, `index.db` derived text.

The split matters — `index.db` is a rebuildable cache, `progress.db` is not.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from booklens import paths

SCHEMA_VERSION = 2

_MAX_SPINE_IDX = 1000
_MAX_PARA_IDX = 1000


def global_seq(book_order: int, spine_idx: int, para_idx: int) -> int:
    """Position a paragraph in the single total order spanning the whole series.

    Refuses inputs that would overflow their digit range and collide with a
    neighbouring document, rather than silently producing a wrong order.
    """
    if book_order < 0 or spine_idx < 0 or para_idx < 0:
        raise ValueError(
            f"global_seq arguments must be non-negative: "
            f"book_order={book_order}, spine_idx={spine_idx}, para_idx={para_idx}"
        )
    if spine_idx >= _MAX_SPINE_IDX:
        raise ValueError(f"spine_idx {spine_idx} out of range (must be < {_MAX_SPINE_IDX})")
    if para_idx >= _MAX_PARA_IDX:
        raise ValueError(f"para_idx {para_idx} out of range (must be < {_MAX_PARA_IDX})")
    return book_order * 1_000_000 + spine_idx * 1000 + para_idx


def _base_connect(path: Path) -> sqlite3.Connection:
    """Open a connection with the settings every caller depends on."""
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def connect_index(path: Path | None = None) -> sqlite3.Connection:
    """Open the derived-text database, creating it if needed."""
    p = path if path is not None else paths.index_db_path()
    conn = _base_connect(p)
    init_index(conn)
    return conn


def connect_progress(path: Path | None = None) -> sqlite3.Connection:
    """Open the user-state database, creating it if needed."""
    p = path if path is not None else paths.progress_db_path()
    conn = _base_connect(p)
    init_progress(conn)
    return conn


_INDEX_DDL = """
CREATE TABLE IF NOT EXISTS book(
  id           TEXT PRIMARY KEY,
  sha256       TEXT NOT NULL UNIQUE,
  title        TEXT NOT NULL,
  author       TEXT,
  source_path  TEXT NOT NULL,
  series_id    TEXT NOT NULL,
  book_order   INTEGER NOT NULL,
  sequence_tier TEXT NOT NULL,
  label_tier   TEXT NOT NULL,
  ingested_at  TEXT NOT NULL,
  UNIQUE(series_id, book_order)
);

CREATE TABLE IF NOT EXISTS chapter(
  book_id     TEXT NOT NULL REFERENCES book(id) ON DELETE CASCADE,
  chapter_idx INTEGER NOT NULL,
  label       TEXT NOT NULL,
  part_label  TEXT,
  start_seq   INTEGER NOT NULL,
  end_seq     INTEGER NOT NULL,
  kind        TEXT NOT NULL DEFAULT 'body' CHECK(kind IN ('body','front','excerpt')),
  PRIMARY KEY(book_id, chapter_idx)
);

CREATE TABLE IF NOT EXISTS para(
  id            INTEGER PRIMARY KEY,
  book_id       TEXT NOT NULL REFERENCES book(id) ON DELETE CASCADE,
  spine_idx     INTEGER NOT NULL,
  para_idx      INTEGER NOT NULL,
  global_seq    INTEGER NOT NULL UNIQUE,
  chapter_idx   INTEGER NOT NULL,
  chapter_label TEXT NOT NULL,
  text          TEXT NOT NULL,
  kind          TEXT NOT NULL DEFAULT 'body' CHECK(kind IN ('body','front','excerpt'))
);

CREATE VIRTUAL TABLE IF NOT EXISTS para_fts USING fts5(
  text, content='para', content_rowid='id'
);

CREATE INDEX IF NOT EXISTS idx_para_seq ON para(global_seq);
CREATE INDEX IF NOT EXISTS idx_para_book_ch ON para(book_id, chapter_idx);
CREATE INDEX IF NOT EXISTS idx_chapter_seq ON chapter(start_seq, end_seq);
CREATE INDEX IF NOT EXISTS idx_para_kind_seq ON para(kind, global_seq);

CREATE TRIGGER IF NOT EXISTS para_ai AFTER INSERT ON para BEGIN
  INSERT INTO para_fts(rowid, text) VALUES (new.id, new.text);
END;

CREATE TRIGGER IF NOT EXISTS para_ad AFTER DELETE ON para BEGIN
  INSERT INTO para_fts(para_fts, rowid, text) VALUES ('delete', old.id, old.text);
END;

CREATE TRIGGER IF NOT EXISTS para_au AFTER UPDATE ON para BEGIN
  INSERT INTO para_fts(para_fts, rowid, text) VALUES ('delete', old.id, old.text);
  INSERT INTO para_fts(rowid, text) VALUES (new.id, new.text);
END;
"""

_PROGRESS_DDL = """
CREATE TABLE IF NOT EXISTS book_progress(
  book_id   TEXT PRIMARY KEY,
  status    TEXT NOT NULL CHECK(status IN ('unread','reading','finished')),
  position_chapter_idx INTEGER,
  ceiling_seq INTEGER NOT NULL DEFAULT 0,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS setting(
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
"""


class SchemaVersionError(Exception):
    """index.db was built against an older schema and cannot be reused."""


def _check_schema_compat(conn: sqlite3.Connection) -> None:
    """Reject an index.db predating the current schema.

    `CREATE TABLE IF NOT EXISTS` skips existing tables, so a stale one would
    otherwise survive init untouched and missing its new columns.
    """
    tables = {
        r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    for table, required_cols in (("chapter", {"kind"}), ("para", {"kind"})):
        if table not in tables:
            continue
        cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        missing = required_cols - cols
        if missing:
            raise SchemaVersionError(
                f"index.db has an outdated schema: table {table!r} is missing "
                f"column(s) {sorted(missing)} required by SCHEMA_VERSION={SCHEMA_VERSION}. "
                "index.db is a rebuildable cache, not user data -- delete it "
                "(and its digests/ directory) and re-run ingest for every book."
            )


def init_index(conn: sqlite3.Connection) -> None:
    """Create the index tables if absent, refusing an outdated database."""
    _check_schema_compat(conn)
    conn.executescript(_INDEX_DDL)
    conn.commit()


def init_progress(conn: sqlite3.Connection) -> None:
    """Create the user-state tables if absent."""
    conn.executescript(_PROGRESS_DDL)
    conn.commit()


def _regexp(pattern: str, value: str | None) -> bool:
    """Backs the REGEXP operator; a bad pattern matches nothing rather than raising."""
    if value is None:
        return False
    try:
        return re.search(pattern, value) is not None
    except re.error:
        return False


def register_regexp(conn: sqlite3.Connection) -> None:
    """Make `text REGEXP ?` available on this connection."""
    conn.create_function("REGEXP", 2, _regexp)
