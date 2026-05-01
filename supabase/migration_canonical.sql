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

-- Index for canonical_series_id lookups (used by library manager joins)
CREATE INDEX IF NOT EXISTS idx_canonical_books_canonical_series_id
    ON canonical_books (canonical_series_id);

-- knowledge: re-key by canonical_series_id, drop user_id
-- IMPORTANT: Run DELETE FROM knowledge; first to clear old composite-PK rows.
-- Order: drop RLS policy → drop FK → drop PK → drop column → rename → add PK → new policy.
DROP POLICY IF EXISTS "Users can manage their own knowledge" ON knowledge;
ALTER TABLE knowledge DROP CONSTRAINT IF EXISTS knowledge_series_id_user_id_fkey;
ALTER TABLE knowledge DROP CONSTRAINT IF EXISTS knowledge_pkey;
ALTER TABLE knowledge DROP COLUMN IF EXISTS user_id;
ALTER TABLE knowledge RENAME COLUMN series_id TO canonical_series_id;
ALTER TABLE knowledge ADD PRIMARY KEY (canonical_series_id);
-- Knowledge is now shared; no per-user RLS needed (access controlled at API layer via user_books)
ALTER TABLE knowledge DISABLE ROW LEVEL SECURITY;
