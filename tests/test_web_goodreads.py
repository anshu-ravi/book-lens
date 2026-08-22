"""Tests for the Goodreads HTTP routes in booklens.web.app.

Every test is offline: syncing is monkeypatched so nothing ever calls the
real `goodreads.sync`, which is the only network-touching path here.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from booklens import cli, goodreads, paths
from booklens.goodreads.feed import GoodreadsBook, ShelfFetch
from booklens.web.app import app
from tests.test_ingest import _simple_epub

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
        cover_small="http://example.com/s.jpg",
        cover_medium="http://example.com/m.jpg",
        cover_large="http://example.com/l.jpg",
        average_rating=4.2,
        user_rating=5,
        user_review="great",
        shelf=shelf,
        custom_shelves=(),
        date_added="2024-01-01T00:00:00+00:00",
        date_read="2024-02-01T00:00:00+00:00",
        date_created="2024-01-01T00:00:00+00:00",
        date_started=None,
    )
    fields.update(overrides)
    return GoodreadsBook(**fields)


def _ingest(tmp_path, monkeypatch, name, title, series="s1", start_order=1):
    _isolate(tmp_path, monkeypatch)
    epub = _simple_epub(tmp_path, name=name, title=title)
    rc = cli.main(["ingest", str(epub), "--series", series, "--start-order", str(start_order)])
    assert rc == 0


def _seed(tmp_path, monkeypatch, fetches: dict[str, tuple[GoodreadsBook, ...]], truncated: set[str] = frozenset()):
    """Write books directly into the Goodreads cache without touching the network."""
    _isolate(tmp_path, monkeypatch)
    conn = goodreads.connect()
    try:
        for shelf, books in fetches.items():
            goodreads.upsert_shelf(conn, ShelfFetch(shelf=shelf, books=books, truncated=shelf in truncated))
    finally:
        conn.close()


# -- shelves ------------------------------------------------------------------


def test_shelves_never_synced_returns_empty(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)

    resp = client.get("/api/goodreads/shelves")
    assert resp.status_code == 200
    assert resp.json() == {"shelves": [], "total": 0, "synced_at": None}


def test_shelves_fixed_order_then_alphabetical_custom(tmp_path, monkeypatch):
    _seed(
        tmp_path,
        monkeypatch,
        {
            "to-read": (_book("r1", "To Read Book", "to-read"),),
            "read": (_book("r2", "Read Book", "read"),),
            "currently-reading": (_book("r3", "Current Book", "currently-reading"),),
            "zzz-custom": (_book("r4", "Custom Book", "zzz-custom"),),
        },
    )

    resp = client.get("/api/goodreads/shelves")
    assert resp.status_code == 200
    body = resp.json()

    assert [s["shelf"] for s in body["shelves"]] == [
        "currently-reading",
        "read",
        "to-read",
        "zzz-custom",
    ]
    assert body["total"] == 4
    assert body["synced_at"] is not None
    for s in body["shelves"]:
        assert s["count"] == 1


def test_shelves_truncated_flag_propagates(tmp_path, monkeypatch):
    _seed(
        tmp_path,
        monkeypatch,
        {"read": (_book("r1", "Book One", "read"),)},
        truncated={"read"},
    )

    resp = client.get("/api/goodreads/shelves")
    body = resp.json()
    assert body["shelves"] == [{"shelf": "read", "count": 1, "truncated": True}]


# -- books ----------------------------------------------------------------------


def test_books_filters_by_shelf_and_sorts_by_title(tmp_path, monkeypatch):
    _seed(
        tmp_path,
        monkeypatch,
        {
            "read": (
                _book("r1", "Zebra", "read"),
                _book("r2", "Apple", "read"),
            ),
            "to-read": (_book("r3", "Something Else", "to-read"),),
        },
    )

    resp = client.get("/api/goodreads/books", params={"shelf": "read"})
    assert resp.status_code == 200
    titles = [b["title"] for b in resp.json()["books"]]
    assert titles == ["Apple", "Zebra"]


def test_books_shelf_all_returns_everything(tmp_path, monkeypatch):
    _seed(
        tmp_path,
        monkeypatch,
        {
            "read": (_book("r1", "Zebra", "read"),),
            "to-read": (_book("r2", "Apple", "to-read"),),
        },
    )

    resp = client.get("/api/goodreads/books")
    assert resp.status_code == 200
    titles = [b["title"] for b in resp.json()["books"]]
    assert titles == ["Apple", "Zebra"]


def test_books_unknown_shelf_returns_empty_200(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch, {"read": (_book("r1", "Zebra", "read"),)})

    resp = client.get("/api/goodreads/books", params={"shelf": "nonexistent-shelf"})
    assert resp.status_code == 200
    assert resp.json() == {"books": []}


def test_books_custom_shelves_array_and_goodreads_url(tmp_path, monkeypatch):
    _seed(
        tmp_path,
        monkeypatch,
        {
            "read": (
                _book("r1", "Tagged Book", "read", book_id="99999", custom_shelves=("favorites", "2024")),
            )
        },
    )

    resp = client.get("/api/goodreads/books", params={"shelf": "read"})
    book = resp.json()["books"][0]
    assert book["custom_shelves"] == ["favorites", "2024"]
    assert book["goodreads_url"] == "https://www.goodreads.com/book/show/99999"


def test_books_null_fields_stay_null(tmp_path, monkeypatch):
    _seed(
        tmp_path,
        monkeypatch,
        {
            "read": (
                _book("r1", "Sparse Book", "read", isbn=None, date_read=None, date_started=None),
            )
        },
    )

    resp = client.get("/api/goodreads/books", params={"shelf": "read"})
    book = resp.json()["books"][0]
    assert book["isbn"] is None
    assert book["date_read"] is None
    assert book["date_started"] is None


# -- sync -----------------------------------------------------------------------


def test_sync_without_user_id_returns_400(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    monkeypatch.delenv("GOODREADS_USER_ID", raising=False)

    resp = client.post("/api/goodreads/sync", json={})
    assert resp.status_code == 400


def test_sync_goodreads_error_returns_502(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)

    def _raise(conn, user_id, *, dnf_shelf=None):
        raise goodreads.GoodreadsError("boom")

    monkeypatch.setattr(goodreads, "sync", _raise)

    resp = client.post("/api/goodreads/sync", json={"user_id": "abc123"})
    assert resp.status_code == 502
    assert "boom" in resp.json()["detail"]


def test_sync_happy_path_returns_report(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)

    def _fake_sync(conn, user_id, *, dnf_shelf=None):
        assert user_id == "abc123"
        assert dnf_shelf == "did-not-finish"
        return goodreads.SyncReport(
            shelf_counts={"read": 33, "to-read": 66, "currently-reading": 2, "did-not-finish": 1},
            truncated_shelves=(),
            total_books=102,
        )

    monkeypatch.setattr(goodreads, "sync", _fake_sync)

    resp = client.post(
        "/api/goodreads/sync", json={"user_id": "abc123", "dnf_shelf": "did-not-finish"}
    )
    assert resp.status_code == 200
    assert resp.json() == {
        "shelf_counts": {"read": 33, "to-read": 66, "currently-reading": 2, "did-not-finish": 1},
        "truncated_shelves": [],
        "total_books": 102,
    }


def test_sync_falls_back_to_env_user_id(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setenv("GOODREADS_USER_ID", "env-user")

    seen = {}

    def _fake_sync(conn, user_id, *, dnf_shelf=None):
        seen["user_id"] = user_id
        return goodreads.SyncReport(shelf_counts={}, truncated_shelves=(), total_books=0)

    monkeypatch.setattr(goodreads, "sync", _fake_sync)

    resp = client.post("/api/goodreads/sync", json={})
    assert resp.status_code == 200
    assert seen["user_id"] == "env-user"


# -- settings -------------------------------------------------------------------


def test_get_settings_none_configured(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    monkeypatch.delenv("GOODREADS_USER_ID", raising=False)

    resp = client.get("/api/goodreads/settings")
    assert resp.status_code == 200
    assert resp.json() == {"user_id": None, "dnf_shelf": None, "source": "none"}


def test_get_settings_falls_back_to_env(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setenv("GOODREADS_USER_ID", "env-user")

    resp = client.get("/api/goodreads/settings")
    assert resp.status_code == 200
    assert resp.json() == {"user_id": "env-user", "dnf_shelf": None, "source": "env"}


def test_put_settings_round_trip_and_stored_wins_over_env(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setenv("GOODREADS_USER_ID", "env-user")

    resp = client.put(
        "/api/goodreads/settings", json={"user_id": "185528019", "dnf_shelf": "did-not-finish"}
    )
    assert resp.status_code == 200
    assert resp.json() == {"user_id": "185528019", "dnf_shelf": "did-not-finish", "source": "stored"}

    resp = client.get("/api/goodreads/settings")
    assert resp.json() == {"user_id": "185528019", "dnf_shelf": "did-not-finish", "source": "stored"}


def test_put_settings_normalizes_profile_url(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)

    resp = client.put(
        "/api/goodreads/settings",
        json={"user_id": "https://www.goodreads.com/user/show/185528019-anshumaan-ravi"},
    )
    assert resp.status_code == 200
    assert resp.json()["user_id"] == "185528019"


def test_put_settings_rejects_garbage_user_id(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)

    resp = client.put("/api/goodreads/settings", json={"user_id": "not-a-url"})
    assert resp.status_code == 400
    assert "not-a-url" in resp.json()["detail"]


def test_put_settings_dnf_shelf_optional_and_nullable(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)

    client.put("/api/goodreads/settings", json={"user_id": "12345", "dnf_shelf": "dnf"})
    resp = client.put("/api/goodreads/settings", json={"user_id": "12345"})
    assert resp.status_code == 200
    assert resp.json()["dnf_shelf"] is None


# -- sync resolution order ------------------------------------------------------


def test_sync_prefers_explicit_body_over_stored_and_env(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setenv("GOODREADS_USER_ID", "env-user")
    client.put("/api/goodreads/settings", json={"user_id": "111111"})

    seen = {}

    def _fake_sync(conn, user_id, *, dnf_shelf=None):
        seen["user_id"] = user_id
        return goodreads.SyncReport(shelf_counts={}, truncated_shelves=(), total_books=0)

    monkeypatch.setattr(goodreads, "sync", _fake_sync)

    resp = client.post("/api/goodreads/sync", json={"user_id": "222222"})
    assert resp.status_code == 200
    assert seen["user_id"] == "222222"


def test_sync_uses_stored_user_id_when_body_omits_it(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    monkeypatch.delenv("GOODREADS_USER_ID", raising=False)
    client.put("/api/goodreads/settings", json={"user_id": "333333", "dnf_shelf": "dnf"})

    seen = {}

    def _fake_sync(conn, user_id, *, dnf_shelf=None):
        seen["user_id"] = user_id
        seen["dnf_shelf"] = dnf_shelf
        return goodreads.SyncReport(shelf_counts={}, truncated_shelves=(), total_books=0)

    monkeypatch.setattr(goodreads, "sync", _fake_sync)

    resp = client.post("/api/goodreads/sync", json={})
    assert resp.status_code == 200
    assert seen["user_id"] == "333333"
    assert seen["dnf_shelf"] == "dnf"


def test_sync_400_when_nothing_configured(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    monkeypatch.delenv("GOODREADS_USER_ID", raising=False)

    resp = client.post("/api/goodreads/sync", json={})
    assert resp.status_code == 400


# -- stats: month-strip cover fallback -------------------------------------------


def test_stats_month_cover_falls_back_to_linked_epub_cover(tmp_path, monkeypatch):
    _ingest(tmp_path, monkeypatch, "book.epub", "Cold Wind")
    (paths.book_dir("cold-wind")).mkdir(parents=True, exist_ok=True)
    (paths.book_dir("cold-wind") / "cover.jpg").write_bytes(b"fake-cover-bytes")

    _seed(
        tmp_path, monkeypatch,
        {
            "read": (
                _book(
                    "r1", "Cold Wind", "read", book_id="7235533",
                    cover_small=None, cover_medium=None, cover_large=None,
                    date_read="2025-03-05T00:00:00+00:00",
                ),
            ),
        },
    )
    conn = goodreads.connect()
    try:
        goodreads.set_link(conn, "cold-wind", "7235533", source="manual")
    finally:
        conn.close()

    body = client.get("/api/goodreads/stats").json()
    march = next(m for m in body["by_month"] if m["month"] == "2025-03")
    assert march["books"][0]["cover"] == "/api/books/cold-wind/cover"


def test_stats_month_cover_stays_none_without_link(tmp_path, monkeypatch):
    _seed(
        tmp_path, monkeypatch,
        {
            "read": (
                _book(
                    "r1", "Unlinked Book", "read", book_id="999",
                    cover_small=None, cover_medium=None, cover_large=None,
                    date_read="2025-03-05T00:00:00+00:00",
                ),
            ),
        },
    )

    body = client.get("/api/goodreads/stats").json()
    march = next(m for m in body["by_month"] if m["month"] == "2025-03")
    assert march["books"][0]["cover"] is None


def test_stats_month_cover_prefers_goodreads_url_when_present(tmp_path, monkeypatch):
    _ingest(tmp_path, monkeypatch, "book.epub", "Cold Wind")
    (paths.book_dir("cold-wind")).mkdir(parents=True, exist_ok=True)
    (paths.book_dir("cold-wind") / "cover.jpg").write_bytes(b"fake-cover-bytes")

    _seed(
        tmp_path, monkeypatch,
        {
            "read": (
                _book(
                    "r1", "Cold Wind", "read", book_id="7235533",
                    cover_large="http://example.com/large.jpg",
                    date_read="2025-03-05T00:00:00+00:00",
                ),
            ),
        },
    )
    conn = goodreads.connect()
    try:
        goodreads.set_link(conn, "cold-wind", "7235533", source="manual")
    finally:
        conn.close()

    body = client.get("/api/goodreads/stats").json()
    march = next(m for m in body["by_month"] if m["month"] == "2025-03")
    assert march["books"][0]["cover"] == "http://example.com/large.jpg"
