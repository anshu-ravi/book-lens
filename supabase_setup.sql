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
    text TEXT NOT NULL,
    embedding VECTOR(1536),
    metadata JSONB,
    FOREIGN KEY (series_id, user_id) REFERENCES series(id, user_id) ON DELETE CASCADE
);

-- 3. Create Vector Search RPC (User Isolated)
CREATE OR REPLACE FUNCTION match_vectors (
  query_embedding VECTOR(1536),
  match_threshold FLOAT,
  match_count INT,
  filter_user_id UUID,
  filter_series_id TEXT DEFAULT NULL,
  filter_book_index INT DEFAULT NULL,
  filter_chapter_index INT DEFAULT NULL
)
RETURNS TABLE (
  text TEXT,
  book_index INT,
  chapter_index INT,
  metadata JSONB,
  similarity FLOAT
)
LANGUAGE plpgsql
AS $$
BEGIN
  RETURN QUERY
  SELECT
    vectors.text,
    vectors.book_index,
    vectors.chapter_index,
    vectors.metadata,
    1 - (vectors.embedding <=> query_embedding) AS similarity
  FROM vectors
  WHERE 
    vectors.user_id = filter_user_id
    AND (filter_series_id IS NULL OR vectors.series_id = filter_series_id)
    AND (filter_book_index IS NULL OR vectors.book_index = filter_book_index)
    AND (filter_chapter_index IS NULL OR vectors.chapter_index <= filter_chapter_index)
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
