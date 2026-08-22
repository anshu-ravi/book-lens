"""Tests for GET/POST/DELETE /api/library/unified and its link endpoints.

Offline throughout -- Goodreads data is written directly into the cache via
`goodreads.upsert_shelf`, never fetched over the network. Titles are
synthetic, per CLAUDE.md.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

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
        assert s["groups"] == []
    assert body["totals"] == {"books": 0, "with_epub": 0, "askable": 0}


# -- shelf mapping ----------------------------------------------------------------


def test_shelf_mapping_including_configured_dnf_shelf(tmp_path, monkeypatch):
    _seed_gr(tmp_path, monkeypatch, "to-read", _gr_book("r1", "Alpha", "to-read"))
    _seed_gr(tmp_path, monkeypatch, "currently-reading", _gr_book("r2", "Beta", "currently-reading"))
    _seed_gr(tmp_path, monkeypatch, "read", _gr_book("r3", "Gamma", "read"))
    _seed_gr(tmp_path, monkeypatch, "did-not-finish", _gr_book("r4", "Delta", "did-not-finish"), dnf_shelf="did-not-finish")

    body = client.get("/api/library/unified").json()
    by_shelf = {s["shelf"]: s for s in body["shelves"]}
    assert by_shelf["tbr"]["groups"][0]["books"][0]["title"] == "Alpha"
    assert by_shelf["reading"]["groups"][0]["books"][0]["title"] == "Beta"
    assert by_shelf["completed"]["groups"][0]["books"][0]["title"] == "Gamma"
    assert by_shelf["dnf"]["groups"][0]["books"][0]["title"] == "Delta"
    assert body["totals"]["books"] == 4


# -- ingested book with no Goodreads match --------------------------------------


def test_ingested_book_with_no_match_filed_by_progress(tmp_path, monkeypatch):
    _ingest(tmp_path, monkeypatch, "book.epub", "Sample Book")

    # Unread by default -> tbr.
    body = client.get("/api/library/unified").json()
    by_shelf = {s["shelf"]: s for s in body["shelves"]}
    assert by_shelf["tbr"]["groups"][0]["books"][0]["book_id"] == "sample-book"
    assert by_shelf["tbr"]["groups"][0]["books"][0]["askable"] is True
    assert by_shelf["tbr"]["groups"][0]["books"][0]["goodreads_book_id"] is None
    assert body["totals"] == {"books": 1, "with_epub": 1, "askable": 1}

    rc = cli.main(["progress", "sample-book", "--status", "reading", "--chapter", "1"])
    assert rc == 0
    body = client.get("/api/library/unified").json()
    by_shelf = {s["shelf"]: s for s in body["shelves"]}
    assert by_shelf["reading"]["groups"][0]["books"][0]["book_id"] == "sample-book"

    rc = cli.main(["progress", "sample-book", "--status", "finished"])
    assert rc == 0
    body = client.get("/api/library/unified").json()
    by_shelf = {s["shelf"]: s for s in body["shelves"]}
    assert by_shelf["completed"]["groups"][0]["books"][0]["book_id"] == "sample-book"


def test_ingested_book_progress_defaults_to_unread_when_no_progress_row(tmp_path, monkeypatch):
    _ingest(tmp_path, monkeypatch, "book.epub", "Sample Book")

    body = client.get("/api/library/unified").json()
    entry = body["shelves"][1]["groups"][0]["books"][0]  # tbr
    assert entry["progress"] == {"status": "unread", "chapter_idx": None, "ceiling_seq": 0}


def test_goodreads_only_book_has_null_progress(tmp_path, monkeypatch):
    _seed_gr(tmp_path, monkeypatch, "to-read", _gr_book("r1", "Alpha", "to-read"))

    body = client.get("/api/library/unified").json()
    entry = body["shelves"][1]["groups"][0]["books"][0]  # tbr
    assert entry["book_id"] is None
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

    completed_groups = by_shelf["completed"]["groups"]
    assert len(completed_groups) == 1
    assert completed_groups[0]["series"] == "Ironbound"
    assert [b["title"] for b in completed_groups[0]["books"]] == ["Cold Wind (Ironbound, #2)"]

    tbr_groups = by_shelf["tbr"]["groups"]
    assert len(tbr_groups) == 1
    assert tbr_groups[0]["series"] == "Ironbound"
    assert [b["title"] for b in tbr_groups[0]["books"]] == ["Iron Heart (Ironbound, #1)"]


def test_series_books_sorted_by_number(tmp_path, monkeypatch):
    _seed_gr(
        tmp_path, monkeypatch, "read",
        _gr_book("r1", "Cold Wind (Ironbound, #2)", "read", book_id="2"),
        _gr_book("r2", "Iron Heart (Ironbound, #1)", "read", book_id="1"),
        _gr_book("r3", "Steel Dawn (Ironbound, #3)", "read", book_id="3"),
    )

    body = client.get("/api/library/unified").json()
    completed = next(s for s in body["shelves"] if s["shelf"] == "completed")
    titles = [b["display_title"] for b in completed["groups"][0]["books"]]
    assert titles == ["Iron Heart", "Cold Wind", "Steel Dawn"]


def test_standalone_entries_each_form_their_own_group(tmp_path, monkeypatch):
    _seed_gr(
        tmp_path, monkeypatch, "read",
        _gr_book("r1", "Zebra Tale", "read", date_added="2024-01-02T00:00:00+00:00"),
        _gr_book("r2", "Apple Story", "read", date_added="2024-01-01T00:00:00+00:00"),
    )

    body = client.get("/api/library/unified").json()
    completed = next(s for s in body["shelves"] if s["shelf"] == "completed")
    assert len(completed["groups"]) == 2
    assert all(len(g["books"]) == 1 for g in completed["groups"])
    # Groups ordered by anchor (date_read/date_added) descending.
    titles = [g["books"][0]["title"] for g in completed["groups"]]
    assert titles == ["Zebra Tale", "Apple Story"]


def test_display_title_strips_series_suffix(tmp_path, monkeypatch):
    _seed_gr(tmp_path, monkeypatch, "read", _gr_book("r1", "Cold Wind (Ironbound, #2)", "read"))

    body = client.get("/api/library/unified").json()
    completed = next(s for s in body["shelves"] if s["shelf"] == "completed")
    book = completed["groups"][0]["books"][0]
    assert book["title"] == "Cold Wind (Ironbound, #2)"
    assert book["display_title"] == "Cold Wind"
    assert book["series"] == "Ironbound"
    assert book["series_number"] == 2


def test_series_group_ordered_by_most_recently_touched_volume(tmp_path, monkeypatch):
    """Finishing volume 3 should slot the whole series in beside volumes 1-2, not jump to the front."""
    _seed_gr(
        tmp_path, monkeypatch, "read",
        _gr_book(
            "r1", "Iron Heart (Ironbound, #1)", "read", book_id="1",
            date_added="2020-01-01T00:00:00+00:00", date_read="2020-02-01T00:00:00+00:00",
        ),
        _gr_book(
            "r2", "Cold Wind (Ironbound, #2)", "read", book_id="2",
            date_added="2020-03-01T00:00:00+00:00", date_read="2020-04-01T00:00:00+00:00",
        ),
        _gr_book(
            "r3", "Steel Dawn (Ironbound, #3)", "read", book_id="3",
            date_added="2024-01-01T00:00:00+00:00", date_read="2026-08-01T00:00:00+00:00",
        ),
        _gr_book(
            "r4", "Unrelated Newer Book", "read", book_id="9",
            date_added="2025-01-01T00:00:00+00:00", date_read="2025-06-01T00:00:00+00:00",
        ),
    )

    body = client.get("/api/library/unified").json()
    completed = next(s for s in body["shelves"] if s["shelf"] == "completed")
    groups = completed["groups"]

    ironbound = next(g for g in groups if g["series"] == "Ironbound")
    assert [b["series_number"] for b in ironbound["books"]] == [1, 2, 3]

    # Ironbound (anchored by volume 3's 2026 date_read) sorts ahead of the unrelated 2025 book.
    assert groups[0]["series"] == "Ironbound"


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
        for group in s["groups"]:
            for entry in group["books"]:
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


# -- cross-thread connection safety -------------------------------------------
#
# FastAPI can run a request's dependency and its route body on different
# threadpool threads. `_get_goodreads_db` must open its connection with
# `check_same_thread=False` (goodreads.connect's default is True, for CLI/test
# callers) or this 500s under real concurrency -- a single sequential `curl`
# won't reliably reproduce it, which is why this test fires many requests
# from a thread pool instead.


def test_unified_endpoint_survives_concurrent_requests(tmp_path, monkeypatch):
    _seed_gr(tmp_path, monkeypatch, "read", _gr_book("r1", "Alpha", "read"))

    # One sequential warm-up request creates index.db's schema first --
    # racing *first-time* schema creation across threads is a separate,
    # pre-existing concern from the one this test targets (the goodreads
    # connection's check_same_thread flag).
    assert client.get("/api/library/unified").status_code == 200

    def fetch(_: int) -> int:
        return client.get("/api/library/unified").status_code

    with ThreadPoolExecutor(max_workers=16) as pool:
        statuses = list(pool.map(fetch, range(40)))

    assert statuses == [200] * len(statuses)
