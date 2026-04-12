"""Book indexing pipeline: embed chunks and store in the vector store."""

from src.ingestion.embedder import embed_chunks
from src.models import ChunkRecord
from src.vector_store.base import VectorStore


def index_book(
    chunks: list[ChunkRecord],
    series_id: str,
    book_index: int,
    vector_store: VectorStore,
) -> int:
    """Embed all chunks for a book and upsert them into the vector store.

    Existing vectors for this (series_id, book_index) pair are deleted before
    upserting, making this operation idempotent — safe to call multiple times.

    Args:
        chunks: All ChunkRecords for the book (from the chunking pipeline).
        series_id: Series identifier (e.g. "red-rising", "standalone").
        book_index: 0-based position of the book within the series.
        vector_store: VectorStore backend to write into.

    Returns:
        Number of chunks successfully indexed.
    """
    if not chunks:
        return 0

    embeddings = embed_chunks(chunks)
    return vector_store.upsert(chunks, embeddings, series_id, book_index)
