"""Filesystem layout for generated data, all of it under `./data/`.

`BOOKLENS_DATA_DIR` redirects it and is read at call time, so tests can isolate.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path


def _project_root() -> Path:
    """Walk up from this file to find the directory containing pyproject.toml."""
    here = Path(__file__).resolve()
    for candidate in (here, *here.parents):
        if (candidate / "pyproject.toml").is_file():
            return candidate
    raise RuntimeError(
        f"could not locate project root (pyproject.toml) walking up from {here}"
    )


def data_dir() -> Path:
    """Root of all generated state, created on first use."""
    override = os.environ.get("BOOKLENS_DATA_DIR")
    d = Path(override) if override else _project_root() / "data"
    d.mkdir(parents=True, exist_ok=True)
    return d


def progress_db_path() -> Path:
    """User state ONLY -- precious, never rebuild-and-discard."""
    return data_dir() / "progress.db"


def index_db_path() -> Path:
    """Derived state -- a rebuildable cache."""
    return data_dir() / "index.db"


def book_dir(book_id: str) -> Path:
    """Per-book generated state, keyed by book id so the directory is readable.

    The hash lives in the database (`book.sha256`), not in this path -- it is
    the content-to-book map, not a filename.
    """
    d = data_dir() / "books" / book_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def cover_path(book_id: str) -> Path | None:
    """The book's stored cover file, whatever its extension, or None if it has none."""
    matches = sorted(book_dir(book_id).glob("cover.*"))
    return matches[0] if matches else None


def digests_dir(book_id: str) -> Path:
    """Where a book's digest markdown lives, hand-editable on purpose."""
    d = book_dir(book_id) / "digests"
    d.mkdir(parents=True, exist_ok=True)
    return d


def failed_response_path(book_id: str, chapter_idx: int) -> Path:
    """Where a chapter's raw model response is dumped when the pass exhausts its retries."""
    d = digests_dir(book_id) / "failed"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"ch{chapter_idx:04d}.txt"


def manifest_for(book_id: str) -> dict:
    """Load a book's ingest manifest, empty if it was never written."""
    p = book_dir(book_id) / "manifest.json"
    if not p.is_file():
        return {}
    return json.loads(p.read_text())


def source_file_path(book_id: str) -> Path | None:
    """The retained EPUB inside the book's own directory, or None if this book
    was ingested from a file outside the library (the CLI path, where
    `source_path` points at the user's own read-only Books directory)."""
    matches = sorted(book_dir(book_id).glob("*.epub"))
    return matches[0] if matches else None


def migrate_legacy_book_dirs(iconn) -> list[tuple[str, str]]:
    """Rename `data/books/<sha256[:16]>` directories to `data/books/<book_id>`.

    Idempotent by construction: once a directory has its new name there is
    nothing left to rename. Never overwrites an existing destination and
    never deletes anything -- a directory it can't safely rename is left in
    place. No-ops on a database with no `book` table yet.
    """
    tables = {r[0] for r in iconn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "book" not in tables:
        return []

    books_root = data_dir() / "books"
    if not books_root.is_dir():
        return []

    moved: list[tuple[str, str]] = []
    for row in iconn.execute("SELECT id, sha256 FROM book"):
        book_id, sha256 = row["id"], row["sha256"]
        old_dir = books_root / sha256[:16]
        new_dir = books_root / book_id
        if old_dir == new_dir or not old_dir.is_dir() or new_dir.exists():
            continue
        old_dir.rename(new_dir)
        moved.append((str(old_dir), str(new_dir)))
    return moved


def series_dir() -> Path:
    """Holds the user-editable series definitions."""
    d = data_dir() / "series"
    d.mkdir(parents=True, exist_ok=True)
    return d


UPLOAD_STASH_MAX_AGE_SECONDS = 24 * 60 * 60


def _upload_stash_dir() -> Path:
    """Where inspected-but-not-yet-committed EPUB bytes wait for their commit call."""
    d = data_dir() / "uploads"
    d.mkdir(parents=True, exist_ok=True)
    return d


def upload_stash_path(sha256: str) -> Path:
    """The stash location for one inspected upload, content-addressed like everything else."""
    return _upload_stash_dir() / f"{sha256}.epub"


def upload_name_path(sha256: str) -> Path:
    """Sidecar holding the original upload filename -- the stash itself is
    content-addressed and can't carry a name."""
    return _upload_stash_dir() / f"{sha256}.name"


def prune_stale_uploads(max_age_seconds: float = UPLOAD_STASH_MAX_AGE_SECONDS) -> None:
    """Delete stashed uploads (and their name sidecars) older than `max_age_seconds`.

    No scheduler -- just called on inspect.
    """
    now = time.time()
    for pattern in ("*.epub", "*.name"):
        for f in _upload_stash_dir().glob(pattern):
            try:
                if now - f.stat().st_mtime > max_age_seconds:
                    f.unlink(missing_ok=True)
            except OSError:
                continue
