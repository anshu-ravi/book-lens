"""Spoiler-safe chunk retrieval.

Builds a filter from the current library state so that:
  - COMPLETED books: all chapters are searchable
  - READING books: only chapters up to current_chapter_index are searchable
  - NOT_STARTED books: excluded entirely
"""

from src.ingestion.embedder import embed_query
from src.models import BookStatus, Series
from src.vector_store.base import SearchResult, VectorStore


def build_supabase_filter(series: Series) -> list[dict] | None:
    """Build filter conditions for the match_vectors RPC.

    Returns a list of {book_index, max_chapter?} dicts — one per in-scope book.
    Completed books omit max_chapter (all chapters allowed).
    Returns None if no books are in scope (all NOT_STARTED).
    """
    conditions = []
    for book in series.books:
        if book.status == BookStatus.NOT_STARTED:
            continue

        if book.status == BookStatus.COMPLETED:
            conditions.append({"book_index": book.index})
        elif book.status == BookStatus.READING:
            max_chapter = book.current_chapter_index if book.current_chapter_index is not None else 0
            conditions.append({"book_index": book.index, "max_chapter": max_chapter})

    return conditions if conditions else None


def retrieve_chunks(
    question: str,
    series: Series,
    vector_store: VectorStore,
    user_id: str,
    top_k: int = 5,
) -> list[SearchResult]:
    """Embed a question and retrieve the top-k spoiler-safe chunks.

    Returns an empty list if no books in the series are in scope (all
    NOT_STARTED), avoiding any search against unread content.

    Args:
        question: The user's question to answer.
        series: Series to search within.
        vector_store: VectorStore backend to query.
        user_id: The authenticated user's ID.
        top_k: Maximum number of chunks to return.

    Returns:
        Ranked list of SearchResult objects, highest relevance first.
    """
    sf = build_supabase_filter(series)
    if sf is None:
        return []

    embedding = embed_query(question)
    return vector_store.search(
        embedding=embedding,
        series_id=series.id,
        user_id=user_id,
        filters={"supabase_filter": sf},
        top_k=top_k,
    )
