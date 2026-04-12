"""Abstract VectorStore interface and shared data types."""

from abc import ABC, abstractmethod
from dataclasses import dataclass

from src.models import ChunkRecord


@dataclass
class SearchResult:
    """A single result returned from a vector search."""

    chunk_id: str
    text: str
    chapter_index: int
    chapter_label: str
    series_id: str
    book_index: int
    score: float


class VectorStore(ABC):
    """Abstract interface for vector storage backends.

    Implementations must support upsert, search, and book-level deletion.
    All methods are synchronous; swap to async if needed in a future phase.
    """

    @abstractmethod
    def upsert(
        self,
        chunks: list[ChunkRecord],
        embeddings: list[list[float]],
        series_id: str,
        book_index: int,
    ) -> int:
        """Store chunk embeddings with metadata.

        Args:
            chunks: ChunkRecords from the chunking pipeline.
            embeddings: One embedding vector per chunk (same order).
            series_id: Identifier for the series (used as collection name).
            book_index: 0-based position of the book within the series.

        Returns:
            Number of points successfully upserted.
        """

    @abstractmethod
    def search(
        self,
        embedding: list[float],
        series_id: str,
        filters: dict,
        top_k: int = 5,
    ) -> list[SearchResult]:
        """Semantic search within a series collection.

        Args:
            embedding: Query vector (same model as used during indexing).
            series_id: Collection to search within.
            filters: Backend-specific filter dict (built by the query engine).
            top_k: Maximum number of results to return.

        Returns:
            Ranked list of SearchResult objects.
        """

    @abstractmethod
    def delete_book(self, series_id: str, book_index: int) -> None:
        """Remove all vectors for a specific book.

        Args:
            series_id: Collection containing the book's vectors.
            book_index: Book to delete (all its chunks are removed).
        """
