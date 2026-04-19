"""Spoiler-safe chunk retrieval.

Builds a Qdrant filter from the current library state so that:
  - COMPLETED books: all chapters are searchable
  - READING books: only chapters up to current_chapter_index are searchable
  - NOT_STARTED books: excluded entirely

The filter is combined with OR (Qdrant `should`) so a question can draw
context from multiple books as long as the content is within read progress.
"""

from qdrant_client.http.models import FieldCondition, Filter, MatchValue, Range

from src.ingestion.embedder import embed_query
from src.models import BookStatus, Series
from src.vector_store.base import SearchResult, VectorStore


def build_qdrant_filter(series: Series) -> Filter | None:
    """Build a Qdrant filter allowing only chunks within the user's reading progress.

    Args:
        series: The series containing books with their read statuses.

    Returns:
        A Qdrant Filter combining all in-scope books via OR logic,
        or None if no books are in scope (all NOT_STARTED).
    """
    conditions: list[Filter | FieldCondition] = []

    for book in series.books:
        if book.status == BookStatus.NOT_STARTED:
            continue

        if book.status == BookStatus.COMPLETED:
            # All chapters in this book are safe
            conditions.append(FieldCondition(key="book_index", match=MatchValue(value=book.index)))

        elif book.status == BookStatus.READING:
            # Only chapters up to and including the current chapter
            max_chapter = (
                book.current_chapter_index if book.current_chapter_index is not None else 0
            )
            conditions.append(
                Filter(
                    must=[
                        FieldCondition(key="book_index", match=MatchValue(value=book.index)),
                        FieldCondition(key="chapter_index", range=Range(lte=max_chapter)),
                    ]
                )
            )

    if not conditions:
        return None

    return Filter(should=conditions)


def build_supabase_filter(series: Series) -> list[dict] | None:
    """Build a list of filter conditions for Supabase/Postgres.
    
    Each condition is a dict that can be used with JSONB containment @>.
    Since Postgres doesn't easily support OR-ing multiple JSONB filters in a single 
    containment check without complex SQL, we'll return a structure that the 
    database function can interpret.
    """
    conditions = []
    for book in series.books:
        if book.status == BookStatus.NOT_STARTED:
            continue
        
        if book.status == BookStatus.COMPLETED:
            conditions.append({"book_index": book.index})
        elif book.status == BookStatus.READING:
            max_chapter = book.current_chapter_index if book.current_chapter_index is not None else 0
            # Note: This requires the database function to handle 'lte' for chapter_index
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
    filters = {}
    
    # Check what kind of vector store we are using
    from src.vector_store.qdrant_store import QdrantVectorStore
    if isinstance(vector_store, QdrantVectorStore):
        qf = build_qdrant_filter(series)
        if qf is None:
            return []
        filters["qdrant_filter"] = qf
    else:
        # Fallback to Supabase/Generic
        sf = build_supabase_filter(series)
        if sf is None:
            return []
        filters["supabase_filter"] = sf

    embedding = embed_query(question)
    return vector_store.search(
        embedding=embedding,
        series_id=series.id,
        user_id=user_id,
        filters=filters,
        top_k=top_k,
    )
