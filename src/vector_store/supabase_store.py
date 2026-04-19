"""Supabase (pgvector) implementation of the VectorStore interface."""

import uuid
from typing import Any, Optional

from supabase import Client, create_client
from src.models import ChunkRecord
from src.vector_store.base import SearchResult, VectorStore

class SupabaseVectorStore(VectorStore):
    """VectorStore backed by Supabase Postgres with pgvector.
    
    Uses a 'vectors' table and a 'match_vectors' RPC for semantic search.
    """

    def __init__(self, url: str, key: str) -> None:
        """Initialise the Supabase client.
        
        Args:
            url: Supabase project URL.
            key: Supabase API key (service_role or anon with appropriate RLS).
        """
        self._client: Client = create_client(url, key)

    def upsert(
        self,
        chunks: list[ChunkRecord],
        embeddings: list[list[float]],
        series_id: str,
        book_index: int,
        user_id: str,
    ) -> int:
        """Upsert book vectors into the 'vectors' table for a specific user.
        
        Args:
            chunks: ChunkRecords from the chunking pipeline.
            embeddings: One embedding per chunk.
            series_id: Series identifier.
            book_index: 0-based book position.
            user_id: Current user's ID.
            
        Returns:
            Number of points upserted.
        """
        # Delete existing vectors for this book and user to ensure idempotency
        self.delete_book(series_id, book_index, user_id)

        records = [
            {
                "user_id": user_id,
                "series_id": series_id,
                "book_index": book_index,
                "chapter_index": chunk.chapter_index,
                "chapter_label": chunk.chapter_label,
                "chunk_id": chunk.chunk_id,
                "text": chunk.text,
                "embedding": embedding,
                "metadata": {
                    "word_count": chunk.word_count,
                    "position": chunk.position,
                },
            }
            for chunk, embedding in zip(chunks, embeddings)
        ]

        # Batch upsert
        batch_size = 100
        for i in range(0, len(records), batch_size):
            self._client.table("vectors").insert(records[i : i + batch_size]).execute()

        return len(records)

    def search(
        self,
        embedding: list[float],
        series_id: str,
        user_id: str,
        filters: dict,
        top_k: int = 5,
    ) -> list[SearchResult]:
        """Semantic search using user-isolated match_vectors RPC."""
        # Extract book_index and chapter_index if they are in filters
        # supabase_filter might be [{"book_index": X}, {"book_index": Y, "max_chapter": Z}]
        # For simplicity in RPC, we typically search within a series first.
        # If the RPC needs more granular filtering, we could extend it.
        # But my new match_vectors RPC takes filter_series_id, filter_book_index, filter_chapter_index.
        
        # Default to series search
        supabase_filter = filters.get("supabase_filter")

        response = self._client.rpc(
            "match_vectors",
            {
                "query_embedding": embedding,
                "match_threshold": 0.2,
                "match_count": top_k,
                "filter_user_id": user_id,
                "filter_series_id": series_id,
                "filter_conditions": supabase_filter,
            }
        ).execute()

        return [
            SearchResult(
                chunk_id=hit["chunk_id"] if "chunk_id" in hit else f"chunk_{i}",
                text=hit["text"],
                chapter_index=hit["chapter_index"],
                chapter_label=hit["chapter_label"] if "chapter_label" in hit else f"Ch {hit['chapter_index']}",
                series_id=series_id,
                book_index=hit["book_index"],
                score=hit["similarity"],
            )
            for i, hit in enumerate(response.data)
        ]

    def fetch_by_positions(
        self,
        series_id: str,
        book_index: int,
        chapter_index: int,
        user_id: str,
        positions: list[int],
    ) -> list[SearchResult]:
        """Fetch chunks by position for a user."""
        response = (
            self._client.table("vectors")
            .select("*")
            .filter("series_id", "eq", series_id)
            .filter("user_id", "eq", user_id)
            .filter("book_index", "eq", book_index)
            .filter("chapter_index", "eq", chapter_index)
            .filter("metadata->>position", "in", f"({','.join(map(str, positions))})")
            .execute()
        )
        
        return [
            SearchResult(
                chunk_id=hit["chunk_id"],
                text=hit["text"],
                chapter_index=hit["chapter_index"],
                chapter_label=hit.get("chapter_label") or "",
                series_id=hit["series_id"],
                book_index=hit["book_index"],
                score=0.0,
            )
            for hit in response.data
        ]

    def fetch_chapter_chunks(
        self,
        series_id: str,
        book_index: int,
        chapter_index: int,
        user_id: str,
        limit: int = 10,
    ) -> list[SearchResult]:
        """Fetch chunks for a specific chapter and user."""
        response = (
            self._client.table("vectors")
            .select("*")
            .filter("series_id", "eq", series_id)
            .filter("user_id", "eq", user_id)
            .filter("book_index", "eq", book_index)
            .filter("chapter_index", "eq", chapter_index)
            .limit(limit)
            .execute()
        )

        return [
            SearchResult(
                chunk_id=hit["chunk_id"],
                text=hit["text"],
                chapter_index=hit["chapter_index"],
                chapter_label=hit.get("chapter_label") or "",
                series_id=hit["series_id"],
                book_index=hit["book_index"],
                score=0.0,
            )
            for hit in response.data
        ]

    def delete_book(self, series_id: str, book_index: int, user_id: str) -> None:
        """Delete book vectors for a user."""
        (
            self._client.table("vectors")
            .delete()
            .filter("series_id", "eq", series_id)
            .filter("user_id", "eq", user_id)
            .filter("book_index", "eq", book_index)
            .execute()
        )

    def delete_series(self, series_id: str, user_id: str) -> None:
        """Delete all vectors for a series and user."""
        (
            self._client.table("vectors")
            .delete()
            .filter("series_id", "eq", series_id)
            .filter("user_id", "eq", user_id)
            .execute()
        )
