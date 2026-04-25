# Canonical Books & Shared Knowledge Extraction

**Date:** 2026-04-25  
**Status:** Approved

## Problem

Knowledge extraction currently runs per-user per-book. Two users uploading the same epub both trigger full Claude extraction, paying the cost twice and storing duplicate data. Additionally, users must manually type series names and book indices — creating friction and inconsistent naming.

## Goal

1. Extract knowledge once per book, shared across all users who add the same book.
2. Replace manual series/book entry with Open Library search (type title → pick from results).
3. Keep reading progress, epub files, and vector embeddings per-user.

---

## Database Schema

### New tables

```sql
canonical_books
  id                TEXT  PRIMARY KEY   -- OL work ID (e.g. "OL12345W"), UUID for manual entries
  ol_id             TEXT  NULLABLE      -- Open Library work ID; null for manual entries
  title             TEXT  NOT NULL
  author            TEXT  NULLABLE
  series_name       TEXT  NULLABLE
  series_position   FLOAT NULLABLE      -- supports 1, 2, 2.5 etc.
  cover_url         TEXT  NULLABLE      -- Open Library cover URL
  created_at        TIMESTAMPTZ DEFAULT now()

user_books
  id                UUID  PRIMARY KEY DEFAULT gen_random_uuid()
  user_id           TEXT  NOT NULL
  canonical_book_id TEXT  NOT NULL REFERENCES canonical_books(id)
  status            TEXT  NOT NULL DEFAULT 'not_started'  -- not_started | reading | completed
  current_chapter_index INT NULLABLE
  epub_path         TEXT  NULLABLE      -- {user_id}/{canonical_book_id}/book.epub in Storage
  created_at        TIMESTAMPTZ DEFAULT now()
  UNIQUE (user_id, canonical_book_id)
```

### Modified tables

```sql
-- knowledge: drop user_id, re-key by canonical_book_id
knowledge
  canonical_book_id TEXT  PRIMARY KEY REFERENCES canonical_books(id)
  data              JSONB NOT NULL
```

### Dropped tables

- `series` — series grouping is now derived dynamically from `canonical_books.series_name`
- `books` — replaced by `user_books` + `canonical_books`

### What stays per-user

- Vector embeddings (Supabase vector store, unchanged)
- Epub files in Supabase Storage (`{user_id}/{canonical_book_id}/book.epub`)
- Reading progress (`user_books.status`, `user_books.current_chapter_index`)

### What becomes shared

- Book metadata (`canonical_books`)
- Extracted knowledge (`knowledge`)

---

## Upload Flow

### Primary path (Open Library search)

1. User types a title in the search box.
2. Frontend calls `GET /books/search?q=<title>`.
3. Backend proxies to Open Library `search.json`, returns top 10 results: `{ol_id, title, author, series_name, series_position, cover_url}`.
4. User clicks a result — form pre-fills, `canonical_book_id = ol_id`.
5. User selects epub file and submits `POST /library/books`.
6. Backend:
   - Upserts `canonical_books` row (idempotent on `ol_id`).
   - Creates `user_books` row for this user.
   - Parses epub, indexes vectors per-user (unchanged).
   - Checks `knowledge` table for `canonical_book_id`:
     - **Exists** → skip extraction entirely.
     - **Missing** → trigger background extraction, store against `canonical_book_id`.

### Manual fallback

- User clicks "Add manually" → types title, author, series name, series position.
- Backend generates a UUID as `canonical_book_id` (no `ol_id`).
- Same flow from step 5 onward.
- Knowledge is not shared for manual entries (no stable canonical ID to match on).

### Series grouping

No explicit series creation step. The library view groups `user_books` by `canonical_books.series_name`. Books with no series appear in a standalone section.

---

## Knowledge Sharing & Spoiler Filtering

### Extraction

- `extract_book_knowledge()` and `save_knowledge()` drop the `user_id` parameter.
- `app.state.extracting_books` key changes from `(series_id, book_index, user_id)` → `canonical_book_id`.
- Concurrent-upload guard: if extraction is already running for a `canonical_book_id`, the second upload skips triggering a new task.

### Spoiler filtering

`filter_to_progress` signature changes:

```python
# Before
def filter_to_progress(kb: KnowledgeBase, series: Series) -> KnowledgeBase

# After
def filter_to_progress(kb: KnowledgeBase, user_books: list[UserBook]) -> KnowledgeBase
```

`UserBook` carries `canonical_book_id`, `status`, `current_chapter_index`. The KB's `ChapterRef` objects use `book_index` — derived from the user's ordered list of books in a series (sorted by `series_position`).

Graph and digest endpoints load the shared KB then filter to the requesting user's progress before returning — same pattern as today.

---

## API Changes

### New

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/books/search?q=` | Proxy to Open Library search, returns top 10 results |
| `POST` | `/library/books` | Unified upload (replaces series-scoped upload) |

### Removed

| Method | Path | Reason |
|--------|------|--------|
| `POST` | `/library/series` | Series creation no longer needed |
| `POST` | `/library/series/{series_id}/books` | Replaced by `/library/books` |

### Modified

| Before | After | Change |
|--------|-------|--------|
| `DELETE /library/series/{series_id}` | `DELETE /library/series/{series_name_slug}` | Removes user's `user_books` for that series; deletes `knowledge` only if no other users reference any `canonical_book_id` in that series |
| `DELETE /library/series/{id}/books/{index}` | `DELETE /library/books/{canonical_book_id}` | Removes `user_books` row; same knowledge-safety check |
| `PATCH /library/series/{id}/books/{index}` | `PATCH /library/books/{canonical_book_id}` | Updates `status` + `current_chapter_index` in `user_books` |
| All knowledge/graph/query endpoints using `series_id` | Use `series_name_slug` for series-level ops, `canonical_book_id` for book-level ops | — |

---

## Frontend Changes

- Upload modal: search box + results list replaces the manual series/title form. "Add manually" toggle reveals the old fields.
- Library view: groups by `series_name` dynamically (no series rows).
- Book cover extraction: use `cover_url` from Open Library where available; existing epub cover extraction remains as fallback.

---

## Out of Scope (Future)

- Goodreads URL as an input method
- Admin-curated canonical book catalogue
- Sharing vector embeddings across users
