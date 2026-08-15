"""Filesystem layout for generated data, all of it under `./data/`.

`BOOKLENS_DATA_DIR` redirects it and is read at call time, so tests can isolate.
"""

from __future__ import annotations

import os
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


def book_dir(sha256: str) -> Path:
    """Per-book generated state, keyed by EPUB hash so editions stay separate."""
    d = data_dir() / "books" / sha256[:16]
    d.mkdir(parents=True, exist_ok=True)
    return d


def digests_dir(sha256: str) -> Path:
    """Where a book's digest markdown lives, hand-editable on purpose."""
    d = book_dir(sha256) / "digests"
    d.mkdir(parents=True, exist_ok=True)
    return d


def failed_response_path(sha256: str, chapter_idx: int) -> Path:
    """Where a chapter's raw model response is dumped when the pass exhausts its retries."""
    d = digests_dir(sha256) / "failed"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"ch{chapter_idx:04d}.txt"


def series_dir() -> Path:
    """Holds the user-editable series definitions."""
    d = data_dir() / "series"
    d.mkdir(parents=True, exist_ok=True)
    return d
