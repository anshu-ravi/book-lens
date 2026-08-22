"""Tests for booklens.goodreads.link: title matching and the goodreads_link table.

Offline throughout -- no network, no real cookie. `match_keys` is exercised
against the two real-world title shapes noted in the brief (a colon-suffixed
Goodreads title, and a series suffix on the library side).
"""

from __future__ import annotations

from booklens import db, goodreads
from booklens.goodreads import store
from booklens.goodreads.feed import GoodreadsBook, ShelfFetch
from booklens.goodreads.link import (Link, Unmatched, apply_links, autolink,
                                      link_for_book, linked_book_ids,
                                      match_keys, propose_links, remove_link,
                                      set_link)


def _isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("BOOKLENS_DATA_DIR", str(tmp_path / "data"))


def _insert_book(iconn, book_id, title, *, author="Some Author", series_id="s", book_order=1):
    iconn.execute(
        """
        INSERT INTO book(id, sha256, title, author, source_path, series_id,
                          book_order, sequence_tier, label_tier, ingested_at, standalone)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'spine', 'toc', '2024-01-01T00:00:00+00:00', 0)
        """,
        (book_id, f"sha-{book_id}", title, author, f"/tmp/{book_id}.epub", series_id, book_order),
    )
    iconn.commit()


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
        cover_large=None,
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


def _seed_gr(gconn, shelf, *books):
    store.upsert_shelf(gconn, ShelfFetch(shelf=shelf, books=books, truncated=False))


# -- match_keys -----------------------------------------------------------------


def test_match_keys_colon_subtitle_real_world_case():
    """'The Sword of Kaigen: A Theonite War Story' must match 'The Sword of Kaigen'."""
    a = match_keys("The Sword of Kaigen: A Theonite War Story")
    b = match_keys("The Sword of Kaigen")
    assert a & b


def test_match_keys_series_suffix_and_subtitle_real_world_case():
    """'Mistborn: The Final Empire (Mistborn, #1)' must match 'The Final Empire'."""
    a = match_keys("Mistborn: The Final Empire (Mistborn, #1)")
    b = match_keys("The Final Empire")
    assert a & b


def test_match_keys_unrelated_titles_do_not_intersect():
    assert not (match_keys("The Sword of Kaigen") & match_keys("Cold Wind"))


# -- propose_links ----------------------------------------------------------------


def test_propose_links_unique_match(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    iconn = db.connect_index()
    gconn = goodreads.connect()
    try:
        _insert_book(iconn, "cold-wind", "Cold Wind")
        _seed_gr(gconn, "read", _gr_book("r1", "Cold Wind (Ironbound, #2)", "read", book_id="7235533"))

        links, unmatched = propose_links(iconn, gconn)
        assert links == [Link(book_id="cold-wind", goodreads_book_id="7235533")]
        assert unmatched == []
    finally:
        iconn.close()
        gconn.close()


def test_propose_links_ambiguous_leaves_book_unlinked(tmp_path, monkeypatch):
    """Two Goodreads entries sharing a normalised key must not be guessed at."""
    _isolate(tmp_path, monkeypatch)
    iconn = db.connect_index()
    gconn = goodreads.connect()
    try:
        _insert_book(iconn, "the-heist", "The Heist")
        _seed_gr(
            gconn, "read",
            _gr_book("r1", "The Heist", "read", book_id="111"),
            _gr_book("r2", "The Heist", "read", book_id="222"),
        )

        links, unmatched = propose_links(iconn, gconn)
        assert links == []
        assert len(unmatched) == 1
        u = unmatched[0]
        assert u.book_id == "the-heist"
        assert u.reason == "ambiguous"
        assert set(u.candidates) == {"111", "222"}
    finally:
        iconn.close()
        gconn.close()


def test_propose_links_no_match(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    iconn = db.connect_index()
    gconn = goodreads.connect()
    try:
        _insert_book(iconn, "orphan-book", "A Completely Unrelated Title")
        _seed_gr(gconn, "read", _gr_book("r1", "Cold Wind", "read", book_id="7235533"))

        links, unmatched = propose_links(iconn, gconn)
        assert links == []
        assert unmatched == [
            Unmatched(book_id="orphan-book", title="A Completely Unrelated Title", reason="no_match")
        ]
    finally:
        iconn.close()
        gconn.close()


def test_propose_links_skips_already_linked_books(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    iconn = db.connect_index()
    gconn = goodreads.connect()
    try:
        _insert_book(iconn, "cold-wind", "Cold Wind")
        _seed_gr(gconn, "read", _gr_book("r1", "Cold Wind", "read", book_id="7235533"))
        apply_links(gconn, [Link(book_id="cold-wind", goodreads_book_id="7235533")])

        links, unmatched = propose_links(iconn, gconn)
        assert links == []
        assert unmatched == []
    finally:
        iconn.close()
        gconn.close()


# -- apply_links ------------------------------------------------------------------


def test_apply_links_does_not_clobber_manual_link(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    gconn = goodreads.connect()
    try:
        set_link(gconn, "cold-wind", "manual-choice", source="manual")

        written = apply_links(gconn, [Link(book_id="cold-wind", goodreads_book_id="auto-guess")], source="auto")
        assert written == 0
        assert link_for_book(gconn, "cold-wind") == "manual-choice"
    finally:
        gconn.close()


def test_apply_links_writes_new_and_updates_auto_links(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    gconn = goodreads.connect()
    try:
        written = apply_links(gconn, [Link(book_id="cold-wind", goodreads_book_id="111")], source="auto")
        assert written == 1
        assert link_for_book(gconn, "cold-wind") == "111"

        written = apply_links(gconn, [Link(book_id="cold-wind", goodreads_book_id="222")], source="auto")
        assert written == 1
        assert link_for_book(gconn, "cold-wind") == "222"
    finally:
        gconn.close()


def test_set_link_overwrites_an_earlier_manual_link(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    gconn = goodreads.connect()
    try:
        set_link(gconn, "cold-wind", "111", source="manual")
        set_link(gconn, "cold-wind", "222", source="manual")
        assert link_for_book(gconn, "cold-wind") == "222"
    finally:
        gconn.close()


def test_remove_link(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    gconn = goodreads.connect()
    try:
        set_link(gconn, "cold-wind", "111", source="manual")
        remove_link(gconn, "cold-wind")
        assert link_for_book(gconn, "cold-wind") is None
    finally:
        gconn.close()


def test_linked_book_ids_maps_goodreads_id_to_book_id(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    gconn = goodreads.connect()
    try:
        set_link(gconn, "cold-wind", "111", source="auto")
        assert linked_book_ids(gconn) == {"111": "cold-wind"}
    finally:
        gconn.close()


# -- autolink ---------------------------------------------------------------------


def test_autolink_report_counts(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    iconn = db.connect_index()
    gconn = goodreads.connect()
    try:
        _insert_book(iconn, "cold-wind", "Cold Wind", series_id="s1", book_order=1)
        _insert_book(iconn, "the-heist", "The Heist", series_id="s2", book_order=1)
        _insert_book(iconn, "orphan-book", "A Completely Unrelated Title", series_id="s3", book_order=1)
        _seed_gr(
            gconn, "read",
            _gr_book("r1", "Cold Wind", "read", book_id="7235533"),
            _gr_book("r2", "The Heist", "read", book_id="111"),
            _gr_book("r3", "The Heist", "read", book_id="222"),
        )

        report = autolink(iconn, gconn)
        assert report.linked == 1
        assert report.already_linked == 0
        assert report.ambiguous == 1
        assert report.unmatched == 1
        assert link_for_book(gconn, "cold-wind") == "7235533"

        # A second run: the linked book no longer counts as newly linked.
        report2 = autolink(iconn, gconn)
        assert report2.linked == 0
        assert report2.already_linked == 1
    finally:
        iconn.close()
        gconn.close()


def test_autolink_never_overwrites_a_manual_link(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    iconn = db.connect_index()
    gconn = goodreads.connect()
    try:
        _insert_book(iconn, "cold-wind", "Cold Wind")
        _seed_gr(gconn, "read", _gr_book("r1", "Cold Wind", "read", book_id="7235533"))
        set_link(gconn, "cold-wind", "manual-choice", source="manual")

        report = autolink(iconn, gconn)
        assert link_for_book(gconn, "cold-wind") == "manual-choice"
        assert report.linked == 0
        assert report.already_linked == 1
    finally:
        iconn.close()
        gconn.close()
