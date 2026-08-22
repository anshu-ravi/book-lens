"""Tests for booklens.goodreads: RSS parsing, the shelf cache, and the CLI.

All synthetic -- fictional titles/authors, no real Goodreads data and nothing
from The Stormlight Archive per CLAUDE.md. Every test is offline: network
calls go through a stubbed `httpx` client (`httpx.MockTransport`) or are
never reached at all.
"""

from __future__ import annotations

import json

import httpx
import pytest

from booklens import cli
from booklens.goodreads import feed, store
from booklens.goodreads.feed import (FEED_ITEM_CAP, GoodreadsError,
                                      ShelfFetch, fetch_shelf,
                                      normalize_user_id, parse_feed)


# -- fixtures -------------------------------------------------------------


def _item_xml(
    *,
    review_id="1001",
    book_id="501",
    title="The Glass Orchard",
    author="Mira Voss",
    isbn="9781111111111",
    num_pages="342",
    published="2019",
    user_rating="4",
    user_read_at="Tue, 04 Aug 2026 23:54:14 -0700",
    user_date_added="Tue, 4 Aug 2026 00:00:00 +0000",
    user_date_created="Mon, 3 Aug 2026 00:00:00 +0000",
    user_shelves="",
) -> str:
    num_pages_xml = f"<num_pages>{num_pages}</num_pages>" if num_pages else ""
    return f"""
    <item>
      <guid>https://www.goodreads.com/review/show/{review_id}</guid>
      <pubDate>{user_date_added}</pubDate>
      <title>{title}</title>
      <link>https://www.goodreads.com/review/show/{review_id}</link>
      <book_id>{book_id}</book_id>
      <book_image_url>https://images.example/x.jpg</book_image_url>
      <book_small_image_url>https://images.example/x.s.jpg</book_small_image_url>
      <book_medium_image_url>https://images.example/x.m.jpg</book_medium_image_url>
      <book_large_image_url>https://images.example/x.l.jpg</book_large_image_url>
      <book_description>&lt;p&gt;A quiet orchard hides a loud secret.&lt;/p&gt;</book_description>
      <author_name>{author}</author_name>
      <isbn>{isbn}</isbn>
      <user_name>reader</user_name>
      <user_rating>{user_rating}</user_rating>
      <user_read_at>{user_read_at}</user_read_at>
      <user_date_added>{user_date_added}</user_date_added>
      <user_date_created>{user_date_created}</user_date_created>
      <user_shelves>{user_shelves}</user_shelves>
      <user_review>Loved the pacing.</user_review>
      <average_rating>4.21</average_rating>
      <book_published>{published}</book_published>
      <book id="{book_id}">{num_pages_xml}</book>
    </item>
    """


def _feed_xml(items_xml: str) -> bytes:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0">
      <channel>
        <title>reader's shelf</title>
        {items_xml}
      </channel>
    </rss>
    """.encode("utf-8")


# -- parse_feed -------------------------------------------------------------


def test_parse_feed_extracts_full_item():
    xml = _feed_xml(_item_xml())
    books = parse_feed(xml, "read")
    assert len(books) == 1
    b = books[0]
    assert b.review_id == "1001"
    assert b.book_id == "501"
    assert b.title == "The Glass Orchard"
    assert b.author == "Mira Voss"
    assert b.isbn == "9781111111111"
    assert b.num_pages == 342
    assert b.published_year == 2019
    assert "loud secret" in b.description
    assert b.cover_small.endswith("x.s.jpg")
    assert b.cover_medium.endswith("x.m.jpg")
    assert b.cover_large.endswith("x.l.jpg")
    assert b.average_rating == pytest.approx(4.21)
    assert b.user_rating == 4
    assert b.user_review == "Loved the pacing."
    assert b.shelf == "read"
    assert b.date_added is not None
    assert b.date_read is not None
    assert b.date_created is not None
    assert b.date_started is None


def test_parse_feed_sparse_item_yields_none_not_exceptions():
    xml = _feed_xml(
        _item_xml(
            isbn="", num_pages="", user_rating="0", user_read_at="",
        )
    )
    books = parse_feed(xml, "to-read")
    assert len(books) == 1
    b = books[0]
    assert b.isbn is None
    assert b.num_pages is None
    assert b.user_rating is None
    assert b.date_read is None


def test_parse_feed_both_date_formats_and_garbage_date():
    padded = _item_xml(review_id="a", user_date_added="Tue, 04 Aug 2026 23:54:14 -0700")
    nonpadded = _item_xml(review_id="b", user_date_added="Tue, 4 Aug 2026 00:00:00 +0000")
    garbage = _item_xml(review_id="c", user_date_added="not-a-date")
    books = parse_feed(_feed_xml(padded + nonpadded + garbage), "read")
    assert books[0].date_added is not None
    assert books[1].date_added is not None
    assert books[2].date_added is None


def test_parse_feed_custom_shelves():
    xml = _feed_xml(_item_xml(user_shelves="favorites, book-club"))
    books = parse_feed(xml, "read")
    assert books[0].custom_shelves == ("favorites", "book-club")


def test_parse_feed_custom_shelves_drops_echoed_shelf_name():
    xml = _feed_xml(_item_xml(user_shelves="to-read, favourites"))
    books = parse_feed(xml, "to-read")
    assert books[0].custom_shelves == ("favourites",)


def test_parse_feed_custom_shelves_all_echo_yields_empty():
    xml = _feed_xml(_item_xml(user_shelves="to-read"))
    books = parse_feed(xml, "to-read")
    assert books[0].custom_shelves == ()


def test_truncated_true_at_cap_false_below():
    at_cap = "".join(_item_xml(review_id=str(i)) for i in range(FEED_ITEM_CAP))
    below_cap = "".join(_item_xml(review_id=str(i)) for i in range(FEED_ITEM_CAP - 1))

    def make_fetch(xml_items):
        books = parse_feed(_feed_xml(xml_items), "read")
        return ShelfFetch(shelf="read", books=books, truncated=len(books) >= FEED_ITEM_CAP)

    assert make_fetch(at_cap).truncated is True
    assert make_fetch(below_cap).truncated is False


def test_parse_feed_missing_channel_raises():
    with pytest.raises(GoodreadsError):
        parse_feed(b"<rss version='2.0'></rss>", "read")


def test_parse_feed_malformed_xml_raises():
    with pytest.raises(GoodreadsError):
        parse_feed(b"<rss><channel><item></rss>", "read")


# -- fetch_shelf: stubbed httpx client --------------------------------------


def _mock_client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_fetch_shelf_raises_on_500():
    def handler(request):
        return httpx.Response(500, content=b"server error")

    with pytest.raises(GoodreadsError):
        fetch_shelf("12345", "read", client=_mock_client(handler))


def test_fetch_shelf_raises_on_malformed_xml():
    def handler(request):
        return httpx.Response(200, content=b"not xml at all <<<")

    with pytest.raises(GoodreadsError):
        fetch_shelf("12345", "read", client=_mock_client(handler))


def test_fetch_shelf_success():
    def handler(request):
        assert "shelf=read" in str(request.url)
        return httpx.Response(200, content=_feed_xml(_item_xml()))

    result = fetch_shelf("12345", "read", client=_mock_client(handler))
    assert result.shelf == "read"
    assert len(result.books) == 1
    assert result.truncated is False


# -- store: upsert_shelf idempotency / moves / deletion ---------------------


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("BOOKLENS_DATA_DIR", str(tmp_path / "data"))
    return tmp_path


@pytest.fixture
def gr_conn(data_dir):
    conn = store.connect()
    yield conn
    conn.close()


def _fetch(shelf, review_ids, truncated=False):
    items = "".join(_item_xml(review_id=r, title=f"Book {r}") for r in review_ids)
    books = parse_feed(_feed_xml(items), shelf)
    return ShelfFetch(shelf=shelf, books=books, truncated=truncated)


def test_upsert_shelf_idempotent(gr_conn):
    fetch = _fetch("read", ["1", "2", "3"])
    store.upsert_shelf(gr_conn, fetch)
    store.upsert_shelf(gr_conn, fetch)
    rows = gr_conn.execute("SELECT review_id FROM goodreads_book ORDER BY review_id").fetchall()
    assert [r["review_id"] for r in rows] == ["1", "2", "3"]


def test_book_moving_shelf_leaves_one_row(gr_conn):
    store.upsert_shelf(gr_conn, _fetch("currently-reading", ["7"]))
    store.upsert_shelf(gr_conn, _fetch("read", ["7"]))
    rows = gr_conn.execute("SELECT shelf FROM goodreads_book WHERE review_id = '7'").fetchall()
    assert len(rows) == 1
    assert rows[0]["shelf"] == "read"


def test_truncated_fetch_never_deletes(gr_conn):
    store.upsert_shelf(gr_conn, _fetch("read", ["1", "2"]))
    store.upsert_shelf(gr_conn, _fetch("read", ["1"], truncated=True))
    rows = gr_conn.execute("SELECT review_id FROM goodreads_book WHERE shelf = 'read'").fetchall()
    assert {r["review_id"] for r in rows} == {"1", "2"}


def test_complete_fetch_removes_vanished_book(gr_conn):
    store.upsert_shelf(gr_conn, _fetch("read", ["1", "2"]))
    store.upsert_shelf(gr_conn, _fetch("read", ["1"], truncated=False))
    rows = gr_conn.execute("SELECT review_id FROM goodreads_book WHERE shelf = 'read'").fetchall()
    assert {r["review_id"] for r in rows} == {"1"}


def test_complete_empty_fetch_clears_the_shelf(gr_conn):
    store.upsert_shelf(gr_conn, _fetch("read", ["1", "2"]))
    store.upsert_shelf(gr_conn, _fetch("to-read", ["9"]))
    store.upsert_shelf(gr_conn, _fetch("read", [], truncated=False))
    read_rows = gr_conn.execute("SELECT review_id FROM goodreads_book WHERE shelf = 'read'").fetchall()
    assert read_rows == []
    other_rows = gr_conn.execute("SELECT review_id FROM goodreads_book WHERE shelf = 'to-read'").fetchall()
    assert {r["review_id"] for r in other_rows} == {"9"}


def test_truncated_empty_fetch_deletes_nothing(gr_conn):
    store.upsert_shelf(gr_conn, _fetch("read", ["1", "2"]))
    store.upsert_shelf(gr_conn, _fetch("read", [], truncated=True))
    rows = gr_conn.execute("SELECT review_id FROM goodreads_book WHERE shelf = 'read'").fetchall()
    assert {r["review_id"] for r in rows} == {"1", "2"}


def test_books_on_shelf_and_all_books(gr_conn):
    store.upsert_shelf(gr_conn, _fetch("read", ["1"]))
    store.upsert_shelf(gr_conn, _fetch("to-read", ["2"]))
    assert [b.review_id for b in store.books_on_shelf(gr_conn, "read")] == ["1"]
    assert {b.review_id for b in store.all_books(gr_conn)} == {"1", "2"}


# -- store.sync: end-to-end against a stubbed client -------------------------


def _sync_handler(counts):
    def handler(request):
        shelf = str(request.url).split("shelf=")[-1]
        n = counts.get(shelf, 0)
        items = "".join(_item_xml(review_id=f"{shelf}-{i}") for i in range(n))
        return httpx.Response(200, content=_feed_xml(items))

    return handler


def test_sync_reports_per_shelf_counts_and_truncation(gr_conn, monkeypatch):
    monkeypatch.setattr(feed.time, "sleep", lambda _s: None)
    counts = {"read": 2, "currently-reading": 1, "to-read": 0, "did-not-finish": FEED_ITEM_CAP}
    client = _mock_client(_sync_handler(counts))
    report = store.sync(gr_conn, "12345", dnf_shelf="did-not-finish", client=client)
    assert report.shelf_counts == counts
    assert report.truncated_shelves == ("did-not-finish",)
    assert report.total_books == sum(counts.values())


# -- CLI: sync and shelf, end to end against a stubbed client ----------------


def test_cli_goodreads_sync_and_shelf(data_dir, capsys, monkeypatch):
    monkeypatch.setattr(feed.time, "sleep", lambda _s: None)
    counts = {"read": 1, "currently-reading": 1, "to-read": 1}

    def fake_get(url, headers=None, timeout=None):
        shelf = url.split("shelf=")[-1]
        n = counts.get(shelf, 0)
        items = "".join(_item_xml(review_id=f"{shelf}-{i}", title=f"{shelf} book {i}") for i in range(n))
        return httpx.Response(200, content=_feed_xml(items))

    monkeypatch.setattr(feed.httpx, "get", fake_get)

    rc = cli.main(["goodreads", "sync", "--user-id", "999", "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["shelf_counts"] == counts
    assert out["truncated_shelves"] == []
    assert out["total_books"] == 3

    rc = cli.main(["goodreads", "shelf", "read", "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert len(out) == 1
    assert out[0]["shelf"] == "read"

    rc = cli.main(["goodreads", "shelf", "all"])
    assert rc == 0
    text = capsys.readouterr().out
    assert "read book 0" in text
    assert "currently-reading book 0" in text
    assert "to-read book 0" in text


def test_cli_goodreads_sync_requires_user_id(data_dir, capsys):
    rc = cli.main(["goodreads", "sync"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "user id" in err


def test_cli_goodreads_sync_uses_env_var(data_dir, capsys, monkeypatch):
    monkeypatch.setattr(feed.time, "sleep", lambda _s: None)
    monkeypatch.setenv("GOODREADS_USER_ID", "42")

    def fake_get(url, headers=None, timeout=None):
        return httpx.Response(200, content=_feed_xml(""))

    monkeypatch.setattr(feed.httpx, "get", fake_get)
    rc = cli.main(["goodreads", "sync", "--json"])
    assert rc == 0


# -- feed.normalize_user_id ----------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("185528019", "185528019"),
        ("https://www.goodreads.com/user/show/185528019-anshumaan-ravi", "185528019"),
        (
            "https://www.goodreads.com/user/show/185528019-anshumaan-ravi?ref=nav_mybooks",
            "185528019",
        ),
        ("https://www.goodreads.com/user/show/185528019/", "185528019"),
        ("  185528019  ", "185528019"),
    ],
)
def test_normalize_user_id_accepted_forms(raw, expected):
    assert normalize_user_id(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "not-a-url",
        "https://www.goodreads.com/book/show/12345",
        "",
        "abc123",
        "https://example.com/user/show/185528019-anshumaan-ravi",
    ],
)
def test_normalize_user_id_rejects_garbage(raw):
    with pytest.raises(ValueError):
        normalize_user_id(raw)


# -- store.get_setting / set_setting -------------------------------------------


def test_get_setting_absent_is_none(gr_conn):
    assert store.get_setting(gr_conn, "user_id") is None


def test_set_and_get_setting_round_trip(gr_conn):
    store.set_setting(gr_conn, "user_id", "12345")
    assert store.get_setting(gr_conn, "user_id") == "12345"

    store.set_setting(gr_conn, "user_id", "67890")
    assert store.get_setting(gr_conn, "user_id") == "67890"


def test_set_setting_none_clears(gr_conn):
    store.set_setting(gr_conn, "dnf_shelf", "did-not-finish")
    store.set_setting(gr_conn, "dnf_shelf", None)
    assert store.get_setting(gr_conn, "dnf_shelf") is None


# -- CLI: --save persists the setting ------------------------------------------


def test_cli_goodreads_sync_save_persists_user_id(data_dir, capsys, monkeypatch):
    monkeypatch.setattr(feed.time, "sleep", lambda _s: None)

    def fake_get(url, headers=None, timeout=None):
        return httpx.Response(200, content=_feed_xml(""))

    monkeypatch.setattr(feed.httpx, "get", fake_get)

    rc = cli.main(["goodreads", "sync", "--user-id", "999", "--dnf-shelf", "dnf", "--save", "--json"])
    assert rc == 0

    conn = store.connect()
    try:
        assert store.get_setting(conn, "user_id") == "999"
        assert store.get_setting(conn, "dnf_shelf") == "dnf"
    finally:
        conn.close()

    # A subsequent sync with no flags falls back to the stored setting.
    rc = cli.main(["goodreads", "sync", "--json"])
    assert rc == 0
