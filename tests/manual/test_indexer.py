#!/usr/bin/env python3
"""End-to-end test for the Phase 3 indexing pipeline.

Tests: parse → chunk → embed → index → verify count → re-index (idempotency) → search → cleanup.

Usage:
    poetry run python tests/manual/test_indexer.py

Requires QDRANT_URL and QDRANT_API_KEY to be set in .env.
"""

from pathlib import Path

from src.config import settings
from src.ingestion.chunker import chunk_chapter
from src.ingestion.embedder import embed_query
from src.ingestion.epub_parser import parse_epub
from src.ingestion.indexer import index_book
from src.vector_store.qdrant_store import QdrantVectorStore

# Test constants — isolated collection so it does not pollute real data
_TEST_SERIES_ID = "test-phase3"
_TEST_BOOK_INDEX = 0
_EPUB_PATH = Path("src/data/Project Hail Mary.epub")


def _parse_and_chunk() -> list:
    """Parse the epub and chunk all chapters."""
    print(f"\n📖 Parsing {_EPUB_PATH.name}...")
    chapters = parse_epub(_EPUB_PATH)
    print(f"  Parsed {len(chapters)} chapters")

    all_chunks = []
    for chapter in chapters:
        all_chunks.extend(
            chunk_chapter(chapter, settings.chunk_size, settings.chunk_overlap)
        )
    print(f"  Chunked into {len(all_chunks)} chunks")
    return all_chunks


def test_index_and_verify(store: QdrantVectorStore, chunks: list) -> None:
    """Index the book and verify the point count matches the chunk count."""
    print("\n🚀 Indexing book...")
    indexed = index_book(chunks, _TEST_SERIES_ID, _TEST_BOOK_INDEX, store)
    print(f"  Indexed {indexed} chunks")

    count = store._client.count(collection_name=_TEST_SERIES_ID, exact=True).count
    assert count == len(chunks), f"Expected {len(chunks)} points, got {count}"
    print(f"  ✅ Vector count matches chunk count: {count}")


def test_reindex_idempotency(store: QdrantVectorStore, chunks: list) -> None:
    """Re-index the same book and confirm no duplicates are created."""
    print("\n🔁 Re-indexing same book (idempotency check)...")
    index_book(chunks, _TEST_SERIES_ID, _TEST_BOOK_INDEX, store)

    count = store._client.count(collection_name=_TEST_SERIES_ID, exact=True).count
    assert count == len(chunks), f"Expected {len(chunks)} points after re-index, got {count}"
    print(f"  ✅ No duplicates — count still {count}")


def test_search(store: QdrantVectorStore) -> None:
    """Run a semantic search and verify results are returned."""
    print("\n🔍 Testing semantic search...")
    query = "How does the Hail Mary spacecraft propulsion system work?"
    embedding = embed_query(query)

    results = store.search(embedding, _TEST_SERIES_ID, filters={}, top_k=3)
    assert len(results) > 0, "Expected at least 1 search result"

    print(f"  ✅ Got {len(results)} results for query: '{query}'")
    for i, r in enumerate(results, 1):
        print(f"  [{i}] score={r.score:.3f} | {r.chapter_label} | {r.text[:80]}...")


def cleanup(store: QdrantVectorStore) -> None:
    """Delete the test collection."""
    print("\n🧹 Cleaning up test collection...")
    store._client.delete_collection(_TEST_SERIES_ID)
    print("  ✅ Test collection deleted")


def main() -> None:
    """Run the full indexer validation suite."""
    print("=" * 60)
    print("Phase 3 Indexer Validation")
    print("=" * 60)

    store = QdrantVectorStore(url=str(settings.qdrant_url), api_key=settings.qdrant_api_key)
    chunks = _parse_and_chunk()

    test_index_and_verify(store, chunks)
    test_reindex_idempotency(store, chunks)
    test_search(store)
    cleanup(store)

    print("\n✅ All Phase 3 validation checks passed!")


if __name__ == "__main__":
    main()
