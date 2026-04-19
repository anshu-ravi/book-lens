"""Qdrant Cloud implementation of the VectorStore interface."""

import uuid

from qdrant_client import QdrantClient
from qdrant_client.http.models import (
    Distance,
    FieldCondition,
    Filter,
    FilterSelector,
    MatchValue,
    PayloadSchemaType,
    PointStruct,
    VectorParams,
)

from src.models import ChunkRecord
from src.vector_store.base import SearchResult, VectorStore

# MiniLM (all-MiniLM-L6-v2) output dimension
_VECTOR_SIZE = 384
_UUID_NAMESPACE = uuid.NAMESPACE_DNS


def _chunk_point_id(series_id: str, book_index: int, chunk_id: str) -> str:
    """Generate a deterministic UUID for a chunk point.

    Using uuid5 ensures re-indexing the same chunk always produces the same ID,
    giving extra safety on top of the filter-delete step.

    Args:
        series_id: Series identifier.
        book_index: Book position within the series.
        chunk_id: Chunk identifier from ChunkRecord.

    Returns:
        UUID string suitable for Qdrant point IDs.
    """
    key = f"{series_id}:{book_index}:{chunk_id}"
    return str(uuid.uuid5(_UUID_NAMESPACE, key))


class QdrantVectorStore(VectorStore):
    """VectorStore backed by Qdrant Cloud (or a local Qdrant instance).

    One Qdrant collection is created per series_id. Collections are created
    automatically on first use with cosine distance and 384-dimensional vectors.
    """

    def __init__(self, url: str, api_key: str) -> None:
        """Initialise the Qdrant client.

        Args:
            url: Qdrant cluster URL (e.g. https://xyz.qdrant.io:6333).
            api_key: Qdrant Cloud API key.
        """
        self._client = QdrantClient(url=url, api_key=api_key)

    def _ensure_collection(self, series_id: str) -> None:
        """Create the collection if it does not already exist.

        Args:
            series_id: Used as the collection name.
        """
        existing = {c.name for c in self._client.get_collections().collections}
        if series_id not in existing:
            self._client.create_collection(
                collection_name=series_id,
                vectors_config=VectorParams(size=_VECTOR_SIZE, distance=Distance.COSINE),
            )

        # Payload indexes are required for filtering in Qdrant Cloud.
        # Called every time (idempotent) so existing collections without indexes
        # are patched automatically — e.g. collections created before this fix.
        self._client.create_payload_index(
            collection_name=series_id,
            field_name="book_index",
            field_schema=PayloadSchemaType.INTEGER,
        )
        self._client.create_payload_index(
            collection_name=series_id,
            field_name="chapter_index",
            field_schema=PayloadSchemaType.INTEGER,
        )
        self._client.create_payload_index(
            collection_name=series_id,
            field_name="position",
            field_schema=PayloadSchemaType.INTEGER,
        )

    def upsert(
        self,
        chunks: list[ChunkRecord],
        embeddings: list[list[float]],
        series_id: str,
        book_index: int,
    ) -> int:
        """Delete existing book vectors then upsert new ones in batches of 100.

        Args:
            chunks: ChunkRecords from the chunking pipeline.
            embeddings: One embedding per chunk (same order).
            series_id: Collection name / series identifier.
            book_index: 0-based book position within the series.

        Returns:
            Number of points upserted.
        """
        self._ensure_collection(series_id)
        self.delete_book(series_id, book_index)

        points = [
            PointStruct(
                id=_chunk_point_id(series_id, book_index, chunk.chunk_id),
                vector=embedding,
                payload={
                    "series_id": series_id,
                    "book_index": book_index,
                    "chunk_id": chunk.chunk_id,
                    "chapter_index": chunk.chapter_index,
                    "chapter_label": chunk.chapter_label,
                    "text": chunk.text,
                    "word_count": chunk.word_count,
                    "position": chunk.position,
                },
            )
            for chunk, embedding in zip(chunks, embeddings)
        ]

        batch_size = 100
        for i in range(0, len(points), batch_size):
            self._client.upsert(
                collection_name=series_id,
                points=points[i : i + batch_size],
            )

        return len(points)

    def search(
        self,
        embedding: list[float],
        series_id: str,
        filters: dict,
        top_k: int = 5,
    ) -> list[SearchResult]:
        """Semantic search with optional Qdrant filter.

        Args:
            embedding: Query vector.
            series_id: Collection to search.
            filters: Qdrant Filter object or None (passed directly).
            top_k: Max results to return.

        Returns:
            Ranked SearchResult list (highest score first).
        """
        qdrant_filter: Filter | None = filters.get("qdrant_filter") if filters else None

        # qdrant-client >= 1.7 uses query_points instead of the removed search()
        response = self._client.query_points(
            collection_name=series_id,
            query=embedding,
            query_filter=qdrant_filter,
            limit=top_k,
            with_payload=True,
        )

        return [
            SearchResult(
                chunk_id=hit.payload["chunk_id"],
                text=hit.payload["text"],
                chapter_index=hit.payload["chapter_index"],
                chapter_label=hit.payload["chapter_label"],
                series_id=hit.payload["series_id"],
                book_index=hit.payload["book_index"],
                score=hit.score,
            )
            for hit in response.points
        ]

    def fetch_by_positions(
        self,
        series_id: str,
        book_index: int,
        chapter_index: int,
        positions: list[int],
    ) -> list[SearchResult]:
        """Fetch specific chunks by their position within a chapter.

        Used for neighbor expansion: given a chunk at position N, callers
        pass [N-1, N+1] to retrieve adjacent chunks without a vector query.

        Args:
            series_id: Collection to search.
            book_index: Book containing the chapter.
            chapter_index: Chapter to look within.
            positions: List of 0-based position values to fetch.

        Returns:
            SearchResult list for matching positions (score=0.0 for scroll results).
        """
        existing = {c.name for c in self._client.get_collections().collections}
        if series_id not in existing:
            return []

        self._ensure_collection(series_id)

        from qdrant_client.http.models import Range

        results = []
        for position in positions:
            scroll_filter = Filter(
                must=[
                    FieldCondition(key="book_index", match=MatchValue(value=book_index)),
                    FieldCondition(key="chapter_index", match=MatchValue(value=chapter_index)),
                    FieldCondition(key="position", range=Range(gte=position, lte=position)),
                ]
            )
            response, _ = self._client.scroll(
                collection_name=series_id,
                scroll_filter=scroll_filter,
                limit=1,
                with_payload=True,
            )
            for point in response:
                p = point.payload or {}
                results.append(
                    SearchResult(
                        chunk_id=p["chunk_id"],
                        text=p["text"],
                        chapter_index=p["chapter_index"],
                        chapter_label=p["chapter_label"],
                        series_id=p["series_id"],
                        book_index=p["book_index"],
                        score=0.0,
                    )
                )
        return results

    def delete_book(self, series_id: str, book_index: int) -> None:
        """Remove all points for a given book from the collection.

        A no-op if the collection does not exist yet.

        Args:
            series_id: Collection name.
            book_index: Book whose chunks should be removed.
        """
        existing = {c.name for c in self._client.get_collections().collections}
        if series_id not in existing:
            return

        self._client.delete(
            collection_name=series_id,
            points_selector=FilterSelector(
                filter=Filter(
                    must=[
                        FieldCondition(
                            key="book_index",
                            match=MatchValue(value=book_index),
                        )
                    ]
                )
            ),
        )
