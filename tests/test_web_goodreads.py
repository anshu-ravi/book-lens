"""Tests for the Goodreads HTTP routes in booklens.web.app.

Every test is offline: syncing is monkeypatched so nothing ever calls the
real `goodreads.sync`, which is the only network-touching path here.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from booklens import goodreads
from booklens.goodreads.feed import GoodreadsBook, ShelfFetch
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
