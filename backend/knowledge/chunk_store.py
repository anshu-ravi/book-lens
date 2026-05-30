"""Chunk storage and vector search using Supabase pgvector."""

import logging
import uuid
from typing import Any

from backend.knowledge.embedder import Embedder
from backend.models import ChunkRecord
from backend.supabase_client import get_supabase_client

logger = logging.getLogger(__name__)


def chunk_text(text: str, chapter_index: int, chapter_label: str) -> list[ChunkRecord]:
    """Split chapter text into overlapping chunks at paragraph boundaries.

    Args:
        text: Full chapter text (paragraphs separated by \\n\\n).
        chapter_index: Chapter index (0-based).
        chapter_label: Chapter label.

    Returns:
        List of ChunkRecord objects.
    """
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    target_size = 400  # words — matches chunking strategy in docs/learnings/chunking-strategy.md
    overlap = 50       # words kept from end of previous chunk

    chunks: list[ChunkRecord] = []
    current_words: list[str] = []
    position = 0

    for paragraph in paragraphs:
        para_words = paragraph.split()

        if current_words and len(current_words) + len(para_words) > target_size:
            chunk_str = " ".join(current_words)
            chunks.append(
                ChunkRecord(
                    chunk_id=str(uuid.uuid4()),
                    chapter_index=chapter_index,
                    chapter_label=chapter_label,
                    text=chunk_str,
                    word_count=len(current_words),
                    position=position,
                )
            )
            position += 1
            current_words = current_words[-overlap:] if overlap > 0 else []

        current_words.extend(para_words)

    if current_words:
        chunks.append(
            ChunkRecord(
                chunk_id=str(uuid.uuid4()),
                chapter_index=chapter_index,
                chapter_label=chapter_label,
                text=" ".join(current_words),
                word_count=len(current_words),
                position=position,
            )
        )

    return chunks


class ChunkStore:
    """Store and retrieve text chunks with vector embeddings via Supabase pgvector.

    Requires the following Supabase setup (run once in the SQL editor):

        CREATE EXTENSION IF NOT EXISTS vector;

        CREATE TABLE IF NOT EXISTS book_chunks (
          id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          user_id        uuid NOT NULL,
          series_id      text NOT NULL,
          book_id        uuid NOT NULL,
          chapter_index  int  NOT NULL,
          chapter_label  text NOT NULL,
          chunk_position int  NOT NULL,
          text           text NOT NULL,
          embedding      vector(384),
          created_at     timestamptz DEFAULT now()
        );

        CREATE INDEX IF NOT EXISTS book_chunks_embedding_idx
          ON book_chunks USING ivfflat (embedding vector_cosine_ops)
          WITH (lists = 100);

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
          WHERE series_id = match_series_id
            AND user_id   = match_user_id
            AND chapter_index <= chapter_cutoff
          ORDER BY embedding <=> query_embedding
          LIMIT match_count;
        $$;
    """

    _BATCH_SIZE = 100

    def __init__(self) -> None:
        """Initialize with shared embedder and Supabase client."""
        self.embedder = Embedder()
        self.client = get_supabase_client()

    def upsert_chapters(
        self,
        user_id: str,
        series_id: str,
        book_id: str,
        chapters: list[tuple[int, str, str]],
    ) -> int:
        """Chunk, embed, and upsert all chapters for a book.

        Deletes any existing chunks for the book first (idempotent).

        Args:
            user_id: User identifier.
            series_id: Series identifier.
            book_id: Book identifier.
            chapters: List of (chapter_index, chapter_label, text) tuples.

        Returns:
            Total number of chunks stored.
        """
        # Clear existing chunks for this book so re-ingestion is clean
        try:
            self.client.table("book_chunks").delete().filter(
                "book_id", "eq", book_id
            ).filter("user_id", "eq", user_id).execute()
        except Exception as e:
            logger.warning(f"Failed to clear existing chunks: {e}")

        all_chunks: list[ChunkRecord] = []
        for chapter_index, chapter_label, text in chapters:
            all_chunks.extend(chunk_text(text, chapter_index, chapter_label))

        if not all_chunks:
            return 0

        texts = [c.text for c in all_chunks]
        embeddings = self.embedder.embed_batch(texts)

        rows = [
            {
                "id": chunk.chunk_id,
                "user_id": user_id,
                "series_id": series_id,
                "book_id": book_id,
                "chapter_index": chunk.chapter_index,
                "chapter_label": chunk.chapter_label,
                "chunk_position": chunk.position,
                "text": chunk.text,
                "embedding": embedding,
            }
            for chunk, embedding in zip(all_chunks, embeddings)
        ]

        for i in range(0, len(rows), self._BATCH_SIZE):
            self.client.table("book_chunks").upsert(rows[i : i + self._BATCH_SIZE]).execute()

        logger.info(f"Upserted {len(rows)} chunks for book {book_id}")
        return len(rows)

    def search(
        self,
        user_id: str,
        series_id: str,
        query_text: str,
        up_to_chapter: int,
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        """Find relevant passages using vector similarity.

        Args:
            user_id: User identifier.
            series_id: Series identifier.
            query_text: Question or search phrase to embed.
            up_to_chapter: Spoiler cutoff — only return chunks from chapters at or before this index.
            top_k: Number of results to return.

        Returns:
            List of dicts with keys: text, chapter_index, chapter_label, chunk_position, similarity.
        """
        query_embedding = self.embedder.embed(query_text)

        try:
            result = self.client.rpc(
                "match_chunks",
                {
                    "query_embedding": query_embedding,
                    "match_series_id": series_id,
                    "match_user_id": user_id,
                    "chapter_cutoff": up_to_chapter,
                    "match_count": top_k,
                },
            ).execute()
            return result.data or []
        except Exception as e:
            logger.error(f"Vector search failed: {e}", exc_info=True)
            return []
