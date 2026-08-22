"""Tests for matching an uploaded EPUB against the cached Goodreads shelf.

Offline throughout -- Goodreads data is written directly into the cache via
`goodreads.upsert_shelf`, never fetched over the network. Titles are
synthetic, per CLAUDE.md.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from booklens import cli, db, goodreads
from booklens.goodreads import store
from booklens.goodreads.feed import GoodreadsBook, ShelfFetch
from booklens.web.app import _author_tokens, app
from tests.test_ingest import _make_epub, _simple_epub

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


def _inspect(tmp_path, monkeypatch, epub_path: Path, filename: str | None = None):
    monkeypatch.setenv("BOOKLENS_DATA_DIR", str(tmp_path / "data"))
    db.connect_index().close()  # establish the data dir before inspecting
    with open(epub_path, "rb") as f:
        return client.post(
            "/api/upload/inspect",
            files={"file": (filename or epub_path.name, f, "application/epub+zip")},
        )


def _commit(tmp_path, monkeypatch, epub_path: Path, **overrides):
    resp = _inspect(tmp_path, monkeypatch, epub_path)
    assert resp.status_code == 200
    sha256 = resp.json()["sha256"]
    body = {"sha256": sha256, "series_id": "s1", "book_order": 1, "standalone": False, **overrides}
    return client.post("/api/upload/commit", json=body), sha256


def _ingest_epub(tmp_path, monkeypatch, epub_path: Path, series: str, order: int) -> None:
    _isolate(tmp_path, monkeypatch)
    rc = cli.main(["ingest", str(epub_path), "--series", series, "--start-order", str(order)])
    assert rc == 0


# -- _author_tokens ------------------------------------------------------------


def test_author_tokens_treats_goodreads_and_epub_forms_as_matching():
    goodreads_form = _author_tokens("Chakraborty, S.A.")
    epub_form = _author_tokens("S. A. Chakraborty")
    assert goodreads_form == epub_form
    assert goodreads_form == frozenset({"chakraborty", "s", "a"})


# -- exact title match -----------------------------------------------------------


def test_exact_title_match_returns_goodreads_match(tmp_path, monkeypatch):
    _seed_gr(
        tmp_path, monkeypatch, "to-read",
        _gr_book("r1", "The Amber Ledger (The Ledger Cycle, #2)", "to-read", book_id="900"),
    )
    epub = _simple_epub(tmp_path, name="amber.epub", title="The Amber Ledger")

    resp = _inspect(tmp_path, monkeypatch, epub)
    assert resp.status_code == 200
    body = resp.json()

    match = body["goodreads_match"]
    assert match is not None
    assert match["goodreads_book_id"] == "900"
    assert match["title"] == "The Amber Ledger"
    assert match["series"] == "The Ledger Cycle"
    assert match["series_number"] == 2
    assert match["linked_book_id"] is None


def test_exact_title_match_overrides_series_suggestion_ladder(tmp_path, monkeypatch):
    # An unrelated book by the same author, in a different series, so the
    # ladder's own answer (shared-authorship) differs from the Goodreads match.
    other = _make_epub(tmp_path / "other.epub", "Some Other Book", [("Chapter 1", ["Text."])], author="A. Author")
    _ingest_epub(tmp_path, monkeypatch, other, series="unrelated-series", order=1)

    _seed_gr(
        tmp_path, monkeypatch, "to-read",
        _gr_book("r1", "The Amber Ledger (The Ledger Cycle, #2)", "to-read", book_id="900", author="A. Author"),
    )
    epub = _make_epub(tmp_path / "amber.epub", "The Amber Ledger", [("Chapter 1", ["Text."])], author="A. Author")

    resp = _inspect(tmp_path, monkeypatch, epub)
    assert resp.status_code == 200
    body = resp.json()

    # The ladder alone would have suggested "unrelated-series" (shared authorship).
    assert body["suggested_series_id"] == "the-ledger-cycle"
    assert body["suggested_series_name"] == "The Ledger Cycle"
    assert body["suggested_book_order"] == 2


def test_noisy_epub_title_still_resolves_via_match_keys(tmp_path, monkeypatch):
    """The EPUB's own title carries extra text the Goodreads title does not."""
    _seed_gr(
        tmp_path, monkeypatch, "to-read",
        _gr_book("r1", "The Amber Ledger (The Ledger Cycle, #2)", "to-read", book_id="900"),
    )
    epub = _simple_epub(tmp_path, name="amber.epub", title="The Amber Ledger: Book Two of The Ledger Cycle")

    resp = _inspect(tmp_path, monkeypatch, epub)
    assert resp.status_code == 200
    body = resp.json()

    match = body["goodreads_match"]
    assert match is not None, (
        "noisy title did not resolve via match_keys -- real finding, not a weakened assertion"
    )
    assert match["goodreads_book_id"] == "900"


# -- ambiguity -----------------------------------------------------------------


def test_ambiguous_match_with_no_disambiguating_author_returns_none(tmp_path, monkeypatch):
    _seed_gr(
        tmp_path, monkeypatch, "to-read",
        _gr_book("r1", "Twilight Bloom", "to-read", book_id="1", author="Nadia Frost"),
        _gr_book("r2", "Twilight Bloom", "to-read", book_id="2", author="Elias Vance"),
    )
    epub = _make_epub(tmp_path / "tb.epub", "Twilight Bloom", [("Chapter 1", ["Text."])], author="Rowan Ashby")

    resp = _inspect(tmp_path, monkeypatch, epub)
    assert resp.status_code == 200
    assert resp.json()["goodreads_match"] is None


def test_ambiguous_match_disambiguated_by_author(tmp_path, monkeypatch):
    _seed_gr(
        tmp_path, monkeypatch, "to-read",
        _gr_book("r1", "Twilight Bloom", "to-read", book_id="1", author="Nadia Frost"),
        _gr_book("r2", "Twilight Bloom", "to-read", book_id="2", author="Elias Vance"),
    )
    epub = _make_epub(tmp_path / "tb.epub", "Twilight Bloom", [("Chapter 1", ["Text."])], author="Elias Vance")

    resp = _inspect(tmp_path, monkeypatch, epub)
    assert resp.status_code == 200
    match = resp.json()["goodreads_match"]
    assert match is not None
    assert match["goodreads_book_id"] == "2"


def test_no_match_leaves_series_suggestion_unchanged(tmp_path, monkeypatch):
    epub = _simple_epub(tmp_path, name="none.epub", title="Nothing Cached Matches This")

    resp = _inspect(tmp_path, monkeypatch, epub)
    assert resp.status_code == 200
    body = resp.json()
    assert body["goodreads_match"] is None
    assert body["suggested_series_id"] is None
    assert body["suggested_series_name"] is None
    assert body["prior_volumes"] == 0
    assert body["suggested_book_order"] == 1


def test_series_number_1_5_does_not_truncate_book_order(tmp_path, monkeypatch):
    # Ladder would otherwise suggest a non-1 order via shared authorship.
    filler = _make_epub(
        tmp_path / "filler.epub", "Filler Book", [("Chapter 1", ["Text."])], author="A. Author"
    )
    _ingest_epub(tmp_path, monkeypatch, filler, series="unrelated-series2", order=5)

    _seed_gr(
        tmp_path, monkeypatch, "to-read",
        _gr_book("r1", "Whatever Novella (Ledger Cycle, #1.5)", "to-read", book_id="777"),
    )
    epub = _make_epub(
        tmp_path / "novella.epub", "Whatever Novella", [("Chapter 1", ["Text."])], author="A. Author"
    )

    resp = _inspect(tmp_path, monkeypatch, epub)
    assert resp.status_code == 200
    body = resp.json()
    assert body["goodreads_match"]["series_number"] == 1.5
    assert body["suggested_series_id"] == "ledger-cycle"
    # Not int(1.5) == 1 -- the ladder's own answer (unrelated-series2, order 6) is kept.
    assert body["suggested_book_order"] == 6


# -- GET /api/goodreads/books/{id} ----------------------------------------------


def test_get_goodreads_book_returns_payload(tmp_path, monkeypatch):
    _seed_gr(
        tmp_path, monkeypatch, "read",
        _gr_book("r1", "Cold Wind (Ironbound, #2)", "read", book_id="42", author="I. Author"),
    )

    resp = client.get("/api/goodreads/books/42")
    assert resp.status_code == 200
    body = resp.json()
    assert body["goodreads_book_id"] == "42"
    assert body["title"] == "Cold Wind"
    assert body["series"] == "Ironbound"
    assert body["series_number"] == 2
    assert body["linked_book_id"] is None


def test_get_goodreads_book_404s_for_unknown_id(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    resp = client.get("/api/goodreads/books/does-not-exist")
    assert resp.status_code == 404


# -- POST /api/upload/commit with goodreads_book_id -----------------------------


def test_commit_with_goodreads_book_id_creates_link(tmp_path, monkeypatch):
    _seed_gr(
        tmp_path, monkeypatch, "read",
        _gr_book("r1", "Linked Title", "read", book_id="555"),
    )
    epub = _simple_epub(tmp_path, name="linked.epub", title="Linked Title")

    resp, _sha = _commit(tmp_path, monkeypatch, epub, goodreads_book_id="555")
    assert resp.status_code == 200
    body = resp.json()
    assert body["goodreads_book_id"] == "555"

    unified = client.get("/api/library/unified").json()
    all_entries = [
        entry
        for shelf in unified["shelves"]
        for group in shelf["groups"]
        for entry in group["books"]
    ]
    matching = [e for e in all_entries if e["goodreads_book_id"] == "555"]
    assert len(matching) == 1
    assert matching[0]["book_id"] == body["book_id"]
    assert matching[0]["askable"] is True


def test_commit_with_unknown_goodreads_book_id_returns_400_and_does_not_ingest(tmp_path, monkeypatch):
    epub = _simple_epub(tmp_path, name="unlinked.epub", title="Some Unlinked Book")
    resp, _sha = _commit(tmp_path, monkeypatch, epub, goodreads_book_id="does-not-exist")
    assert resp.status_code == 400

    _isolate(tmp_path, monkeypatch)
    iconn = db.connect_index()
    assert iconn.execute("SELECT COUNT(*) c FROM book").fetchone()["c"] == 0
