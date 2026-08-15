"""Tests for booklens.paths: directory layout and BOOKLENS_DATA_DIR honouring."""

import os

from booklens import paths


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


def test_book_dir_uses_first_16_chars_of_sha256(tmp_path, monkeypatch):
    monkeypatch.setenv("BOOKLENS_DATA_DIR", str(tmp_path))
    sha = "abcdef0123456789" + "f" * 48
    d = paths.book_dir(sha)
    assert d == tmp_path / "books" / sha[:16]
    assert d.is_dir()


def test_digests_dir_nested_under_book_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("BOOKLENS_DATA_DIR", str(tmp_path))
    sha = "0" * 64
    d = paths.digests_dir(sha)
    assert d == paths.book_dir(sha) / "digests"
    assert d.is_dir()


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
