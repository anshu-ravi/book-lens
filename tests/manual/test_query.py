#!/usr/bin/env python3
"""End-to-end tests for the Phase 5 query engine.

Tests:
  1. Filter logic (in-memory, no network) — COMPLETED / READING / NOT_STARTED
  2. retrieve_chunks live against Qdrant (requires indexed data)
  3. Full Claude answer (requires Anthropic API key)

The test indexes Red Rising Book 1 into a temporary Qdrant collection before
running live tests and deletes it on cleanup.

Usage:
    poetry run python tests/manual/test_query.py
"""

from pathlib import Path

from src.config import settings
from src.ingestion.chunker import chunk_chapter
from src.ingestion.epub_parser import parse_epub
from src.ingestion.indexer import index_book
from src.models import Book, BookStatus, Chapter, Series
from src.query.prompt_builder import build_prompt, build_reading_summary
from src.query.retriever import build_qdrant_filter, retrieve_chunks
from src.vector_store.qdrant_store import QdrantVectorStore

_TEST_SERIES_ID = "test-query-phase5"
_EPUB_PATH = Path("src/data/Red rising _ Book I of The Red Rising Trilogy.epub")


# ---------------------------------------------------------------------------
# Filter logic tests (in-memory, no network)
# ---------------------------------------------------------------------------


def test_filter_not_started() -> None:
    """All NOT_STARTED books → filter is None → no search attempted."""
    series = Series(
        id="red-rising",
        name="Red Rising Saga",
        books=[Book(index=0, title="Red Rising", status=BookStatus.NOT_STARTED, chapters=[])],
    )
    result = build_qdrant_filter(series)
    assert result is None
    print("  ✅ filter: all NOT_STARTED → None (no search)")


def test_filter_completed() -> None:
    """COMPLETED book → filter matches all chapters in that book."""
    series = Series(
        id="red-rising",
        name="Red Rising Saga",
        books=[Book(index=0, title="Red Rising", status=BookStatus.COMPLETED, chapters=[])],
    )
    f = build_qdrant_filter(series)
    assert f is not None
    assert f.should is not None and len(f.should) == 1
    print("  ✅ filter: COMPLETED book → one should condition")


def test_filter_reading_with_chapter() -> None:
    """READING book → filter restricts to chapters <= current_chapter_index."""
    series = Series(
        id="red-rising",
        name="Red Rising Saga",
        books=[
            Book(
                index=0,
                title="Red Rising",
                status=BookStatus.READING,
                chapters=[],
                current_chapter_index=5,
            )
        ],
    )
    f = build_qdrant_filter(series)
    assert f is not None
    assert f.should is not None and len(f.should) == 1
    # The condition should be a nested Filter with must=[book_index, chapter_index range]
    nested = f.should[0]
    assert hasattr(nested, "must") and nested.must is not None
    assert len(nested.must) == 2
    print("  ✅ filter: READING book → nested must filter with chapter range")


def test_filter_mixed_statuses() -> None:
    """Mixed statuses → only COMPLETED and READING contribute conditions."""
    series = Series(
        id="red-rising",
        name="Red Rising Saga",
        books=[
            Book(index=0, title="Red Rising", status=BookStatus.COMPLETED, chapters=[]),
            Book(
                index=1,
                title="Golden Son",
                status=BookStatus.READING,
                chapters=[],
                current_chapter_index=10,
            ),
            Book(index=2, title="Morning Star", status=BookStatus.NOT_STARTED, chapters=[]),
        ],
    )
    f = build_qdrant_filter(series)
    assert f is not None
    assert f.should is not None and len(f.should) == 2
    print("  ✅ filter: mixed statuses → 2 conditions (NOT_STARTED excluded)")


# ---------------------------------------------------------------------------
# Reading summary tests (in-memory)
# ---------------------------------------------------------------------------


def test_reading_summary_completed() -> None:
    """COMPLETED book shows correctly in summary."""
    series = Series(
        id="red-rising",
        name="Red Rising Saga",
        books=[Book(index=0, title="Red Rising", status=BookStatus.COMPLETED, chapters=[])],
    )
    summary = build_reading_summary(series)
    assert "Red Rising" in summary
    assert "completed" in summary
    print(f"  ✅ reading summary (completed): '{summary}'")


def test_reading_summary_reading_with_label() -> None:
    """READING book shows chapter label in summary."""
    series = Series(
        id="red-rising",
        name="Red Rising Saga",
        books=[
            Book(
                index=0,
                title="Red Rising",
                status=BookStatus.READING,
                chapters=[Chapter(index=0, label="Prologue"), Chapter(index=5, label="Chapter 5")],
                current_chapter_index=5,
            )
        ],
    )
    summary = build_reading_summary(series)
    assert "reading" in summary
    assert "Chapter 5" in summary
    print(f"  ✅ reading summary (reading): '{summary}'")


def test_reading_summary_not_started_omitted() -> None:
    """NOT_STARTED books are omitted from the summary."""
    series = Series(
        id="red-rising",
        name="Red Rising Saga",
        books=[Book(index=0, title="Red Rising", status=BookStatus.NOT_STARTED, chapters=[])],
    )
    summary = build_reading_summary(series)
    assert "Red Rising" not in summary
    print(f"  ✅ reading summary (not started omitted): '{summary}'")


# ---------------------------------------------------------------------------
# Live tests (require Qdrant + Anthropic)
# ---------------------------------------------------------------------------


def setup_test_data(store: QdrantVectorStore) -> int:
    """Index Red Rising Book 1 into a temporary test collection."""
    print(f"\n📖 Indexing {_EPUB_PATH.name} into '{_TEST_SERIES_ID}'...")
    chapters = parse_epub(_EPUB_PATH)
    all_chunks = []
    for chapter in chapters:
        all_chunks.extend(chunk_chapter(chapter, settings.chunk_size, settings.chunk_overlap))
    count = index_book(all_chunks, _TEST_SERIES_ID, 0, store)
    print(f"  Indexed {count} chunks")
    return count


def test_retrieve_completed(store: QdrantVectorStore, chunk_count: int) -> None:
    """COMPLETED book → chunks returned."""
    series = Series(
        id=_TEST_SERIES_ID,
        name="Red Rising Saga",
        books=[Book(index=0, title="Red Rising", status=BookStatus.COMPLETED, chapters=[])],
    )
    results = retrieve_chunks("Who is Darrow?", series, store, top_k=3)
    assert len(results) > 0, "Expected results for a COMPLETED book"
    assert all(r.book_index == 0 for r in results)
    print(f"  ✅ retrieve (COMPLETED): {len(results)} chunks returned")
    for r in results:
        print(f"    score={r.score:.3f} | {r.chapter_label} | {r.text[:60]}...")


def test_retrieve_not_started(store: QdrantVectorStore) -> None:
    """NOT_STARTED book → empty result, no search attempted."""
    series = Series(
        id=_TEST_SERIES_ID,
        name="Red Rising Saga",
        books=[Book(index=0, title="Red Rising", status=BookStatus.NOT_STARTED, chapters=[])],
    )
    results = retrieve_chunks("Who is Darrow?", series, store, top_k=3)
    assert results == [], f"Expected no results for NOT_STARTED, got {len(results)}"
    print("  ✅ retrieve (NOT_STARTED): empty list returned")


def test_retrieve_reading_chapter_cutoff(store: QdrantVectorStore) -> None:
    """READING at chapter 3 → only chapters 0–3 returned."""
    series = Series(
        id=_TEST_SERIES_ID,
        name="Red Rising Saga",
        books=[
            Book(
                index=0,
                title="Red Rising",
                status=BookStatus.READING,
                chapters=[],
                current_chapter_index=3,
            )
        ],
    )
    results = retrieve_chunks("Who is Darrow?", series, store, top_k=5)
    assert all(
        r.chapter_index <= 3 for r in results
    ), f"Spoiler leak: got chunk from chapter > 3: {[r.chapter_index for r in results]}"
    print(f"  ✅ retrieve (READING ch≤3): {len(results)} chunks, all from chapters 0–3")


def test_full_claude_answer(store: QdrantVectorStore) -> None:
    """Full end-to-end: retrieve → prompt → Claude answer."""
    print("\n🤖 Testing full Claude answer...")
    series = Series(
        id=_TEST_SERIES_ID,
        name="Red Rising Saga",
        books=[Book(index=0, title="Red Rising", status=BookStatus.COMPLETED, chapters=[])],
    )
    import anthropic as _anthropic

    chunks = retrieve_chunks(
        "What is the Red Rising society's caste system?", series, store, top_k=5
    )
    assert chunks, "Expected chunks for a COMPLETED book"

    prompt = build_prompt("What is the Red Rising society's caste system?", chunks, series)
    client = _anthropic.Anthropic(api_key=settings.anthropic_api_key)
    message = client.messages.create(
        model=settings.llm_model,
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )
    answer = message.content[0].text
    assert len(answer) > 50, "Expected a non-trivial answer from Claude"
    print(f"  ✅ Claude answered ({len(answer)} chars):")
    print(f"  {answer[:200]}...")


def cleanup(store: QdrantVectorStore) -> None:
    """Delete the test collection."""
    print("\n🧹 Cleaning up test collection...")
    store._client.delete_collection(_TEST_SERIES_ID)
    print("  ✅ Test collection deleted")


def main() -> None:
    """Run all query engine tests."""
    print("=" * 60)
    print("Phase 5 Query Engine Tests")
    print("=" * 60)

    print("\n── Filter logic (in-memory) ──")
    test_filter_not_started()
    test_filter_completed()
    test_filter_reading_with_chapter()
    test_filter_mixed_statuses()

    print("\n── Reading summary (in-memory) ──")
    test_reading_summary_completed()
    test_reading_summary_reading_with_label()
    test_reading_summary_not_started_omitted()

    print("\n── Live retrieval + Claude (requires Qdrant + Anthropic) ──")
    store = QdrantVectorStore(url=str(settings.qdrant_url), api_key=settings.qdrant_api_key)
    chunk_count = setup_test_data(store)

    test_retrieve_completed(store, chunk_count)
    test_retrieve_not_started(store)
    test_retrieve_reading_chapter_cutoff(store)
    test_full_claude_answer(store)

    cleanup(store)

    print("\n✅ All Phase 5 query engine tests passed!")


if __name__ == "__main__":
    main()
