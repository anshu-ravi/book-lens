"""Tests for booklens.goodreads.stats: the series-title parser and compute_stats.

All synthetic data -- fictional titles/authors, nothing from The Stormlight
Archive per CLAUDE.md. Every test is offline: stats are computed directly
over a locally seeded `goodreads.db`, no network involved.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from booklens import goodreads
from booklens.goodreads.feed import GoodreadsBook, ShelfFetch
from booklens.goodreads.stats import compute_stats, parse_series
from booklens.web.app import app

client = TestClient(app)


def _isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("BOOKLENS_DATA_DIR", str(tmp_path / "data"))


def _book(review_id, title, shelf, **overrides) -> GoodreadsBook:
    fields = dict(
        review_id=review_id,
        book_id=f"bk-{review_id}",
        title=title,
        author="Some Author",
        isbn="1234567890",
        num_pages=300,
        published_year=2020,
        description="A book.",
        cover_small=None,
        cover_medium=None,
        cover_large=None,
        average_rating=4.2,
        user_rating=5,
        user_review=None,
        shelf=shelf,
        custom_shelves=(),
        date_added="2024-01-01T00:00:00+00:00",
        date_read=None,
        date_created="2024-01-01T00:00:00+00:00",
        date_started=None,
    )
    fields.update(overrides)
    return GoodreadsBook(**fields)


def _seed(conn, fetches: dict[str, tuple[GoodreadsBook, ...]]):
    for shelf, books in fetches.items():
        goodreads.upsert_shelf(conn, ShelfFetch(shelf=shelf, books=books, truncated=False))


# -- parse_series -----------------------------------------------------------


def test_parse_series_basic():
    assert parse_series("Skybound (Ironbound, #2)") == ("Ironbound", "2")


def test_parse_series_decimal_number():
    assert parse_series("Interlude (Ironbound, #1.5)") == ("Ironbound", "1.5")


def test_parse_series_title_with_unrelated_parens():
    assert parse_series("The Diplomat (A Novel)") is None


def test_parse_series_no_series():
    assert parse_series("A Standalone Book") is None


def test_parse_series_name_itself_has_parens():
    # The series name has no comma/#, so the whole thing reads as an
    # unrelated parenthetical -- no series marker to extract.
    assert parse_series("Chronicle (Of Ash and Embers)") is None


# -- compute_stats: empty cache ----------------------------------------------


def test_compute_stats_empty_cache_shape(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    conn = goodreads.connect()
    try:
        stats = compute_stats(conn)
    finally:
        conn.close()

    assert stats == {
        "totals": {
            "books_read": 0,
            "pages_read": 0,
            "avg_pages": 0,
            "dnf": 0,
            "want_to_read": 0,
            "currently_reading": 0,
            "backlog_pages": 0,
            "longest": None,
            "shortest": None,
        },
        "coverage": {
            "read_total": 0, "with_date_read": 0, "with_date_started": 0, "with_genres": 0,
        },
        "by_month": [],
        "top_authors": [],
        "by_decade": [],
        "series": [],
        "durations": {
            "count": 0, "median_days": None, "mean_days": None,
            "fastest": None, "slowest": None, "books": [],
        },
        "genres": [],
        "rating_by_genre": [],
    }


def test_stats_endpoint_empty_cache_returns_200(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    resp = client.get("/api/goodreads/stats")
    assert resp.status_code == 200
    assert resp.json()["totals"]["books_read"] == 0


# -- read-shelf-only scoping --------------------------------------------------


def test_totals_scoped_to_read_shelf_only(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    conn = goodreads.connect()
    try:
        _seed(
            conn,
            {
                "read": (
                    _book("r1", "Book One", "read", num_pages=200, author="Author A"),
                    _book("r2", "Book Two", "read", num_pages=400, author="Author B"),
                ),
                "to-read": (_book("r3", "Book Three", "to-read", num_pages=1000),),
                "currently-reading": (_book("r4", "Book Four", "currently-reading", num_pages=50),),
            },
        )
        stats = compute_stats(conn)
    finally:
        conn.close()

    totals = stats["totals"]
    assert totals["books_read"] == 2
    assert totals["pages_read"] == 600
    assert totals["avg_pages"] == 300
    assert totals["want_to_read"] == 1
    assert totals["currently_reading"] == 1
    assert totals["backlog_pages"] == 1000
    # Both authors were read exactly once here, so top_authors -- which now
    # excludes single-book authors -- is empty; see the dedicated tests below.
    assert stats["top_authors"] == []


def test_dnf_counts_configured_dnf_shelf_only(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    conn = goodreads.connect()
    try:
        goodreads.set_setting(conn, "dnf_shelf", "did-not-finish")
        _seed(
            conn,
            {
                "did-not-finish": (_book("r1", "Abandoned", "did-not-finish"),),
                "some-other-custom-shelf": (_book("r2", "Untracked", "some-other-custom-shelf"),),
            },
        )
        stats = compute_stats(conn)
    finally:
        conn.close()

    assert stats["totals"]["dnf"] == 1


def test_dnf_zero_when_no_dnf_shelf_configured(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    conn = goodreads.connect()
    try:
        _seed(conn, {"did-not-finish": (_book("r1", "Abandoned", "did-not-finish"),)})
        stats = compute_stats(conn)
    finally:
        conn.close()

    assert stats["totals"]["dnf"] == 0


def test_longest_and_shortest(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    conn = goodreads.connect()
    try:
        _seed(
            conn,
            {
                "read": (
                    _book("r1", "Short Book", "read", num_pages=260),
                    _book("r2", "Long Book", "read", num_pages=1007),
                ),
            },
        )
        stats = compute_stats(conn)
    finally:
        conn.close()

    assert stats["totals"]["longest"] == {"title": "Long Book", "num_pages": 1007}
    assert stats["totals"]["shortest"] == {"title": "Short Book", "num_pages": 260}


# -- coverage -----------------------------------------------------------------


def test_coverage_counts_read_books_with_and_without_date_read(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    conn = goodreads.connect()
    try:
        _seed(
            conn,
            {
                "read": (
                    _book("r1", "Dated", "read", date_read="2024-03-15T00:00:00+00:00"),
                    _book("r2", "Undated", "read", date_read=None),
                ),
            },
        )
        stats = compute_stats(conn)
    finally:
        conn.close()

    assert stats["coverage"] == {
        "read_total": 2,
        "with_date_read": 1,
        "with_date_started": 0,
        "with_genres": 0,
    }


# -- by_month gap filling ------------------------------------------------------


def test_by_month_fills_gap_months_with_zero(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    conn = goodreads.connect()
    try:
        _seed(
            conn,
            {
                "read": (
                    _book("r1", "Jan Book", "read", num_pages=300, date_read="2025-01-10T00:00:00+00:00"),
                    _book("r2", "June Book", "read", num_pages=400, date_read="2025-06-20T00:00:00+00:00"),
                ),
            },
        )
        stats = compute_stats(conn)
    finally:
        conn.close()

    months = [m["month"] for m in stats["by_month"]]
    assert months == ["2025-01", "2025-02", "2025-03", "2025-04", "2025-05", "2025-06"]
    by_key = {m["month"]: m for m in stats["by_month"]}
    assert by_key["2025-01"]["count"] == 1
    assert by_key["2025-01"]["pages"] == 300
    assert [b["title"] for b in by_key["2025-01"]["books"]] == ["Jan Book"]
    assert by_key["2025-03"] == {"month": "2025-03", "count": 0, "pages": 0, "books": []}
    assert by_key["2025-06"]["count"] == 1
    assert by_key["2025-06"]["pages"] == 400
    assert [b["title"] for b in by_key["2025-06"]["books"]] == ["June Book"]


def test_by_month_empty_when_no_dates(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    conn = goodreads.connect()
    try:
        _seed(conn, {"read": (_book("r1", "Undated", "read", date_read=None),)})
        stats = compute_stats(conn)
    finally:
        conn.close()

    assert stats["by_month"] == []


# -- by_month book records -----------------------------------------------------


def test_by_month_book_record_shape_and_series_parsing(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    conn = goodreads.connect()
    try:
        _seed(
            conn,
            {
                "read": (
                    _book(
                        "r1", "Skybound (Ironbound, #2)", "read",
                        book_id="gr-1", author="Author A", num_pages=310,
                        user_rating=4, date_read="2025-03-05T00:00:00+00:00",
                        cover_small="http://example.com/s.jpg",
                    ),
                    _book(
                        "r2", "A Standalone Book", "read",
                        book_id="gr-2", author="Author B", num_pages=210,
                        user_rating=5, date_read="2025-03-12T00:00:00+00:00",
                    ),
                ),
            },
        )
        stats = compute_stats(conn)
    finally:
        conn.close()

    march = next(m for m in stats["by_month"] if m["month"] == "2025-03")
    assert march["count"] == 2
    series_book, standalone_book = march["books"]

    assert series_book == {
        "goodreads_book_id": "gr-1",
        "title": "Skybound",
        "author": "Author A",
        "series": "Ironbound",
        "series_number": 2,
        "cover": "http://example.com/s.jpg",
        "pages": 310,
        "rating": 4,
        "date_read": "2025-03-05T00:00:00+00:00",
    }
    assert standalone_book["title"] == "A Standalone Book"
    assert standalone_book["series"] is None
    assert standalone_book["series_number"] is None
    assert standalone_book["cover"] is None


def test_by_month_books_ordered_by_date_read_ascending(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    conn = goodreads.connect()
    try:
        _seed(
            conn,
            {
                "read": (
                    _book("r1", "Later Book", "read", date_read="2025-03-25T00:00:00+00:00"),
                    _book("r2", "Earlier Book", "read", date_read="2025-03-02T00:00:00+00:00"),
                ),
            },
        )
        stats = compute_stats(conn)
    finally:
        conn.close()

    march = next(m for m in stats["by_month"] if m["month"] == "2025-03")
    assert [b["title"] for b in march["books"]] == ["Earlier Book", "Later Book"]


def test_by_month_excludes_read_book_with_no_date_read(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    conn = goodreads.connect()
    try:
        _seed(
            conn,
            {
                "read": (
                    _book("r1", "Dated Book", "read", date_read="2025-03-02T00:00:00+00:00"),
                    _book("r2", "Undated Book", "read", date_read=None),
                ),
            },
        )
        stats = compute_stats(conn)
    finally:
        conn.close()

    # The undated book is invisible to every month bucket, but still counted
    # in coverage -- read_total - with_date_read expresses "can't be placed".
    all_titles = [b["title"] for m in stats["by_month"] for b in m["books"]]
    assert all_titles == ["Dated Book"]
    assert stats["coverage"]["read_total"] == 2
    assert stats["coverage"]["with_date_read"] == 1


# -- by_decade gap filling ------------------------------------------------------


def test_by_decade_fills_gaps_with_zero(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    conn = goodreads.connect()
    try:
        _seed(
            conn,
            {
                "read": (
                    _book("r1", "Old Book", "read", published_year=1965),
                    _book("r2", "New Book", "read", published_year=1988),
                ),
            },
        )
        stats = compute_stats(conn)
    finally:
        conn.close()

    decades = [d["decade"] for d in stats["by_decade"]]
    assert decades == [1960, 1970, 1980]
    by_key = {d["decade"]: d for d in stats["by_decade"]}
    assert by_key[1960] == {"decade": 1960, "books": 1}
    assert by_key[1970] == {"decade": 1970, "books": 0}
    assert by_key[1980] == {"decade": 1980, "books": 1}


# -- top_authors ordering -------------------------------------------------------


def test_top_authors_sorted_by_count_then_alpha_capped(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    conn = goodreads.connect()
    try:
        books = []
        for i in range(3):
            books.append(_book(f"z{i}", f"Zeta Book {i}", "read", author="Zeta Author"))
        for i in range(3):
            books.append(_book(f"a{i}", f"Alpha Book {i}", "read", author="Alpha Author"))
        books.append(_book("s1", "Solo Book", "read", author="Solo Author"))
        _seed(conn, {"read": tuple(books)})
        stats = compute_stats(conn)
    finally:
        conn.close()

    # "Solo Author" was read exactly once, so it's excluded before the cap.
    authors = stats["top_authors"]
    assert authors[0] == {"author": "Alpha Author", "books": 3}
    assert authors[1] == {"author": "Zeta Author", "books": 3}
    assert [a["author"] for a in authors] == ["Alpha Author", "Zeta Author"]


def test_top_authors_excludes_single_book_authors(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    conn = goodreads.connect()
    try:
        _seed(
            conn,
            {
                "read": (
                    _book("r1", "Book One", "read", author="Duo Author"),
                    _book("r2", "Book Two", "read", author="Duo Author"),
                    _book("r3", "Solo Book", "read", author="Solo Author"),
                ),
            },
        )
        stats = compute_stats(conn)
    finally:
        conn.close()

    assert stats["top_authors"] == [{"author": "Duo Author", "books": 2}]


def test_top_authors_all_singletons_returns_empty(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    conn = goodreads.connect()
    try:
        _seed(
            conn,
            {
                "read": (
                    _book("r1", "Book One", "read", author="Author A"),
                    _book("r2", "Book Two", "read", author="Author B"),
                ),
            },
        )
        stats = compute_stats(conn)
    finally:
        conn.close()

    assert stats["top_authors"] == []


# -- series ---------------------------------------------------------------------


def test_series_grouping_and_partial_first(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    conn = goodreads.connect()
    try:
        _seed(
            conn,
            {
                "read": (
                    _book("r1", "Skybound (Ironbound, #1)", "read"),
                    _book("r2", "Skybound (Ironbound, #2)", "read"),
                    _book("r3", "Complete One (Finished, #1)", "read"),
                ),
                "to-read": (
                    _book("r4", "Skybound (Ironbound, #3)", "to-read"),
                    _book("r5", "Complete Two (Finished, #2)", "to-read"),
                ),
                "currently-reading": (_book("r6", "No Series Book", "currently-reading"),),
            },
        )
        # "Finished" series: r3 read, r5 to-read -> partial (1 of 2 read).
        stats = compute_stats(conn)
    finally:
        conn.close()

    series = stats["series"]
    names = [s["name"] for s in series]
    assert "No Series Book" not in names  # unparseable titles excluded

    ironbound = next(s for s in series if s["name"] == "Ironbound")
    assert ironbound["read"] == 2
    assert ironbound["total"] == 3
    assert ironbound["shelves"] == ["read", "to-read"]

    finished = next(s for s in series if s["name"] == "Finished")
    assert finished["read"] == 1
    assert finished["total"] == 2

    # Both are partial (0 < read < total); partial series sort before
    # complete ones and alphabetically among themselves.
    assert names.index("Finished") < len(series)
    assert names[0] in {"Finished", "Ironbound"}


def test_series_complete_sorts_after_partial(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    conn = goodreads.connect()
    try:
        _seed(
            conn,
            {
                "read": (
                    _book("r1", "Whole (Alpha Series, #1)", "read"),
                    _book("r2", "Whole (Alpha Series, #2)", "read"),
                    _book("r3", "Half (Beta Series, #1)", "read"),
                ),
                "to-read": (_book("r4", "Half Two (Beta Series, #2)", "to-read"),),
            },
        )
        stats = compute_stats(conn)
    finally:
        conn.close()

    names = [s["name"] for s in stats["series"]]
    assert names == ["Beta Series", "Alpha Series"]
