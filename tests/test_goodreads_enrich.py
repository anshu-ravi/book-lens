"""Cookie-authenticated enrichment: review-table parsing, genres, and additive writes.

Every test is offline and uses an obviously fake cookie -- a real session
cookie must never appear in the repository.
"""

import httpx
import pytest

from booklens.goodreads import store
from booklens.goodreads.enrich import (
    GoodreadsAuthError,
    fetch_genres,
    fetch_review_rows,
    parse_genres,
    parse_review_table,
)
from booklens.goodreads.feed import ShelfFetch, parse_feed

COOKIE = "test-cookie"


def _row_html(review_id, title, started, read, count="1", pages="412pp"):
    return f"""
    <tr id="review_{review_id}">
      <td class="field title"><div class="value"><a>{title}</a></div></td>
      <td class="field num_pages"><div class="value"><nobr>{pages}</nobr></div></td>
      <td class="field date_started"><div class="value">{started}<a>[edit]</a></div></td>
      <td class="field date_read"><div class="value">{read}<a>[edit]</a></div></td>
      <td class="field read_count"><div class="value">{count}</div></td>
    </tr>"""


def _table_html(*rows):
    return ("<html><body><table><tbody>" + "".join(rows) + "</tbody></table></body></html>").encode()


def _mock_client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


# -- the "not set [edit]" trap -------------------------------------------------


def test_unset_dates_are_null_despite_the_edit_suffix():
    """Goodreads renders an unset date as `not set [edit]`, so an equality check
    against "not set" silently counts every book as dated. This is the bug."""
    rows = parse_review_table(_table_html(_row_html("2", "The Glass Ledger", "not set", "not set")))
    assert rows[0].date_started is None
    assert rows[0].date_read is None


def test_real_dates_still_parse_with_the_edit_suffix():
    rows = parse_review_table(_table_html(_row_html("1", "Tidewrack", "Jun 21, 2026", "Jul 04, 2026")))
    assert rows[0].date_started == "2026-06-21"
    assert rows[0].date_read == "2026-07-04"


@pytest.mark.parametrize(
    "raw,expected",
    [("Jun 21, 2026", "2026-06-21"), ("Jun 2026", "2026-06"), ("2026", "2026"), ("gibberish", None)],
)
def test_all_recorded_date_precisions_parse(raw, expected):
    """A month- or year-only date keeps its precision rather than gaining a guessed day."""
    rows = parse_review_table(_table_html(_row_html("1", "T", raw, "not set")))
    assert rows[0].date_started == expected


def test_row_fields_are_typed():
    rows = parse_review_table(_table_html(_row_html("7", "Tidewrack", "Jun 21, 2026", "Jul 04, 2026", count="2")))
    assert rows[0].review_id == "7"
    assert rows[0].title == "Tidewrack"
    assert rows[0].read_count == 2
    assert rows[0].num_pages == 412


# -- genres --------------------------------------------------------------------


def _genre_blob(*names):
    return " ".join(
        f'"name":"{n}","webUrl":"https://www.goodreads.com/genres/{n.lower().replace(" ", "-")}"'
        for n in names
    ).encode()


def test_genres_are_deduplicated_in_page_order():
    assert parse_genres(_genre_blob("Epic Fantasy", "Fiction", "Epic Fantasy")) == (
        "Epic Fantasy",
        "Fiction",
    )


def test_genres_absent_yields_empty_tuple():
    assert parse_genres(b"<html><body>no genres here</body></html>") == ()


def test_fetch_genres_sends_the_cookie():
    seen = {}

    def handler(request):
        seen["cookie"] = request.headers.get("Cookie")
        return httpx.Response(200, content=_genre_blob("Fantasy"))

    assert fetch_genres("123", cookie=COOKIE, client=_mock_client(handler)) == ("Fantasy",)
    assert seen["cookie"] == COOKIE


# -- authentication failures ---------------------------------------------------


def test_sign_in_redirect_raises_rather_than_returning_empty():
    def handler(request):
        return httpx.Response(302, headers={"location": "https://www.goodreads.com/user/sign_in"})

    with pytest.raises(GoodreadsAuthError):
        fetch_review_rows("12345", cookie=COOKIE, client=_mock_client(handler))


def test_pagination_stops_on_the_first_empty_page():
    pages = {}

    def handler(request):
        page = int(dict(request.url.params).get("page", 1))
        pages[page] = True
        if page == 1:
            return httpx.Response(200, content=_table_html(_row_html("1", "A", "not set", "not set")))
        return httpx.Response(200, content=_table_html())

    rows = fetch_review_rows("12345", cookie=COOKIE, client=_mock_client(handler))
    assert len(rows) == 1
    assert max(pages) == 2


# -- additive writes -----------------------------------------------------------


@pytest.fixture
def gr_conn(tmp_path, monkeypatch):
    monkeypatch.setenv("BOOKLENS_DATA_DIR", str(tmp_path / "data"))
    conn = store.connect()
    yield conn
    conn.close()


def _seed(conn, *review_ids, date_read=""):
    """Seed the whole shelf in one upsert -- a second upsert would prune the first."""
    items = "".join(
        f"""<item>
      <guid>https://www.goodreads.com/review/show/{rid}</guid>
      <book_id>{rid}0</book_id><title>Seeded {rid}</title>
      <author_name>A</author_name><isbn></isbn><user_rating>4</user_rating>
      <user_read_at>{date_read}</user_read_at><user_date_added></user_date_added>
      <user_date_created></user_date_created><user_shelves></user_shelves>
      <user_review></user_review><average_rating>4.0</average_rating><book_published>2020</book_published>
    </item>"""
        for rid in review_ids
    )
    books = parse_feed(f"<rss><channel>{items}</channel></rss>".encode(), "read")
    store.upsert_shelf(conn, ShelfFetch(shelf="read", books=books, truncated=False))


def test_apply_review_rows_never_deletes(gr_conn):
    _seed(gr_conn, "1", "2")
    rows = parse_review_table(_table_html(_row_html("1", "Seeded 1", "Jun 21, 2026", "not set")))
    store.apply_review_rows(gr_conn, rows)
    assert gr_conn.execute("SELECT count(*) FROM goodreads_book").fetchone()[0] == 2


def test_apply_review_rows_fills_start_date(gr_conn):
    _seed(gr_conn, "1")
    rows = parse_review_table(_table_html(_row_html("1", "Seeded 1", "Jun 21, 2026", "not set", count="3")))
    store.apply_review_rows(gr_conn, rows)
    got = gr_conn.execute(
        "SELECT date_started, read_count, enriched_at FROM goodreads_book WHERE review_id='1'"
    ).fetchone()
    assert got["date_started"] == "2026-06-21"
    assert got["read_count"] == 3
    assert got["enriched_at"] is not None


def test_apply_review_rows_does_not_overwrite_an_existing_date_read(gr_conn):
    _seed(gr_conn, "1", date_read="Tue, 4 Aug 2026 00:00:00 +0000")
    before = gr_conn.execute("SELECT date_read FROM goodreads_book WHERE review_id='1'").fetchone()[0]
    rows = parse_review_table(_table_html(_row_html("1", "Seeded 1", "not set", "Jan 01, 2020")))
    store.apply_review_rows(gr_conn, rows)
    after = gr_conn.execute("SELECT date_read FROM goodreads_book WHERE review_id='1'").fetchone()[0]
    assert after == before


def test_empty_genre_result_is_stamped_so_it_is_not_refetched(gr_conn):
    _seed(gr_conn, "1")
    book_id = gr_conn.execute("SELECT book_id FROM goodreads_book WHERE review_id='1'").fetchone()[0]
    assert book_id in {b for b, _ in store.books_needing_genres(gr_conn)}
    store.apply_genres(gr_conn, book_id, ())
    assert book_id not in {b for b, _ in store.books_needing_genres(gr_conn)}


def test_review_id_drops_the_rss_query_string():
    """RSS guids carry `?utm_medium=api&utm_source=rss`. Keeping it made
    review_id unjoinable with the authenticated review table."""
    from booklens.goodreads.feed import parse_feed

    xml = b"""<rss><channel><item>
      <guid>https://www.goodreads.com/review/show/8228226382?utm_medium=api&amp;utm_source=rss</guid>
      <book_id>1</book_id><title>T</title><author_name>A</author_name>
    </item></channel></rss>"""
    assert parse_feed(xml, "read")[0].review_id == "8228226382"


def test_cell_text_reads_the_value_div_not_the_label():
    """Each cell carries a <label> naming the column; taking the whole <td>
    yields "date started not set", which is neither null nor a date."""
    rows = parse_review_table(
        b"""<table><tr id="review_9">
          <td class="field title"><label>title</label><div class="value"><a>Tidewrack</a></div></td>
          <td class="field date_started"><label>date started</label>
            <div class="value"><span>Jun 21, 2026</span><a>[edit]</a></div></td>
        </tr></table>"""
    )
    assert rows[0].title == "Tidewrack"
    assert rows[0].date_started == "2026-06-21"


def test_hidden_template_row_without_cells_is_skipped():
    html = b"""<table>
      <tr id="review_1"><td class="field title"><div class="value">Real</div></td></tr>
      <tr id="review_template"></tr>
    </table>"""
    assert [r.review_id for r in parse_review_table(html)] == ["1"]
