-- Migration: add book_chunks table and match_chunks RPC for vector search
-- Run this once in the Supabase SQL editor before ingesting any books.

-- Enable pgvector extension (safe to re-run)
CREATE EXTENSION IF NOT EXISTS vector;

-- Table: stores text chunks with embeddings (384-dim all-MiniLM-L6-v2)
CREATE TABLE IF NOT EXISTS book_chunks (
  id             uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id        uuid        NOT NULL,
  series_id      text        NOT NULL,
  book_id        uuid        NOT NULL,
  chapter_index  int         NOT NULL,
  chapter_label  text        NOT NULL,
  chunk_position int         NOT NULL,
  text           text        NOT NULL,
  embedding      vector(384),
  created_at     timestamptz DEFAULT now()
);

-- ANN index for fast cosine similarity search
CREATE INDEX IF NOT EXISTS book_chunks_embedding_idx
  ON book_chunks USING ivfflat (embedding vector_cosine_ops)
  WITH (lists = 100);

-- Supporting indexes for common filter patterns
CREATE INDEX IF NOT EXISTS book_chunks_series_user_idx
  ON book_chunks (series_id, user_id, chapter_index);

-- RPC: vector similarity search with spoiler safety
-- Called by ChunkStore.search() via supabase.rpc("match_chunks", {...})
CREATE OR REPLACE FUNCTION match_chunks(
  query_embedding vector(384),
  match_series_id text,
  match_user_id   uuid,
  chapter_cutoff  int,
  match_count     int
)
RETURNS TABLE (
  id             uuid,
  text           text,
  chapter_index  int,
  chapter_label  text,
  chunk_position int,
  similarity     float
)
LANGUAGE sql STABLE AS $$
  SELECT id, text, chapter_index, chapter_label, chunk_position,
         1 - (embedding <=> query_embedding) AS similarity
  FROM book_chunks
  WHERE series_id     = match_series_id
    AND user_id       = match_user_id
    AND chapter_index <= chapter_cutoff
  ORDER BY embedding <=> query_embedding
  LIMIT match_count;
$$;
