"""Smoke test: canonical models parse correctly."""
from src.models import CanonicalBook, UserBook, BookStatus


def test_canonical_book_standalone():
    """Standalone book (no series) has canonical_series_id == its own id."""
    cb = CanonicalBook(
        id="abc123",
        title="Piranesi",
        canonical_series_id="abc123",
    )
    assert cb.canonical_series_id == "abc123"
    assert cb.series_name is None


def test_canonical_book_series():
    cb = CanonicalBook(
        id="OL12345W",
        ol_id="OL12345W",
        title="The Way of Kings",
        author="Brandon Sanderson",
        series_name="The Stormlight Archive",
        series_position=1.0,
        canonical_series_id="the-stormlight-archive",
    )
    assert cb.canonical_series_id == "the-stormlight-archive"


def test_user_book_defaults():
    ub = UserBook(
        canonical_book_id="OL12345W",
        user_id="user-1",
        status=BookStatus.NOT_STARTED,
    )
    assert ub.current_chapter_index is None
    assert ub.has_cover is False
