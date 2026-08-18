"""Tests for booklens.paths: directory layout and BOOKLENS_DATA_DIR honouring."""

import os

from booklens import db, paths


def test_data_dir_honours_env_var_at_call_time(tmp_path, monkeypatch):
    d1 = tmp_path / "first"
    monkeypatch.setenv("BOOKLENS_DATA_DIR", str(d1))
    assert paths.data_dir() == d1
    assert d1.is_dir()

    d2 = tmp_path / "second"
    monkeypatch.setenv("BOOKLENS_DATA_DIR", str(d2))
    assert paths.data_dir() == d2
    assert d2.is_dir()
    assert d1 != d2


def test_data_dir_falls_back_to_project_root_when_unset(tmp_path, monkeypatch):
    monkeypatch.delenv("BOOKLENS_DATA_DIR", raising=False)
    d = paths.data_dir()
    assert d.name == "data"
    assert (d.parent / "pyproject.toml").is_file()


def test_progress_and_index_db_paths(tmp_path, monkeypatch):
    monkeypatch.setenv("BOOKLENS_DATA_DIR", str(tmp_path))
    assert paths.progress_db_path() == tmp_path / "progress.db"
    assert paths.index_db_path() == tmp_path / "index.db"


def test_book_dir_named_by_book_id(tmp_path, monkeypatch):
    monkeypatch.setenv("BOOKLENS_DATA_DIR", str(tmp_path))
    d = paths.book_dir("red-rising")
    assert d == tmp_path / "books" / "red-rising"
    assert d.is_dir()


def test_digests_dir_nested_under_book_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("BOOKLENS_DATA_DIR", str(tmp_path))
    d = paths.digests_dir("red-rising")
    assert d == paths.book_dir("red-rising") / "digests"
    assert d.is_dir()


def test_source_file_path_none_when_no_epub_in_book_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("BOOKLENS_DATA_DIR", str(tmp_path))
    paths.book_dir("red-rising")  # created, but empty -- a CLI-ingested book
    assert paths.source_file_path("red-rising") is None


def test_source_file_path_finds_retained_epub(tmp_path, monkeypatch):
    monkeypatch.setenv("BOOKLENS_DATA_DIR", str(tmp_path))
    d = paths.book_dir("red-rising")
    epub = d / "Red Rising.epub"
    epub.write_bytes(b"fake epub bytes")
    assert paths.source_file_path("red-rising") == epub


def test_migrate_legacy_book_dirs_renames_and_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setenv("BOOKLENS_DATA_DIR", str(tmp_path))
    sha = "abcdef0123456789" + "f" * 48
    legacy_dir = tmp_path / "books" / sha[:16]
    legacy_dir.mkdir(parents=True)
    (legacy_dir / "meta.json").write_text("{}")

    iconn = db.connect_index(tmp_path / "index.db")
    iconn.execute(
        "INSERT INTO book(id, sha256, title, source_path, series_id, book_order, "
        "sequence_tier, label_tier, ingested_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("red-rising", sha, "Red Rising", "/somewhere/red-rising.epub", "red-rising", 1, "S1", "L1", "now"),
    )
    iconn.commit()

    moved = paths.migrate_legacy_book_dirs(iconn)
    new_dir = tmp_path / "books" / "red-rising"
    assert moved == [(str(legacy_dir), str(new_dir))]
    assert new_dir.is_dir()
    assert not legacy_dir.is_dir()
    assert (new_dir / "meta.json").is_file()

    # Idempotent: nothing left to rename.
    assert paths.migrate_legacy_book_dirs(iconn) == []


def test_migrate_legacy_book_dirs_never_clobbers_existing_destination(tmp_path, monkeypatch):
    monkeypatch.setenv("BOOKLENS_DATA_DIR", str(tmp_path))
    sha = "abcdef0123456789" + "f" * 48
    legacy_dir = tmp_path / "books" / sha[:16]
    legacy_dir.mkdir(parents=True)
    (legacy_dir / "marker.txt").write_text("legacy")

    new_dir = tmp_path / "books" / "red-rising"
    new_dir.mkdir(parents=True)
    (new_dir / "marker.txt").write_text("current")

    iconn = db.connect_index(tmp_path / "index.db")
    iconn.execute(
        "INSERT INTO book(id, sha256, title, source_path, series_id, book_order, "
        "sequence_tier, label_tier, ingested_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("red-rising", sha, "Red Rising", "/somewhere/red-rising.epub", "red-rising", 1, "S1", "L1", "now"),
    )
    iconn.commit()

    moved = paths.migrate_legacy_book_dirs(iconn)
    assert moved == []
    assert legacy_dir.is_dir()  # never deleted
    assert (new_dir / "marker.txt").read_text() == "current"  # never overwritten


def test_migrate_legacy_book_dirs_noop_without_book_table(tmp_path, monkeypatch):
    monkeypatch.setenv("BOOKLENS_DATA_DIR", str(tmp_path))
    import sqlite3

    raw = sqlite3.connect(str(tmp_path / "empty.db"))
    raw.row_factory = sqlite3.Row
    assert paths.migrate_legacy_book_dirs(raw) == []


def test_series_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("BOOKLENS_DATA_DIR", str(tmp_path))
    d = paths.series_dir()
    assert d == tmp_path / "series"
    assert d.is_dir()


def test_env_var_read_at_call_time_not_import_time(tmp_path, monkeypatch):
    # Simulate a test harness redirecting the env var *after* the module was
    # already imported elsewhere in the process (which conftest.py relies on).
    assert "booklens.paths" in list(__import__("sys").modules)
    new_dir = tmp_path / "redirected"
    monkeypatch.setenv("BOOKLENS_DATA_DIR", str(new_dir))
    assert paths.data_dir() == new_dir
