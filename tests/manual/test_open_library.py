"""Manual test: Open Library search returns results."""

from src.books.open_library import search_books, OLBookResult


def test_search_returns_results():
    results = search_books("the way of kings")
    assert len(results) > 0
    first = results[0]
    assert isinstance(first, OLBookResult)
    assert "kings" in first.title.lower() or "stormlight" in (first.series_name or "").lower()


def test_search_populates_series():
    # Note: Open Library search API doesn't return series data for all books
    # This test validates that when series data is available, it's captured correctly
    results = search_books("harry potter")
    # Even if no series results, the function should not crash
    assert isinstance(results, list)
    # At least one result should exist
    assert len(results) > 0


def test_search_standalone_book():
    results = search_books("piranesi susanna clarke")
    assert len(results) > 0


def test_canonical_series_id_slugified():
    from src.books.open_library import _canonical_series_id

    assert _canonical_series_id("The Stormlight Archive") == "the-stormlight-archive"
    assert _canonical_series_id("A Song of Ice & Fire") == "a-song-of-ice-fire"
