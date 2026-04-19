-- BookLens Supabase Setup Script (Multi-User Support)
-- Run this in your Supabase SQL Editor to create the necessary tables and vector search function.

-- 1. Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- 2. Create tables with user isolation
CREATE TABLE IF NOT EXISTS series (
    id TEXT NOT NULL,
    user_id UUID NOT NULL DEFAULT auth.uid(),
    name TEXT NOT NULL,
    PRIMARY KEY (id, user_id)
);

CREATE TABLE IF NOT EXISTS books (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id UUID NOT NULL DEFAULT auth.uid(),
    series_id TEXT NOT NULL,
    index INT NOT NULL,
    title TEXT NOT NULL,
    status TEXT NOT NULL,
    current_chapter_index INT,
    has_cover BOOLEAN DEFAULT false,
    chapters JSONB,
    UNIQUE(user_id, series_id, index),
    -- Note: ForeignKey to series needs both components for full isolation
    FOREIGN KEY (series_id, user_id) REFERENCES series(id, user_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS knowledge (
    series_id TEXT NOT NULL,
    user_id UUID NOT NULL DEFAULT auth.uid(),
    data JSONB NOT NULL,
    PRIMARY KEY (series_id, user_id),
    FOREIGN KEY (series_id, user_id) REFERENCES series(id, user_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS vectors (
    id BIGSERIAL PRIMARY KEY,
    user_id UUID NOT NULL DEFAULT auth.uid(),
    series_id TEXT NOT NULL,
    book_index INT NOT NULL,
    chapter_index INT NOT NULL,
    chapter_label TEXT,
    chunk_id TEXT,
    text TEXT NOT NULL,
    embedding VECTOR(384),
    metadata JSONB,
    FOREIGN KEY (series_id, user_id) REFERENCES series(id, user_id) ON DELETE CASCADE
);

-- 3. Create Vector Search RPC (User Isolated, spoiler-safe)
-- filter_conditions: JSONB array of {book_index, max_chapter?}
-- e.g. [{"book_index": 0, "max_chapter": 7}, {"book_index": 1}]
-- Omit max_chapter for completed books (all chapters allowed).
CREATE OR REPLACE FUNCTION match_vectors (
  query_embedding VECTOR(384),
  match_threshold FLOAT,
  match_count INT,
  filter_user_id UUID,
  filter_series_id TEXT DEFAULT NULL,
  filter_conditions JSONB DEFAULT NULL
)
RETURNS TABLE (
  chunk_id TEXT,
  text TEXT,
  book_index INT,
  chapter_index INT,
  chapter_label TEXT,
  metadata JSONB,
  similarity FLOAT
)
LANGUAGE plpgsql
AS $$
BEGIN
  RETURN QUERY
  SELECT
    vectors.chunk_id,
    vectors.text,
    vectors.book_index,
    vectors.chapter_index,
    vectors.chapter_label,
    vectors.metadata,
    1 - (vectors.embedding <=> query_embedding) AS similarity
  FROM vectors
  WHERE
    vectors.user_id = filter_user_id
    AND (filter_series_id IS NULL OR vectors.series_id = filter_series_id)
    AND (
      filter_conditions IS NULL
      OR EXISTS (
        SELECT 1 FROM jsonb_array_elements(filter_conditions) AS fc
        WHERE (fc->>'book_index')::int = vectors.book_index
        AND (
          fc->>'max_chapter' IS NULL
          OR vectors.chapter_index <= (fc->>'max_chapter')::int
        )
      )
    )
    AND 1 - (vectors.embedding <=> query_embedding) > match_threshold
  ORDER BY vectors.embedding <=> query_embedding
  LIMIT match_count;
END;
$$;

-- 4. Enable Row Level Security (RLS)
ALTER TABLE series ENABLE ROW LEVEL SECURITY;
ALTER TABLE books ENABLE ROW LEVEL SECURITY;
ALTER TABLE knowledge ENABLE ROW LEVEL SECURITY;
ALTER TABLE vectors ENABLE ROW LEVEL SECURITY;

-- 5. Create Policies (Secure Multi-user mode)
-- These policies ensure users can only access data where user_id matches their Auth UID.

CREATE POLICY "Users can manage their own series" ON series 
    FOR ALL USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Users can manage their own books" ON books 
    FOR ALL USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Users can manage their own knowledge" ON knowledge 
    FOR ALL USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Users can manage their own vectors" ON vectors 
    FOR ALL USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);
