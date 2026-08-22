"""Tests for GET/POST/DELETE /api/library/unified and its link endpoints.

Offline throughout -- Goodreads data is written directly into the cache via
`goodreads.upsert_shelf`, never fetched over the network. Titles are
synthetic, per CLAUDE.md.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from booklens import cli, goodreads
from booklens.goodreads import store
from booklens.goodreads.feed import GoodreadsBook, ShelfFetch
from booklens.web.app import app
from tests.test_ingest import _simple_epub

client = TestClient(app)


def _isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("BOOKLENS_DATA_DIR", str(tmp_path / "data"))


def _gr_book(review_id, title, shelf, *, book_id=None, **overrides) -> GoodreadsBook:
    fields = dict(
        review_id=review_id,
        book_id=book_id or f"gr-{review_id}",
        title=title,
        author="Some Author",
        isbn=None,
        num_pages=300,
        published_year=2020,
        description="A book.",
        cover_small=None,
        cover_medium=None,
        cover_large="http://example.com/l.jpg",
        average_rating=4.2,
        user_rating=None,
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


def _seed_gr(tmp_path, monkeypatch, shelf, *books, dnf_shelf=None):
    _isolate(tmp_path, monkeypatch)
    conn = goodreads.connect()
    try:
        store.upsert_shelf(conn, ShelfFetch(shelf=shelf, books=books, truncated=False))
        if dnf_shelf is not None:
            goodreads.set_setting(conn, "dnf_shelf", dnf_shelf)
    finally:
        conn.close()


def _ingest(tmp_path, monkeypatch, name, title, series="s1", start_order=1):
    _isolate(tmp_path, monkeypatch)
    epub = _simple_epub(tmp_path, name=name, title=title)
    rc = cli.main(["ingest", str(epub), "--series", series, "--start-order", str(start_order)])
    assert rc == 0


# -- empty cache ----------------------------------------------------------------


def test_empty_cache_shape(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)

    resp = client.get("/api/library/unified")
    assert resp.status_code == 200
    body = resp.json()

    assert [s["shelf"] for s in body["shelves"]] == ["reading", "tbr", "completed", "dnf"]
    assert [s["label"] for s in body["shelves"]] == ["Reading", "To Read", "Completed", "Did Not Finish"]
    for s in body["shelves"]:
        assert s["count"] == 0
        assert s["series"] == []
        assert s["standalone"] == []
    assert body["totals"] == {"books": 0, "with_epub": 0, "askable": 0}


# -- shelf mapping ----------------------------------------------------------------


def test_shelf_mapping_including_configured_dnf_shelf(tmp_path, monkeypatch):
    _seed_gr(tmp_path, monkeypatch, "to-read", _gr_book("r1", "Alpha", "to-read"))
    _seed_gr(tmp_path, monkeypatch, "currently-reading", _gr_book("r2", "Beta", "currently-reading"))
    _seed_gr(tmp_path, monkeypatch, "read", _gr_book("r3", "Gamma", "read"))
    _seed_gr(tmp_path, monkeypatch, "did-not-finish", _gr_book("r4", "Delta", "did-not-finish"), dnf_shelf="did-not-finish")

    body = client.get("/api/library/unified").json()
    by_shelf = {s["shelf"]: s for s in body["shelves"]}
    assert by_shelf["tbr"]["standalone"][0]["title"] == "Alpha"
    assert by_shelf["reading"]["standalone"][0]["title"] == "Beta"
    assert by_shelf["completed"]["standalone"][0]["title"] == "Gamma"
    assert by_shelf["dnf"]["standalone"][0]["title"] == "Delta"
    assert body["totals"]["books"] == 4


# -- ingested book with no Goodreads match --------------------------------------


def test_ingested_book_with_no_match_filed_by_progress(tmp_path, monkeypatch):
    _ingest(tmp_path, monkeypatch, "book.epub", "Sample Book")

    # Unread by default -> tbr.
    body = client.get("/api/library/unified").json()
    by_shelf = {s["shelf"]: s for s in body["shelves"]}
    assert by_shelf["tbr"]["standalone"][0]["book_id"] == "sample-book"
    assert by_shelf["tbr"]["standalone"][0]["askable"] is True
    assert by_shelf["tbr"]["standalone"][0]["goodreads_book_id"] is None
    assert body["totals"] == {"books": 1, "with_epub": 1, "askable": 1}

    rc = cli.main(["progress", "sample-book", "--status", "reading", "--chapter", "1"])
    assert rc == 0
    body = client.get("/api/library/unified").json()
    by_shelf = {s["shelf"]: s for s in body["shelves"]}
    assert by_shelf["reading"]["standalone"][0]["book_id"] == "sample-book"

    rc = cli.main(["progress", "sample-book", "--status", "finished"])
    assert rc == 0
    body = client.get("/api/library/unified").json()
    by_shelf = {s["shelf"]: s for s in body["shelves"]}
    assert by_shelf["completed"]["standalone"][0]["book_id"] == "sample-book"


def test_ingested_book_progress_null_when_no_progress_row(tmp_path, monkeypatch):
    _ingest(tmp_path, monkeypatch, "book.epub", "Sample Book")

    body = client.get("/api/library/unified").json()
    entry = body["shelves"][1]["standalone"][0]  # tbr
    assert entry["progress"] is None


# -- series grouping ----------------------------------------------------------


def test_series_spans_two_shelves_with_only_that_shelfs_volumes(tmp_path, monkeypatch):
    _seed_gr(
        tmp_path, monkeypatch, "read",
        _gr_book("r1", "Cold Wind (Ironbound, #2)", "read", book_id="2"),
    )
    conn = goodreads.connect()
    try:
        store.upsert_shelf(
            conn,
            ShelfFetch(
                shelf="to-read",
                books=(_gr_book("r2", "Iron Heart (Ironbound, #1)", "to-read", book_id="1"),),
                truncated=False,
            ),
        )
    finally:
        conn.close()

    body = client.get("/api/library/unified").json()
    by_shelf = {s["shelf"]: s for s in body["shelves"]}

    completed_series = by_shelf["completed"]["series"]
    assert len(completed_series) == 1
    assert completed_series[0]["name"] == "Ironbound"
    assert [b["title"] for b in completed_series[0]["books"]] == ["Cold Wind (Ironbound, #2)"]

    tbr_series = by_shelf["tbr"]["series"]
    assert len(tbr_series) == 1
    assert tbr_series[0]["name"] == "Ironbound"
    assert [b["title"] for b in tbr_series[0]["books"]] == ["Iron Heart (Ironbound, #1)"]


def test_series_books_sorted_by_number(tmp_path, monkeypatch):
    _seed_gr(
        tmp_path, monkeypatch, "read",
        _gr_book("r1", "Cold Wind (Ironbound, #2)", "read", book_id="2"),
        _gr_book("r2", "Iron Heart (Ironbound, #1)", "read", book_id="1"),
        _gr_book("r3", "Steel Dawn (Ironbound, #3)", "read", book_id="3"),
    )

    body = client.get("/api/library/unified").json()
    completed = next(s for s in body["shelves"] if s["shelf"] == "completed")
    titles = [b["display_title"] for b in completed["series"][0]["books"]]
    assert titles == ["Iron Heart", "Cold Wind", "Steel Dawn"]


def test_standalone_sorted_by_title(tmp_path, monkeypatch):
    _seed_gr(
        tmp_path, monkeypatch, "read",
        _gr_book("r1", "Zebra Tale", "read"),
        _gr_book("r2", "Apple Story", "read"),
    )

    body = client.get("/api/library/unified").json()
    completed = next(s for s in body["shelves"] if s["shelf"] == "completed")
    titles = [b["title"] for b in completed["standalone"]]
    assert titles == ["Apple Story", "Zebra Tale"]


def test_display_title_strips_series_suffix(tmp_path, monkeypatch):
    _seed_gr(tmp_path, monkeypatch, "read", _gr_book("r1", "Cold Wind (Ironbound, #2)", "read"))

    body = client.get("/api/library/unified").json()
    completed = next(s for s in body["shelves"] if s["shelf"] == "completed")
    book = completed["series"][0]["books"][0]
    assert book["title"] == "Cold Wind (Ironbound, #2)"
    assert book["display_title"] == "Cold Wind"
    assert book["series"] == "Ironbound"
    assert book["series_number"] == 2


# -- no book appears twice ---------------------------------------------------


def test_linked_book_appears_only_once(tmp_path, monkeypatch):
    _ingest(tmp_path, monkeypatch, "book.epub", "Cold Wind")
    _seed_gr(tmp_path, monkeypatch, "read", _gr_book("r1", "Cold Wind", "read", book_id="7235533"))

    conn = goodreads.connect()
    try:
        goodreads.set_link(conn, "cold-wind", "7235533", source="manual")
    finally:
        conn.close()

    body = client.get("/api/library/unified").json()
    all_book_ids = []
    for s in body["shelves"]:
        for entry in s["standalone"]:
            all_book_ids.append(entry["book_id"])
        for series in s["series"]:
            for entry in series["books"]:
                all_book_ids.append(entry["book_id"])
    assert all_book_ids.count("cold-wind") == 1
    assert body["totals"]["books"] == 1


# -- link endpoints ---------------------------------------------------------------


def test_post_library_link_creates_manual_link(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    resp = client.post("/api/library/link", json={"book_id": "cold-wind", "goodreads_book_id": "111"})
    assert resp.status_code == 200
    assert resp.json() == {"book_id": "cold-wind", "goodreads_book_id": "111"}


def test_post_library_link_overwrites_earlier_manual_link(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    client.post("/api/library/link", json={"book_id": "cold-wind", "goodreads_book_id": "111"})
    resp = client.post("/api/library/link", json={"book_id": "cold-wind", "goodreads_book_id": "222"})
    assert resp.json()["goodreads_book_id"] == "222"


def test_delete_library_link_removes_it(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    client.post("/api/library/link", json={"book_id": "cold-wind", "goodreads_book_id": "111"})
    resp = client.delete("/api/library/link/cold-wind")
    assert resp.status_code == 200
    assert resp.json() == {"book_id": "cold-wind", "goodreads_book_id": None}
