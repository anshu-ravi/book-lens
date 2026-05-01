"""Manual integration test for canonical library manager."""
import asyncio
import pytest
from src.library.manager import upsert_canonical_book, upsert_user_book, load_library, get_series_by_canonical_id
from src.models import CanonicalBook, UserBook, BookStatus, Chapter

TEST_USER = "test-canonical-user-001"
CB_ID = "OL_TEST_CANONICAL_001"
SERIES_SLUG = "test-series-slug"


@pytest.fixture(autouse=True)
def cleanup():
    yield
    from src.supabase_client import get_supabase_client
    client = get_supabase_client()
    client.table("user_books").delete().filter("user_id", "eq", TEST_USER).execute()
    client.table("canonical_books").delete().filter("id", "eq", CB_ID).execute()


def test_upsert_and_load():
    cb = CanonicalBook(
        id=CB_ID,
        title="Test Book One",
        author="Test Author",
        series_name="Test Series",
        series_position=1.0,
        canonical_series_id=SERIES_SLUG,
        chapters=[Chapter(index=0, label="Chapter 1"), Chapter(index=1, label="Chapter 2")],
    )
    upsert_canonical_book(cb)

    ub = UserBook(
        canonical_book_id=CB_ID,
        user_id=TEST_USER,
        status=BookStatus.READING,
        current_chapter_index=1,
    )
    upsert_user_book(ub)

    library = asyncio.run(load_library(TEST_USER))
    # Should have one series
    assert len(library.series) >= 1
    test_series = next((s for s in library.series if s.id == SERIES_SLUG), None)
    assert test_series is not None
    assert len(test_series.books) == 1
    book = test_series.books[0]
    assert book.title == "Test Book One"
    assert book.status == BookStatus.READING
    assert book.current_chapter_index == 1
    assert book.canonical_book_id == CB_ID
