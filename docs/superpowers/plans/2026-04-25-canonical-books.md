# Canonical Books & Shared Knowledge Extraction — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace per-user series/book tables with a shared canonical book registry backed by Open Library, so knowledge extraction runs once per book across all users.

**Architecture:** `canonical_books` stores OL metadata (shared); `user_books` stores per-user reading progress; `knowledge` is re-keyed by `canonical_series_id` (shared). The `Series`/`Book` response models stay intact — only how they're loaded changes. `filter_to_progress` signature is unchanged since `Series` still carries the same structure.

**Tech Stack:** Python 3.11, FastAPI, Supabase (Postgres + Storage), Open Library Search API (free, no auth), Alpine.js frontend, Poetry

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `supabase/migration_canonical.sql` | Create | DB migration: new tables, modify knowledge |
| `src/models.py` | Modify | Add `CanonicalBook`, `UserBook`; update `Book` with `canonical_book_id` |
| `src/books/__init__.py` | Create | Package init |
| `src/books/open_library.py` | Create | Open Library search + metadata fetch |
| `src/library/manager.py` | Rewrite | CRUD using `canonical_books` + `user_books` |
| `src/knowledge/store.py` | Modify | Drop `user_id`, use `canonical_series_id` |
| `src/knowledge/pipeline.py` | Modify | Drop `user_id`, accept `canonical_series_id` + `book_index` |
| `src/main.py` | Modify | New endpoints, updated upload/delete/patch |
| `src/static/index.html` | Modify | Search UI in upload modal, library grouping by series |

---

## Task 1: DB Migration

**Files:**
- Create: `supabase/migration_canonical.sql`

- [ ] **Step 1: Write the migration SQL**

Create `supabase/migration_canonical.sql`:

```sql
-- canonical_books: shared book metadata keyed by Open Library work ID or UUID
CREATE TABLE IF NOT EXISTS canonical_books (
    id                  TEXT PRIMARY KEY,          -- ol_id e.g. "OL12345W", or UUID for manual
    ol_id               TEXT UNIQUE,               -- Open Library work ID (null for manual entries)
    title               TEXT NOT NULL,
    author              TEXT,
    series_name         TEXT,
    series_position     FLOAT,                     -- 1, 2, 2.5 etc; null for standalones
    canonical_series_id TEXT NOT NULL,             -- slugified series_name, or own id if standalone
    cover_url           TEXT,                      -- Open Library cover URL
    chapters            JSONB NOT NULL DEFAULT '[]', -- [{index, label}, ...]
    created_at          TIMESTAMPTZ DEFAULT now()
);

-- user_books: per-user reading state mapped to canonical books
CREATE TABLE IF NOT EXISTS user_books (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             TEXT NOT NULL,
    canonical_book_id   TEXT NOT NULL REFERENCES canonical_books(id),
    status              TEXT NOT NULL DEFAULT 'not_started',
    current_chapter_index INT,
    epub_path           TEXT,                      -- {user_id}/{canonical_book_id}/book.epub
    has_cover           BOOLEAN DEFAULT FALSE,
    created_at          TIMESTAMPTZ DEFAULT now(),
    UNIQUE (user_id, canonical_book_id)
);

-- knowledge: re-key by canonical_series_id, drop user_id
-- (Run AFTER migrating existing data or starting fresh)
ALTER TABLE knowledge DROP COLUMN IF EXISTS user_id;
ALTER TABLE knowledge RENAME COLUMN series_id TO canonical_series_id;
ALTER TABLE knowledge DROP CONSTRAINT IF EXISTS knowledge_pkey;
ALTER TABLE knowledge ADD PRIMARY KEY (canonical_series_id);
```

- [ ] **Step 2: Apply in Supabase SQL editor**

Run `supabase/migration_canonical.sql` in the Supabase project SQL editor.
Verify: tables `canonical_books` and `user_books` appear; `knowledge` has `canonical_series_id` column.

> **Note:** Existing `knowledge`, `series`, `books` rows are invalidated. Clear them or start fresh:
> ```sql
> DELETE FROM knowledge;
> ```
> The old `series` and `books` tables can stay (unused) until a cleanup migration later.

- [ ] **Step 3: Commit**

```bash
git add supabase/migration_canonical.sql
git commit -m "chore(db): add canonical_books and user_books migration"
```

---

## Task 2: Pydantic Models

**Files:**
- Modify: `src/models.py`

- [ ] **Step 1: Write failing test**

Create `tests/manual/test_models_canonical.py`:

```python
"""Smoke test: canonical models parse correctly."""
from src.models import CanonicalBook, UserBook, BookStatus


def test_canonical_book_standalone():
    """Standalone book (no series) has canonical_series_id == its own id."""
    cb = CanonicalBook(
        id="abc123",
        title="Piranesi",
        canonical_series_id="abc123",
    )
    assert cb.canonical_series_id == "abc123"
    assert cb.series_name is None


def test_canonical_book_series():
    cb = CanonicalBook(
        id="OL12345W",
        ol_id="OL12345W",
        title="The Way of Kings",
        author="Brandon Sanderson",
        series_name="The Stormlight Archive",
        series_position=1.0,
        canonical_series_id="the-stormlight-archive",
    )
    assert cb.canonical_series_id == "the-stormlight-archive"


def test_user_book_defaults():
    ub = UserBook(
        canonical_book_id="OL12345W",
        user_id="user-1",
        status=BookStatus.NOT_STARTED,
    )
    assert ub.current_chapter_index is None
    assert ub.has_cover is False
```

- [ ] **Step 2: Run test — expect failure**

```bash
poetry run pytest tests/manual/test_models_canonical.py -v
```
Expected: `ImportError` — `CanonicalBook`, `UserBook` not defined yet.

- [ ] **Step 3: Add models to `src/models.py`**

Add after the existing `ChunkRecord` class:

```python
class CanonicalBook(BaseModel):
    """Shared book metadata from Open Library or manual entry."""

    id: str                              # OL work ID or UUID
    ol_id: Optional[str] = None
    title: str
    author: Optional[str] = None
    series_name: Optional[str] = None
    series_position: Optional[float] = None
    canonical_series_id: str             # slugified series_name, or own id
    cover_url: Optional[str] = None
    chapters: List[Chapter] = []


class UserBook(BaseModel):
    """Per-user reading state for a canonical book."""

    canonical_book_id: str
    user_id: str
    status: BookStatus = BookStatus.NOT_STARTED
    current_chapter_index: Optional[int] = None
    epub_path: Optional[str] = None
    has_cover: bool = False
```

Also update the `Book` model to include `canonical_book_id` (used by endpoints):

```python
class Book(BaseModel):
    """Book metadata and state."""

    index: int
    canonical_book_id: str = ""          # NEW — empty string for backwards compat
    title: str
    author: Optional[str] = None         # NEW
    status: BookStatus
    chapters: List[Chapter]
    current_chapter_index: Optional[int] = None
    has_cover: bool = False
    cover_url: Optional[str] = None
    series_position: Optional[float] = None  # NEW
```

- [ ] **Step 4: Run test — expect pass**

```bash
poetry run pytest tests/manual/test_models_canonical.py -v
```
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/models.py tests/manual/test_models_canonical.py
git commit -m "feat(models): add CanonicalBook and UserBook models"
```

---

## Task 3: Open Library Service

**Files:**
- Create: `src/books/__init__.py`
- Create: `src/books/open_library.py`

- [ ] **Step 1: Write failing test**

Create `tests/manual/test_open_library.py`:

```python
"""Manual test: Open Library search returns results."""
import pytest
from src.books.open_library import search_books, OLBookResult


def test_search_returns_results():
    results = search_books("the way of kings")
    assert len(results) > 0
    first = results[0]
    assert isinstance(first, OLBookResult)
    assert "kings" in first.title.lower() or "stormlight" in (first.series_name or "").lower()


def test_search_populates_series():
    results = search_books("the way of kings brandon sanderson")
    series_results = [r for r in results if r.series_name]
    assert len(series_results) > 0


def test_search_standalone_book():
    results = search_books("piranesi susanna clarke")
    assert len(results) > 0


def test_canonical_series_id_slugified():
    from src.books.open_library import _canonical_series_id
    assert _canonical_series_id("The Stormlight Archive") == "the-stormlight-archive"
    assert _canonical_series_id("A Song of Ice & Fire") == "a-song-of-ice-fire"
```

- [ ] **Step 2: Run test — expect failure**

```bash
poetry run pytest tests/manual/test_open_library.py -v
```
Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Create `src/books/__init__.py`**

```python
```
(empty file)

- [ ] **Step 4: Create `src/books/open_library.py`**

```python
"""Open Library search and metadata helpers.

Uses the Open Library Search API (no auth required):
  https://openlibrary.org/search.json?q=<query>&fields=...&limit=10
"""

import re
import logging
import httpx
from pydantic import BaseModel

logger = logging.getLogger(__name__)

OL_SEARCH_URL = "https://openlibrary.org/search.json"
OL_COVER_URL = "https://covers.openlibrary.org/b/id/{cover_id}-M.jpg"


class OLBookResult(BaseModel):
    """A single search result from Open Library."""

    ol_id: str                        # e.g. "OL12345W"
    title: str
    author: str | None = None
    series_name: str | None = None
    series_position: float | None = None
    cover_url: str | None = None
    canonical_series_id: str          # slugified series_name or ol_id


def _canonical_series_id(series_name: str) -> str:
    """Convert series name to a stable slug."""
    slug = series_name.lower()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)   # strip punctuation
    slug = re.sub(r"\s+", "-", slug.strip())     # spaces → hyphens
    slug = re.sub(r"-+", "-", slug)              # collapse multiple hyphens
    return slug


def search_books(query: str, limit: int = 10) -> list[OLBookResult]:
    """Search Open Library and return up to `limit` results.

    Args:
        query: Free-text search (title, author, etc.)
        limit: Max results to return.

    Returns:
        List of OLBookResult objects, best matches first.
    """
    fields = "key,title,author_name,series,series_number,cover_i,first_publish_year"
    try:
        resp = httpx.get(
            OL_SEARCH_URL,
            params={"q": query, "fields": fields, "limit": limit},
            timeout=10.0,
        )
        resp.raise_for_status()
        docs = resp.json().get("docs", [])
    except Exception as exc:
        logger.warning("Open Library search failed: %s", exc)
        return []

    results: list[OLBookResult] = []
    for doc in docs:
        raw_key = doc.get("key", "")
        # key format: "/works/OL12345W"
        ol_id = raw_key.split("/")[-1] if raw_key else ""
        if not ol_id:
            continue

        title = doc.get("title", "").strip()
        if not title:
            continue

        authors = doc.get("author_name") or []
        author = authors[0] if authors else None

        series_list = doc.get("series") or []
        series_name = series_list[0].strip() if series_list else None

        series_number_raw = doc.get("series_number") or []
        series_position: float | None = None
        if series_number_raw:
            try:
                series_position = float(str(series_number_raw[0]).strip())
            except (ValueError, TypeError):
                pass

        cover_id = doc.get("cover_i")
        cover_url = OL_COVER_URL.format(cover_id=cover_id) if cover_id else None

        if series_name:
            can_series_id = _canonical_series_id(series_name)
        else:
            can_series_id = ol_id

        results.append(
            OLBookResult(
                ol_id=ol_id,
                title=title,
                author=author,
                series_name=series_name,
                series_position=series_position,
                cover_url=cover_url,
                canonical_series_id=can_series_id,
            )
        )

    return results
```

- [ ] **Step 5: Run test — expect pass**

```bash
poetry run pytest tests/manual/test_open_library.py -v
```
Expected: 4 passed. (Requires network access.)

- [ ] **Step 6: Commit**

```bash
git add src/books/__init__.py src/books/open_library.py tests/manual/test_open_library.py
git commit -m "feat(books): add Open Library search service"
```

---

## Task 4: GET /books/search Endpoint

**Files:**
- Modify: `src/main.py`

- [ ] **Step 1: Add the endpoint**

In `src/main.py`, add after the imports block (near top with other imports):

```python
from src.books.open_library import search_books, OLBookResult
```

Add the endpoint after the `@app.get("/library")` endpoint:

```python
@app.get("/books/search", response_model=list[OLBookResult])
async def search_books_endpoint(q: str) -> list[OLBookResult]:
    """Search Open Library for books matching the query.

    Returns up to 10 results with title, author, series, cover URL.
    Used by the frontend upload modal to look up book metadata.
    """
    if not q or len(q.strip()) < 2:
        return []
    return search_books(q.strip(), limit=10)
```

- [ ] **Step 2: Manual smoke test**

```bash
poetry run uvicorn src.main:app --reload &
curl "http://localhost:8000/books/search?q=the+way+of+kings" | python3 -m json.tool | head -40
```
Expected: JSON array with at least one result containing `ol_id`, `title`, `series_name`.

Kill the server: `pkill -f uvicorn`

- [ ] **Step 3: Commit**

```bash
git add src/main.py
git commit -m "feat(api): add GET /books/search endpoint (Open Library proxy)"
```

---

## Task 5: Library Manager Rewrite

**Files:**
- Modify: `src/library/manager.py`

The manager is rewritten to use `canonical_books` + `user_books`. The public interface stays the same where possible so callers in `main.py` need minimal changes. Key changes:
- `load_library(user_id)` → reads `user_books` JOIN `canonical_books`, groups by `canonical_series_id`
- `get_series(series_id, user_id)` → `series_id` is now `canonical_series_id`
- New: `upsert_canonical_book(cb)` and `upsert_user_book(ub)`
- `create_series` removed (series derived from OL data)

- [ ] **Step 1: Write failing test**

Create `tests/manual/test_library_manager_canonical.py`:

```python
"""Manual integration test for canonical library manager."""
import pytest
from src.library.manager import upsert_canonical_book, upsert_user_book, load_library, get_series_by_canonical_id
from src.models import CanonicalBook, UserBook, BookStatus, Chapter

TEST_USER = "test-canonical-user-001"
CB_ID = "OL_TEST_CANONICAL_001"
SERIES_SLUG = "test-series-slug"


@pytest.fixture(autouse=True)
def cleanup():
    yield
    from src.supabase_client import get_supabase_client
    client = get_supabase_client()
    client.table("user_books").delete().filter("user_id", "eq", TEST_USER).execute()
    client.table("canonical_books").delete().filter("id", "eq", CB_ID).execute()


def test_upsert_and_load():
    cb = CanonicalBook(
        id=CB_ID,
        title="Test Book One",
        author="Test Author",
        series_name="Test Series",
        series_position=1.0,
        canonical_series_id=SERIES_SLUG,
        chapters=[Chapter(index=0, label="Chapter 1"), Chapter(index=1, label="Chapter 2")],
    )
    upsert_canonical_book(cb)

    ub = UserBook(
        canonical_book_id=CB_ID,
        user_id=TEST_USER,
        status=BookStatus.READING,
        current_chapter_index=1,
    )
    upsert_user_book(ub)

    library = load_library(TEST_USER)
    # Should have one series
    assert len(library.series) >= 1
    test_series = next((s for s in library.series if s.id == SERIES_SLUG), None)
    assert test_series is not None
    assert len(test_series.books) == 1
    book = test_series.books[0]
    assert book.title == "Test Book One"
    assert book.status == BookStatus.READING
    assert book.current_chapter_index == 1
    assert book.canonical_book_id == CB_ID
```

- [ ] **Step 2: Run test — expect failure**

```bash
poetry run pytest tests/manual/test_library_manager_canonical.py -v
```
Expected: `ImportError` — functions not defined yet.

- [ ] **Step 3: Rewrite `src/library/manager.py`**

```python
"""Library state persistence using canonical_books + user_books tables."""

import logging
from typing import Optional

from src.config import settings
from src.supabase_client import get_supabase_client
from src.models import Book, BookStatus, CanonicalBook, Chapter, Library, Series, UserBook

logger = logging.getLogger(__name__)


def _cover_url(user_id: str, canonical_book_id: str) -> str:
    """Return the public Supabase Storage URL for a book cover."""
    return f"{settings.supabase_url}/storage/v1/object/public/covers/{user_id}/{canonical_book_id}/cover.jpg"


def _book_from_rows(cb_data: dict, ub_data: dict, book_index: int, user_id: str) -> Book:
    """Build a Book from canonical_books + user_books rows."""
    chapters_data = cb_data.get("chapters") or []
    chapters = [Chapter(index=c["index"], label=c["label"]) for c in chapters_data]
    has_cover = ub_data.get("has_cover", False)
    canonical_book_id = cb_data["id"]
    return Book(
        index=book_index,
        canonical_book_id=canonical_book_id,
        title=cb_data["title"],
        author=cb_data.get("author"),
        status=BookStatus(ub_data.get("status", "not_started")),
        chapters=chapters,
        current_chapter_index=ub_data.get("current_chapter_index"),
        has_cover=has_cover,
        cover_url=_cover_url(user_id, canonical_book_id) if has_cover else None,
        series_position=cb_data.get("series_position"),
    )


def upsert_canonical_book(cb: CanonicalBook) -> None:
    """Insert or update a canonical book row (idempotent on id)."""
    client = get_supabase_client()
    client.table("canonical_books").upsert({
        "id": cb.id,
        "ol_id": cb.ol_id,
        "title": cb.title,
        "author": cb.author,
        "series_name": cb.series_name,
        "series_position": cb.series_position,
        "canonical_series_id": cb.canonical_series_id,
        "cover_url": cb.cover_url,
        "chapters": [c.model_dump() for c in cb.chapters],
    }).execute()


def upsert_user_book(ub: UserBook) -> None:
    """Insert or update a user_books row."""
    client = get_supabase_client()
    client.table("user_books").upsert({
        "user_id": ub.user_id,
        "canonical_book_id": ub.canonical_book_id,
        "status": ub.status.value,
        "current_chapter_index": ub.current_chapter_index,
        "epub_path": ub.epub_path,
        "has_cover": ub.has_cover,
    }, on_conflict="user_id,canonical_book_id").execute()


def _group_into_series(rows: list[dict], user_id: str) -> list[Series]:
    """Group (canonical_books + user_books) rows into Series objects."""
    # Group by canonical_series_id
    groups: dict[str, list[dict]] = {}
    for row in rows:
        csid = row["canonical_series_id"]
        groups.setdefault(csid, []).append(row)

    series_list: list[Series] = []
    for canonical_series_id, group_rows in groups.items():
        # Sort by series_position (None → float inf so they go last)
        group_rows.sort(key=lambda r: r.get("series_position") or float("inf"))

        books: list[Book] = []
        for book_index, row in enumerate(group_rows):
            cb_data = {k: row[k] for k in ("id", "title", "author", "series_name", "series_position", "cover_url", "chapters")}
            ub_data = {k: row.get(k) for k in ("status", "current_chapter_index", "epub_path", "has_cover")}
            books.append(_book_from_rows(cb_data, ub_data, book_index, user_id))

        series_name = group_rows[0].get("series_name") or group_rows[0]["title"]
        series_list.append(Series(id=canonical_series_id, name=series_name, books=books))

    return series_list


async def load_library(user_id: str) -> Library:
    """Read library state from Supabase for a specific user."""
    client = get_supabase_client()
    resp = (
        client.table("user_books")
        .select("*, canonical_books(*)")
        .filter("user_id", "eq", user_id)
        .execute()
    )
    if not resp.data:
        return Library(series=[])

    # Flatten join result
    rows: list[dict] = []
    for ub_row in resp.data:
        cb = ub_row.pop("canonical_books", {}) or {}
        merged = {**cb, **ub_row}
        rows.append(merged)

    return Library(series=_group_into_series(rows, user_id))


async def get_series_by_canonical_id(canonical_series_id: str, user_id: str) -> Series | None:
    """Find a series by canonical_series_id for this user."""
    client = get_supabase_client()
    resp = (
        client.table("user_books")
        .select("*, canonical_books(*)")
        .filter("user_id", "eq", user_id)
        .filter("canonical_books.canonical_series_id", "eq", canonical_series_id)
        .execute()
    )
    if not resp.data:
        return None

    rows: list[dict] = []
    for ub_row in resp.data:
        cb = ub_row.pop("canonical_books", {}) or {}
        if not cb:
            continue
        if cb.get("canonical_series_id") != canonical_series_id:
            continue
        rows.append({**cb, **ub_row})

    if not rows:
        return None

    series_list = _group_into_series(rows, user_id)
    return series_list[0] if series_list else None


async def get_book_by_canonical_id(canonical_book_id: str, user_id: str) -> Book | None:
    """Fetch a single book and its series context."""
    client = get_supabase_client()
    resp = (
        client.table("user_books")
        .select("*, canonical_books(*)")
        .filter("user_id", "eq", user_id)
        .filter("canonical_book_id", "eq", canonical_book_id)
        .execute()
    )
    if not resp.data:
        return None
    ub_row = resp.data[0]
    cb = ub_row.pop("canonical_books", {}) or {}
    merged = {**cb, **ub_row}
    # book_index within series: load full series to derive it
    series = await get_series_by_canonical_id(cb.get("canonical_series_id", canonical_book_id), user_id)
    if series is None:
        return None
    return next((b for b in series.books if b.canonical_book_id == canonical_book_id), None)


async def remove_user_book(canonical_book_id: str, user_id: str) -> None:
    """Remove a user_books row (does not touch canonical_books or knowledge)."""
    client = get_supabase_client()
    client.table("user_books").delete().filter("canonical_book_id", "eq", canonical_book_id).filter("user_id", "eq", user_id).execute()


async def remove_user_series(canonical_series_id: str, user_id: str) -> None:
    """Remove all user_books for a series (user-scoped)."""
    client = get_supabase_client()
    # Get canonical_book_ids in this series for this user
    resp = (
        client.table("user_books")
        .select("canonical_book_id, canonical_books(canonical_series_id)")
        .filter("user_id", "eq", user_id)
        .execute()
    )
    ids_to_delete = [
        row["canonical_book_id"]
        for row in (resp.data or [])
        if (row.get("canonical_books") or {}).get("canonical_series_id") == canonical_series_id
    ]
    for cid in ids_to_delete:
        client.table("user_books").delete().filter("canonical_book_id", "eq", cid).filter("user_id", "eq", user_id).execute()


async def other_users_have_book(canonical_book_id: str, excluding_user_id: str) -> bool:
    """Return True if any other user has this canonical book in their library."""
    client = get_supabase_client()
    resp = (
        client.table("user_books")
        .select("id")
        .filter("canonical_book_id", "eq", canonical_book_id)
        .neq("user_id", excluding_user_id)
        .limit(1)
        .execute()
    )
    return bool(resp.data)


async def other_users_have_series(canonical_series_id: str, excluding_user_id: str) -> bool:
    """Return True if any other user has any book from this series."""
    client = get_supabase_client()
    resp = (
        client.table("user_books")
        .select("canonical_book_id, canonical_books(canonical_series_id)")
        .neq("user_id", excluding_user_id)
        .execute()
    )
    for row in (resp.data or []):
        if (row.get("canonical_books") or {}).get("canonical_series_id") == canonical_series_id:
            return True
    return False


async def update_user_book_status(
    canonical_book_id: str,
    status: BookStatus,
    current_chapter_index: int | None,
    user_id: str,
) -> None:
    """Update reading status for a user_books row."""
    client = get_supabase_client()
    update_data: dict = {"status": status.value}
    if status == BookStatus.READING:
        update_data["current_chapter_index"] = current_chapter_index
    else:
        update_data["current_chapter_index"] = None
    client.table("user_books").update(update_data).filter("canonical_book_id", "eq", canonical_book_id).filter("user_id", "eq", user_id).execute()


async def set_user_book_cover(canonical_book_id: str, user_id: str, has_cover: bool) -> None:
    """Mark whether this user has a cover for their copy of the book."""
    client = get_supabase_client()
    client.table("user_books").update({"has_cover": has_cover}).filter("canonical_book_id", "eq", canonical_book_id).filter("user_id", "eq", user_id).execute()
```

- [ ] **Step 4: Run test — expect pass**

```bash
poetry run pytest tests/manual/test_library_manager_canonical.py -v
```
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add src/library/manager.py tests/manual/test_library_manager_canonical.py
git commit -m "feat(library): rewrite manager using canonical_books + user_books"
```

---

## Task 6: Knowledge Store Update

**Files:**
- Modify: `src/knowledge/store.py`

Drop `user_id` from all functions. `series_id` → `canonical_series_id`. `filter_to_progress` signature stays the same (still takes `Series`, which now has same structure).

- [ ] **Step 1: Update `src/knowledge/store.py`**

Replace the entire file:

```python
"""Knowledge base persistence and spoiler-safe filtering.

The knowledge base is stored as one row per canonical_series_id in Supabase:
    knowledge table: canonical_series_id (PK), data (JSONB)

Extraction is shared across users — no user_id in this layer.
Spoiler filtering (filter_to_progress) still takes a Series object, which
is built per-user from user_books + canonical_books by the library manager.
"""

from src.supabase_client import get_supabase_client
from src.knowledge.models import (
    ChapterRef,
    ChapterSummary,
    CharacterEntity,
    CharacterEvent,
    KnowledgeBase,
    Relationship,
    RelationshipMoment,
    WorldFact,
)
from src.models import BookStatus, Series


async def load_knowledge(canonical_series_id: str) -> KnowledgeBase:
    """Read shared knowledge base from Supabase.

    Args:
        canonical_series_id: Canonical series slug or standalone book id.

    Returns:
        KnowledgeBase object (empty if not yet extracted).
    """
    client = get_supabase_client()
    resp = (
        client.table("knowledge")
        .select("data")
        .filter("canonical_series_id", "eq", canonical_series_id)
        .execute()
    )
    if not resp.data:
        return KnowledgeBase(series_id=canonical_series_id)
    return KnowledgeBase.model_validate(resp.data[0]["data"])


async def save_knowledge(kb: KnowledgeBase, canonical_series_id: str) -> None:
    """Write shared knowledge base to Supabase.

    Args:
        kb: KnowledgeBase to persist.
        canonical_series_id: The series key.
    """
    client = get_supabase_client()
    data = kb.model_dump()
    client.table("knowledge").upsert(
        {"canonical_series_id": canonical_series_id, "data": data}
    ).execute()


def is_chapter_extracted(kb: KnowledgeBase, book_index: int, chapter_index: int) -> bool:
    """Check whether a chapter has already been processed for extraction."""
    return any(
        ref.book_index == book_index and ref.chapter_index == chapter_index
        for ref in kb.extracted_chapters
    )


def _is_within_progress(book_index: int, chapter_index: int, series: Series) -> bool:
    """Check if a (book_index, chapter_index) pair is within reading progress."""
    book = next((b for b in series.books if b.index == book_index), None)
    if book is None:
        return False
    if book.status == BookStatus.NOT_STARTED:
        return False
    if book.status == BookStatus.COMPLETED:
        return True
    max_chapter = book.current_chapter_index if book.current_chapter_index is not None else 0
    return chapter_index <= max_chapter


def filter_to_progress(kb: KnowledgeBase, series: Series) -> KnowledgeBase:
    """Return a KnowledgeBase containing only knowledge within reading progress."""
    def within(book_index: int, chapter_index: int) -> bool:
        return _is_within_progress(book_index, chapter_index, series)

    filtered_characters: list[CharacterEntity] = []
    for char in kb.characters:
        if char.first_appearance is None:
            continue
        if not within(char.first_appearance.book_index, char.first_appearance.chapter_index):
            continue
        safe_events: list[CharacterEvent] = [
            e for e in char.key_events if within(e.book_index, e.chapter_index)
        ]
        filtered_characters.append(
            CharacterEntity(
                name=char.name,
                aliases=char.aliases,
                faction=char.faction,
                role=char.role,
                description=char.description,
                first_appearance=char.first_appearance,
                key_events=safe_events,
            )
        )

    filtered_relationships: list[Relationship] = []
    for rel in kb.relationships:
        safe_moments: list[RelationshipMoment] = [
            m for m in rel.moments if within(m.book_index, m.chapter_index)
        ]
        if not safe_moments:
            continue
        filtered_relationships.append(
            Relationship(
                character_a=rel.character_a,
                character_b=rel.character_b,
                type=rel.type,
                description=rel.description,
                moments=safe_moments,
            )
        )

    filtered_world_facts: list[WorldFact] = [
        wf for wf in kb.world_facts if within(wf.book_index, wf.chapter_index)
    ]
    filtered_summaries: list[ChapterSummary] = [
        s for s in kb.summaries if within(s.book_index, s.chapter_index)
    ]
    filtered_extracted: list[ChapterRef] = [
        r for r in kb.extracted_chapters if within(r.book_index, r.chapter_index)
    ]

    visible_names = {c.name for c in filtered_characters}
    filtered_aliases = {
        alias: canonical
        for alias, canonical in kb.alias_registry.items()
        if canonical in visible_names
    }

    return KnowledgeBase(
        series_id=kb.series_id,
        characters=filtered_characters,
        relationships=filtered_relationships,
        world_facts=filtered_world_facts,
        summaries=filtered_summaries,
        alias_registry=filtered_aliases,
        extracted_chapters=filtered_extracted,
    )


async def delete_series_knowledge(canonical_series_id: str) -> None:
    """Delete the knowledge for a series (only if no other users reference it)."""
    client = get_supabase_client()
    client.table("knowledge").delete().filter("canonical_series_id", "eq", canonical_series_id).execute()


async def delete_book_knowledge(canonical_series_id: str, book_index: int) -> KnowledgeBase:
    """Remove knowledge entries for a specific book index and save."""
    kb = await load_knowledge(canonical_series_id)

    kept_characters: list[CharacterEntity] = []
    removed_names: set[str] = set()
    for char in kb.characters:
        if char.first_appearance is not None and char.first_appearance.book_index == book_index:
            removed_names.add(char.name)
        else:
            safe_events = [e for e in char.key_events if e.book_index != book_index]
            kept_characters.append(
                CharacterEntity(
                    name=char.name,
                    aliases=char.aliases,
                    faction=char.faction,
                    role=char.role,
                    description=char.description,
                    first_appearance=char.first_appearance,
                    key_events=safe_events,
                )
            )

    kept_relationships: list[Relationship] = []
    for rel in kb.relationships:
        if rel.character_a in removed_names or rel.character_b in removed_names:
            continue
        kept_moments = [m for m in rel.moments if m.book_index != book_index]
        if not kept_moments:
            continue
        kept_relationships.append(
            Relationship(
                character_a=rel.character_a,
                character_b=rel.character_b,
                type=rel.type,
                description=rel.description,
                moments=kept_moments,
            )
        )

    kept_world_facts = [wf for wf in kb.world_facts if wf.book_index != book_index]
    kept_summaries = [s for s in kb.summaries if s.book_index != book_index]
    kept_extracted = [r for r in kb.extracted_chapters if r.book_index != book_index]
    kept_aliases = {
        alias: canonical
        for alias, canonical in kb.alias_registry.items()
        if canonical not in removed_names
    }

    updated = KnowledgeBase(
        series_id=canonical_series_id,
        characters=kept_characters,
        relationships=kept_relationships,
        world_facts=kept_world_facts,
        summaries=kept_summaries,
        alias_registry=kept_aliases,
        extracted_chapters=kept_extracted,
    )
    await save_knowledge(updated, canonical_series_id)
    return updated
```

- [ ] **Step 2: Run existing knowledge store tests (if any) and the server import check**

```bash
poetry run python -c "from src.knowledge.store import load_knowledge, save_knowledge, filter_to_progress; print('OK')"
```
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add src/knowledge/store.py
git commit -m "refactor(knowledge): drop user_id, re-key by canonical_series_id"
```

---

## Task 7: Knowledge Pipeline Update

**Files:**
- Modify: `src/knowledge/pipeline.py`

Drop `user_id`. Callers pass `canonical_series_id` and `book_index` explicitly.

- [ ] **Step 1: Update `src/knowledge/pipeline.py`**

Replace the function signature and internal calls:

```python
"""Book-level extraction orchestration.

extract_book_knowledge() processes all chapters in a book sequentially,
building up the shared KnowledgeBase chapter by chapter.

canonical_series_id: the shared series key (no user_id)
book_index: 0-based position of this book in the series (derived from series_position ordering)
"""

import asyncio
import logging

import anthropic

from src.knowledge.extractor import extract_chapter
from src.knowledge.merger import merge_extraction
from src.knowledge.models import KnowledgeBase
from src.knowledge.store import is_chapter_extracted, load_knowledge, save_knowledge
from src.models import ParsedChapter

logger = logging.getLogger(__name__)


async def extract_book_knowledge(
    chapters: list[ParsedChapter],
    canonical_series_id: str,
    book_index: int,
    client: anthropic.AsyncAnthropic,
    extraction_model: str,
    concurrency: int = 2,
) -> KnowledgeBase:
    """Extract structured knowledge from all chapters of a book.

    Args:
        chapters: Parsed chapters from epub.
        canonical_series_id: Shared series key (no user_id).
        book_index: 0-based position of this book in the series.
        client: Anthropic async client.
        extraction_model: Claude model ID for extraction.
        concurrency: Max parallel LLM calls.

    Returns:
        Updated KnowledgeBase.
    """
    kb = await load_knowledge(canonical_series_id)

    to_extract = [c for c in chapters if not is_chapter_extracted(kb, book_index, c.index)]
    if not to_extract:
        logger.info("[%s] Book %d — already fully extracted.", canonical_series_id, book_index)
        return kb

    total = len(chapters)
    logger.info(
        "[%s] Book %d — starting extraction for %d/%d chapters (concurrency=%d)",
        canonical_series_id, book_index, len(to_extract), total, concurrency,
    )

    semaphore = asyncio.Semaphore(concurrency)

    async def _safe_extract(chapter: ParsedChapter, current_kb: KnowledgeBase) -> KnowledgeBase:
        async with semaphore:
            return await extract_chapter(
                chapter=chapter,
                book_index=book_index,
                kb=current_kb,
                client=client,
                extraction_model=extraction_model,
            )

    seed_chapters = [c for c in to_extract if c.index < 2]
    remaining_chapters = [c for c in to_extract if c.index >= 2]

    for chapter in seed_chapters:
        logger.info("[%s] Book %d — seed chapter %d: %s", canonical_series_id, book_index, chapter.index + 1, chapter.label)
        extraction = await _safe_extract(chapter, kb)
        kb = merge_extraction(kb, extraction, book_index=book_index, chapter_index=chapter.index)
        await save_knowledge(kb, canonical_series_id)

    if remaining_chapters:
        tasks = {}
        for c in remaining_chapters:
            tasks[c.index] = asyncio.create_task(_safe_extract(c, kb))
            await asyncio.sleep(1.0)

        for idx in sorted(tasks.keys()):
            extraction = await tasks[idx]
            kb = merge_extraction(kb, extraction, book_index=book_index, chapter_index=idx)
            await save_knowledge(kb, canonical_series_id)
            logger.info("[%s] Book %d — chapter %d merged and saved", canonical_series_id, book_index, idx + 1)

    logger.info("[%s] Book %d extraction complete.", canonical_series_id, book_index)
    return kb
```

- [ ] **Step 2: Import check**

```bash
poetry run python -c "from src.knowledge.pipeline import extract_book_knowledge; print('OK')"
```
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add src/knowledge/pipeline.py
git commit -m "refactor(knowledge): drop user_id from pipeline, accept canonical_series_id"
```

---

## Task 8: Rewrite Upload Endpoint and Background Extraction

**Files:**
- Modify: `src/main.py`

This is the largest change to `main.py`. We add `POST /library/books`, update `_run_extraction_background`, and wire up the new manager functions.

- [ ] **Step 1: Update imports in `src/main.py`**

Replace the `from src.library.manager import ...` import line with:

```python
from src.library.manager import (
    get_book_by_canonical_id,
    get_series_by_canonical_id,
    load_library,
    other_users_have_book,
    other_users_have_series,
    remove_user_book,
    remove_user_series,
    set_user_book_cover,
    update_user_book_status,
    upsert_canonical_book,
    upsert_user_book,
)
```

Replace `from src.knowledge.store import ...` with:

```python
from src.knowledge.store import (
    delete_book_knowledge,
    delete_series_knowledge,
    filter_to_progress,
    load_knowledge,
)
```

Add to imports:

```python
from src.books.open_library import OLBookResult, _canonical_series_id
from src.models import CanonicalBook, UserBook
import uuid
```

- [ ] **Step 2: Update request/response models in `src/main.py`**

Replace `UploadBookResponse`:

```python
class UploadBookResponse(BaseModel):
    """Response returned after a successful book upload."""
    canonical_book_id: str
    canonical_series_id: str
    title: str
    chapter_count: int
    knowledge_already_extracted: bool = False
```

Add new upload request model (for manual fallback — OL search uses form fields):

```python
class AddBookRequest(BaseModel):
    """Body fields for POST /library/books (JSON portion)."""
    # Populated from OL search result or manual entry
    canonical_book_id: str       # ol_id or client-generated UUID
    ol_id: str | None = None
    title: str
    author: str | None = None
    series_name: str | None = None
    series_position: float | None = None
    canonical_series_id: str
    cover_url: str | None = None
```

- [ ] **Step 3: Update `_run_extraction_background`**

Replace the existing function:

```python
async def _run_extraction_background(
    canonical_series_id: str,
    canonical_book_id: str,
    book_index: int,
    parsed_chapters: list,
    anthropic_client: anthropic.AsyncAnthropic,
    extracting_books: set,
) -> None:
    """Background task: extract shared knowledge for a book after upload."""
    if canonical_book_id in extracting_books:
        logger.info("Extraction already in progress for %s, skipping.", canonical_book_id)
        return

    extracting_books.add(canonical_book_id)
    try:
        logger.info("Background extraction started: %s (series=%s book_index=%d)", canonical_book_id, canonical_series_id, book_index)
        await extract_book_knowledge(
            chapters=parsed_chapters,
            canonical_series_id=canonical_series_id,
            book_index=book_index,
            client=anthropic_client,
            extraction_model=settings.extraction_model,
        )
        logger.info("Background extraction complete: %s", canonical_book_id)
    except Exception:
        logger.error("Background extraction failed: %s", canonical_book_id, exc_info=True)
    finally:
        extracting_books.discard(canonical_book_id)
```

- [ ] **Step 4: Add `POST /library/books` endpoint**

Add after the existing upload endpoint (keep old endpoint temporarily for rollback safety):

```python
@app.post("/library/books", response_model=UploadBookResponse)
async def upload_book_canonical(
    request: Request,
    background_tasks: BackgroundTasks,
    # OL / manual metadata fields
    canonical_book_id: Annotated[str, Form()],
    title: Annotated[str, Form()],
    canonical_series_id: Annotated[str, Form()],
    ol_id: Annotated[str | None, Form()] = None,
    author: Annotated[str | None, Form()] = None,
    series_name: Annotated[str | None, Form()] = None,
    series_position: Annotated[float | None, Form()] = None,
    cover_url: Annotated[str | None, Form()] = None,
    file: UploadFile = File(...),
    user_id: str = Depends(get_current_user),
) -> UploadBookResponse:
    """Upload an epub and register it against a canonical book.

    If another user has already uploaded the same canonical book, knowledge
    extraction is skipped (shared KB reused). Vectors and epub are always
    stored per-user.
    """
    if not file.filename or not file.filename.endswith(".epub"):
        raise HTTPException(status_code=400, detail="File must be an .epub.")

    book_bytes = await file.read()
    client = get_supabase_client()

    # 1. Parse epub to get chapters
    from io import BytesIO
    parsed_chapters = parse_epub(BytesIO(book_bytes))
    chapters_for_db = [{"index": c.index, "label": c.label} for c in parsed_chapters]

    # 2. Upsert canonical_books row (idempotent)
    from src.models import CanonicalBook, Chapter
    cb = CanonicalBook(
        id=canonical_book_id,
        ol_id=ol_id,
        title=title,
        author=author,
        series_name=series_name,
        series_position=series_position,
        canonical_series_id=canonical_series_id,
        cover_url=cover_url,
        chapters=[Chapter(index=c["index"], label=c["label"]) for c in chapters_for_db],
    )
    upsert_canonical_book(cb)

    # 3. Store epub per-user
    epub_path = f"{user_id}/{canonical_book_id}/book.epub"
    try:
        client.storage.from_("books").upload(path=epub_path, file=book_bytes, file_options={"content-type": "application/epub+zip"})
    except Exception as e:
        logger.warning("Failed to upload epub to Supabase: %s", e)

    # 4. Index vectors (per-user, unchanged)
    # Compute book_index from series_position ordering
    series = await get_series_by_canonical_id(canonical_series_id, user_id)
    existing_positions: list[float] = []
    if series:
        for b in series.books:
            if b.series_position is not None and b.canonical_book_id != canonical_book_id:
                existing_positions.append(b.series_position)
    all_positions = sorted(existing_positions + [series_position or 999.0])
    book_index = all_positions.index(series_position or 999.0)

    vector_store: SupabaseVectorStore = request.app.state.vector_store
    from src.ingestion.chunker import chunk_chapter
    all_chunks = []
    for chapter in parsed_chapters:
        all_chunks.extend(chunk_chapter(chapter))
    index_book(all_chunks, canonical_series_id, book_index, vector_store, user_id)

    # 5. Extract and save cover
    has_cover = False
    try:
        cover_result = extract_cover(book_bytes) or fetch_cover_open_library(title, book_bytes)
        if cover_result is not None:
            cover_bytes, _ = cover_result
            cover_path = f"{user_id}/{canonical_book_id}/cover.jpg"
            client.storage.from_("covers").upload(path=cover_path, file=cover_bytes, file_options={"content-type": "image/jpeg"})
            has_cover = True
    except Exception:
        logger.warning("Cover extraction failed; continuing", exc_info=True)

    # 6. Upsert user_books row
    from src.models import UserBook
    ub = UserBook(
        canonical_book_id=canonical_book_id,
        user_id=user_id,
        status=BookStatus.NOT_STARTED,
        epub_path=epub_path,
        has_cover=has_cover,
    )
    upsert_user_book(ub)
    if has_cover:
        await set_user_book_cover(canonical_book_id, user_id, True)

    # 7. Trigger extraction only if knowledge doesn't already exist
    kb = await load_knowledge(canonical_series_id)
    knowledge_already_extracted = is_chapter_extracted_for_book(kb, book_index, len(parsed_chapters))
    if not knowledge_already_extracted:
        background_tasks.add_task(
            _run_extraction_background,
            canonical_series_id,
            canonical_book_id,
            book_index,
            parsed_chapters,
            request.app.state.anthropic_client,
            request.app.state.extracting_books,
        )

    return UploadBookResponse(
        canonical_book_id=canonical_book_id,
        canonical_series_id=canonical_series_id,
        title=title,
        chapter_count=len(parsed_chapters),
        knowledge_already_extracted=knowledge_already_extracted,
    )
```

Add helper above the endpoint:

```python
def is_chapter_extracted_for_book(kb: KnowledgeBase, book_index: int, total_chapters: int) -> bool:
    """Return True if all chapters of this book_index are already in the KB."""
    extracted = {ref.chapter_index for ref in kb.extracted_chapters if ref.book_index == book_index}
    return len(extracted) >= total_chapters
```

- [ ] **Step 5: Import check**

```bash
poetry run python -c "from src.main import app; print('OK')"
```
Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add src/main.py
git commit -m "feat(api): add POST /library/books canonical upload endpoint"
```

---

## Task 9: Update Delete, Patch, and Knowledge Endpoints

**Files:**
- Modify: `src/main.py`

- [ ] **Step 1: Replace delete series endpoint**

Replace the existing `@app.delete("/library/series/{series_id}")` handler:

```python
@app.delete("/library/series/{canonical_series_id}", response_model=Library)
async def delete_series_endpoint(
    canonical_series_id: str,
    request: Request,
    user_id: str = Depends(get_current_user),
) -> Library:
    """Delete all of a user's books in a series. Deletes shared knowledge only if no other users have it."""
    series = await get_series_by_canonical_id(canonical_series_id, user_id)
    if series is None:
        raise HTTPException(status_code=404, detail=f"Series '{canonical_series_id}' not found.")

    vector_store: SupabaseVectorStore = request.app.state.vector_store
    client = get_supabase_client()

    for book in series.books:
        cid = book.canonical_book_id
        vector_store.delete_book(canonical_series_id, book.index, user_id)
        try:
            client.storage.from_("books").remove([f"{user_id}/{cid}/book.epub"])
            client.storage.from_("covers").remove([f"{user_id}/{cid}/cover.jpg"])
        except Exception as e:
            logger.warning("Storage cleanup failed: %s", e)

    # Only delete shared knowledge if no other users have any book in this series
    if not await other_users_have_series(canonical_series_id, user_id):
        await delete_series_knowledge(canonical_series_id)

    await remove_user_series(canonical_series_id, user_id)
    return await load_library(user_id)
```

- [ ] **Step 2: Replace delete book endpoint**

Replace `@app.delete("/library/series/{series_id}/books/{book_index}")`:

```python
@app.delete("/library/books/{canonical_book_id}", response_model=Library)
async def delete_book_endpoint(
    canonical_book_id: str,
    request: Request,
    user_id: str = Depends(get_current_user),
) -> Library:
    """Remove a book from the user's library. Removes from shared KB only if no other users have it."""
    book = await get_book_by_canonical_id(canonical_book_id, user_id)
    if book is None:
        raise HTTPException(status_code=404, detail=f"Book '{canonical_book_id}' not found.")

    series = await get_series_by_canonical_id(
        (await _get_canonical_series_id_for_book(canonical_book_id)), user_id
    )
    book_index = book.index

    vector_store: SupabaseVectorStore = request.app.state.vector_store
    if series:
        vector_store.delete_book(series.id, book_index, user_id)

    client = get_supabase_client()
    try:
        client.storage.from_("books").remove([f"{user_id}/{canonical_book_id}/book.epub"])
        client.storage.from_("covers").remove([f"{user_id}/{canonical_book_id}/cover.jpg"])
    except Exception as e:
        logger.warning("Storage cleanup failed: %s", e)

    if not await other_users_have_book(canonical_book_id, user_id) and series:
        await delete_book_knowledge(series.id, book_index)

    await remove_user_book(canonical_book_id, user_id)
    return await load_library(user_id)
```

Add helper:

```python
async def _get_canonical_series_id_for_book(canonical_book_id: str) -> str:
    """Look up the canonical_series_id for a given canonical_book_id."""
    client = get_supabase_client()
    resp = client.table("canonical_books").select("canonical_series_id").filter("id", "eq", canonical_book_id).execute()
    if resp.data:
        return resp.data[0]["canonical_series_id"]
    return canonical_book_id
```

- [ ] **Step 3: Replace patch book status endpoint**

Replace `@app.patch("/library/series/{series_id}/books/{book_index}")`:

```python
@app.patch("/library/books/{canonical_book_id}", response_model=Library)
async def update_book_status_endpoint(
    canonical_book_id: str,
    body: UpdateBookStatusRequest,
    user_id: str = Depends(get_current_user),
) -> Library:
    """Update a book's reading status."""
    book = await get_book_by_canonical_id(canonical_book_id, user_id)
    if book is None:
        raise HTTPException(status_code=404, detail=f"Book '{canonical_book_id}' not found.")
    await update_user_book_status(canonical_book_id, body.status, body.current_chapter_index, user_id)
    return await load_library(user_id)
```

- [ ] **Step 4: Update knowledge/graph/query endpoints to use canonical_series_id**

For each of the following endpoints, replace `series_id` parameter and `get_series()` calls with `canonical_series_id` and `get_series_by_canonical_id()`, and update `load_knowledge()` calls (drop `user_id` arg):

**`GET /library/series/{series_id}/knowledge`** → `GET /library/series/{canonical_series_id}/knowledge`:
```python
@app.get("/library/series/{canonical_series_id}/knowledge", response_model=KnowledgeBase)
async def get_knowledge_endpoint(
    canonical_series_id: str, user_id: str = Depends(get_current_user)
) -> KnowledgeBase:
    series = await get_series_by_canonical_id(canonical_series_id, user_id)
    if series is None:
        raise HTTPException(status_code=404, detail=f"Series '{canonical_series_id}' not found.")
    kb = await load_knowledge(canonical_series_id)
    return filter_to_progress(kb, series)
```

**`GET /library/series/{series_id}/knowledge-summary`** → same pattern, replace `get_series` and `load_knowledge` calls.

**`POST /library/series/{series_id}/books/{book_index}/extract`** → `POST /library/books/{canonical_book_id}/extract`:
```python
@app.post("/library/books/{canonical_book_id}/extract")
async def extract_book_endpoint(
    canonical_book_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    user_id: str = Depends(get_current_user),
):
    """Trigger knowledge extraction for a book (manual re-trigger)."""
    book = await get_book_by_canonical_id(canonical_book_id, user_id)
    if book is None:
        raise HTTPException(status_code=404, detail=f"Book '{canonical_book_id}' not found.")

    canonical_series_id = await _get_canonical_series_id_for_book(canonical_book_id)

    epub_path = f"{user_id}/{canonical_book_id}/book.epub"
    try:
        book_data = get_supabase_client().storage.from_("books").download(epub_path)
    except Exception:
        raise HTTPException(status_code=404, detail="Epub not found in storage.")

    from io import BytesIO
    parsed_chapters = parse_epub(BytesIO(book_data))

    if canonical_book_id in request.app.state.extracting_books:
        return {"message": "Extraction already in progress"}

    background_tasks.add_task(
        _run_extraction_background,
        canonical_series_id,
        canonical_book_id,
        book.index,
        parsed_chapters,
        request.app.state.anthropic_client,
        request.app.state.extracting_books,
    )
    return {"message": "Extraction started"}
```

**`GET /library/series/{series_id}/graph`** and **`GET /library/series/{series_id}/graph/digest`** — same pattern: replace `get_series` with `get_series_by_canonical_id`, `load_knowledge(series_id, user_id)` with `load_knowledge(canonical_series_id)`.

**`POST /query`** — replace `get_series(body.series_id, user_id)` with `get_series_by_canonical_id(body.series_id, user_id)` and `load_knowledge(body.series_id, user_id)` with `load_knowledge(body.series_id)`.

- [ ] **Step 5: Import check**

```bash
poetry run python -c "from src.main import app; print('OK')"
```
Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add src/main.py
git commit -m "refactor(api): update delete/patch/knowledge endpoints to canonical model"
```

---

## Task 10: Frontend — Upload Modal with Open Library Search

**Files:**
- Modify: `src/static/index.html`

The upload modal currently shows: series name, book index, title, file picker.

New flow: search box → results list → (auto-fill) → file picker. "Add manually" toggle shows original fields.

- [ ] **Step 1: Locate the upload modal in `index.html`**

```bash
grep -n "upload\|Upload\|addBook\|series_id\|book_index" src/static/index.html | head -30
```

Note the line numbers of the upload modal section.

- [ ] **Step 2: Add OL search state to the Alpine.js `app()` function**

Find the `app()` function's `data` return object and add:

```javascript
// OL search state
olQuery: '',
olResults: [],
olSearching: false,
olSelected: null,      // { ol_id, title, author, series_name, series_position, canonical_series_id, cover_url }
uploadManual: false,   // toggle for manual fallback
// manual fallback fields
manualTitle: '',
manualAuthor: '',
manualSeriesName: '',
manualSeriesPosition: '',
```

- [ ] **Step 3: Add OL search methods to `app()`**

Add these methods:

```javascript
async searchOL() {
    if (this.olQuery.length < 2) return;
    this.olSearching = true;
    this.olResults = [];
    try {
        const res = await fetch(`/books/search?q=${encodeURIComponent(this.olQuery)}`);
        this.olResults = await res.json();
    } catch (e) {
        console.error('OL search failed', e);
    } finally {
        this.olSearching = false;
    }
},
selectOLResult(result) {
    this.olSelected = result;
    this.olResults = [];
    this.olQuery = result.title;
},
clearOLSelection() {
    this.olSelected = null;
    this.olQuery = '';
},
async uploadBook() {
    if (!this.uploadFile) return;
    const formData = new FormData();
    formData.append('file', this.uploadFile);

    if (this.uploadManual || !this.olSelected) {
        // Manual path: generate a UUID client-side
        const manualId = crypto.randomUUID();
        const seriesSlug = this.manualSeriesName
            ? this.manualSeriesName.toLowerCase().replace(/[^a-z0-9\s-]/g, '').replace(/\s+/g, '-')
            : manualId;
        formData.append('canonical_book_id', manualId);
        formData.append('title', this.manualTitle);
        formData.append('canonical_series_id', seriesSlug);
        if (this.manualAuthor) formData.append('author', this.manualAuthor);
        if (this.manualSeriesName) formData.append('series_name', this.manualSeriesName);
        if (this.manualSeriesPosition) formData.append('series_position', this.manualSeriesPosition);
    } else {
        formData.append('canonical_book_id', this.olSelected.ol_id);
        formData.append('ol_id', this.olSelected.ol_id);
        formData.append('title', this.olSelected.title);
        formData.append('canonical_series_id', this.olSelected.canonical_series_id);
        if (this.olSelected.author) formData.append('author', this.olSelected.author);
        if (this.olSelected.series_name) formData.append('series_name', this.olSelected.series_name);
        if (this.olSelected.series_position != null) formData.append('series_position', this.olSelected.series_position);
        if (this.olSelected.cover_url) formData.append('cover_url', this.olSelected.cover_url);
    }

    this.uploading = true;
    try {
        const res = await fetch('/library/books', { method: 'POST', body: formData, headers: { 'Authorization': `Bearer ${this.token}` } });
        if (!res.ok) throw new Error(await res.text());
        await this.loadLibrary();
        this.showUploadModal = false;
        this.olSelected = null;
        this.olQuery = '';
        this.uploadManual = false;
    } catch (e) {
        this.uploadError = e.message;
    } finally {
        this.uploading = false;
    }
},
```

- [ ] **Step 4: Replace the upload modal HTML**

Find the existing upload modal `<div>` and replace its inner form with:

```html
<!-- Book search -->
<template x-if="!uploadManual && !olSelected">
    <div>
        <label class="block text-sm font-medium mb-1">Search for a book</label>
        <div class="flex gap-2">
            <input
                type="text"
                x-model="olQuery"
                @input.debounce.400ms="searchOL()"
                placeholder="Title or author..."
                class="flex-1 border rounded px-3 py-2 text-sm"
            />
            <span x-show="olSearching" class="text-sm text-gray-400 self-center">Searching…</span>
        </div>
        <!-- Results -->
        <ul x-show="olResults.length > 0" class="mt-2 border rounded divide-y max-h-64 overflow-y-auto">
            <template x-for="r in olResults" :key="r.ol_id">
                <li
                    class="flex items-center gap-3 px-3 py-2 hover:bg-gray-50 cursor-pointer"
                    @click="selectOLResult(r)"
                >
                    <img x-show="r.cover_url" :src="r.cover_url" class="w-8 h-12 object-cover rounded" />
                    <div class="flex-1 min-w-0">
                        <div class="font-medium text-sm truncate" x-text="r.title"></div>
                        <div class="text-xs text-gray-500 truncate" x-text="[r.author, r.series_name ? `${r.series_name} #${r.series_position}` : ''].filter(Boolean).join(' · ')"></div>
                    </div>
                </li>
            </template>
        </ul>
        <button
            class="mt-3 text-xs text-gray-400 underline"
            @click="uploadManual = true"
        >Add manually instead</button>
    </div>
</template>

<!-- Selected OL result confirmation -->
<template x-if="!uploadManual && olSelected">
    <div class="flex items-center gap-3 p-3 border rounded bg-gray-50">
        <img x-show="olSelected.cover_url" :src="olSelected.cover_url" class="w-10 h-14 object-cover rounded" />
        <div class="flex-1">
            <div class="font-medium text-sm" x-text="olSelected.title"></div>
            <div class="text-xs text-gray-500" x-text="[olSelected.author, olSelected.series_name].filter(Boolean).join(' · ')"></div>
        </div>
        <button class="text-xs text-gray-400 underline" @click="clearOLSelection()">Change</button>
    </div>
</template>

<!-- Manual fallback -->
<template x-if="uploadManual">
    <div class="space-y-3">
        <div>
            <label class="block text-sm font-medium mb-1">Title <span class="text-red-500">*</span></label>
            <input type="text" x-model="manualTitle" class="w-full border rounded px-3 py-2 text-sm" />
        </div>
        <div>
            <label class="block text-sm font-medium mb-1">Author</label>
            <input type="text" x-model="manualAuthor" class="w-full border rounded px-3 py-2 text-sm" />
        </div>
        <div class="grid grid-cols-2 gap-3">
            <div>
                <label class="block text-sm font-medium mb-1">Series name</label>
                <input type="text" x-model="manualSeriesName" class="w-full border rounded px-3 py-2 text-sm" />
            </div>
            <div>
                <label class="block text-sm font-medium mb-1">Position</label>
                <input type="number" step="0.5" x-model="manualSeriesPosition" class="w-full border rounded px-3 py-2 text-sm" />
            </div>
        </div>
        <button class="text-xs text-gray-400 underline" @click="uploadManual = false">Search instead</button>
    </div>
</template>

<!-- File picker (always shown) -->
<div class="mt-4">
    <label class="block text-sm font-medium mb-1">Epub file <span class="text-red-500">*</span></label>
    <input type="file" accept=".epub" @change="uploadFile = $event.target.files[0]" class="w-full text-sm" />
</div>

<!-- Upload button -->
<div class="mt-4 flex justify-end gap-2">
    <button @click="showUploadModal = false" class="px-4 py-2 text-sm border rounded">Cancel</button>
    <button
        @click="uploadBook()"
        :disabled="uploading || (!olSelected && !uploadManual) || (uploadManual && !manualTitle) || !uploadFile"
        class="px-4 py-2 text-sm bg-blue-600 text-white rounded disabled:opacity-50"
        x-text="uploading ? 'Uploading…' : 'Upload'"
    ></button>
</div>
<p x-show="uploadError" x-text="uploadError" class="mt-2 text-sm text-red-500"></p>
```

- [ ] **Step 5: Update library view to group by series_name**

The library view already groups by `series` — confirm that `series.name` is used for display (it will now show the OL series name or the manual series name). No structural change needed since `load_library` still returns `Library { series: Series[] }`.

If the library view uses `series.id` for routing (e.g. in API calls for delete/graph), update those to use `series.id` (which is now `canonical_series_id`). Search for hardcoded `/library/series/` route constructions and update to use `canonical_series_id`.

Also update any calls to old book endpoints like `/library/series/{id}/books/{index}` → `/library/books/{canonical_book_id}` using `book.canonical_book_id`.

- [ ] **Step 6: Manual smoke test**

```bash
poetry run uvicorn src.main:app --reload
```
Open the app in a browser. Try searching "the name of the wind" — should show OL results. Select one, attach an epub, upload. Verify library updates.

- [ ] **Step 7: Commit**

```bash
git add src/static/index.html
git commit -m "feat(frontend): replace upload form with Open Library search modal"
```

---

## Task 11: Final Wiring and Smoke Test

**Files:**
- Modify: `src/main.py` (remove old series-scoped endpoints)

- [ ] **Step 1: Remove old endpoints that are now replaced**

Remove or comment out the following from `src/main.py`:
- `POST /library/series` (create series)
- `POST /library/series/{series_id}/books` (old upload)
- `DELETE /library/series/{series_id}/books/{book_index}` (replaced by `/library/books/{id}`)
- `PATCH /library/series/{series_id}/books/{book_index}` (replaced by `/library/books/{id}`)

- [ ] **Step 2: Full integration smoke test**

```bash
poetry run uvicorn src.main:app --reload &
# Check library loads
curl -H "Authorization: Bearer <token>" http://localhost:8000/library
# Check OL search
curl "http://localhost:8000/books/search?q=mistborn"
```
Expected: library returns `{"series": []}` for a new user; search returns OL results.

Kill server: `pkill -f uvicorn`

- [ ] **Step 3: Final commit**

```bash
git add src/main.py
git commit -m "refactor(api): remove legacy series-scoped endpoints"
```

---

## Self-Review

**Spec coverage check:**

| Spec requirement | Task |
|-----------------|------|
| `canonical_books` table | Task 1 |
| `user_books` table | Task 1 |
| `knowledge` re-keyed by `canonical_series_id` | Task 1, Task 6 |
| `series`/`books` tables dropped | Task 1 (cleared), Task 11 |
| OL search service | Task 3 |
| `GET /books/search` endpoint | Task 4 |
| Library manager using new tables | Task 5 |
| Knowledge store drops `user_id` | Task 6 |
| Pipeline drops `user_id` | Task 7 |
| `POST /library/books` unified upload | Task 8 |
| Skip extraction if KB already exists | Task 8 |
| Delete endpoints updated | Task 9 |
| Knowledge/graph/query endpoints updated | Task 9 |
| Knowledge deleted only if no other users | Task 9 |
| Frontend search modal | Task 10 |
| Manual fallback | Task 10 |
| Library groups by series_name | Task 10 |
| `filter_to_progress` stays compatible | Task 6 (interface unchanged) |

**Design refinement applied:** Knowledge keyed by `canonical_series_id` (not `canonical_book_id`) — series accumulates across books, consistent with existing `KnowledgeBase` model.
