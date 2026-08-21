"""Fetch and parse Goodreads' public shelf RSS feeds.

The only module in this package that touches the network. The official
Goodreads API is dead; `list_rss` is the sole unauthenticated source, and it
caps every feed at `FEED_ITEM_CAP` items with pagination silently ignored --
callers must treat a full feed as possibly truncated, never as complete data.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from email.utils import parsedate_to_datetime

import httpx
from lxml import etree

EXCLUSIVE_SHELVES = ("read", "currently-reading", "to-read")
FEED_ITEM_CAP = 100

_FEED_URL_TEMPLATE = "https://www.goodreads.com/review/list_rss/{user_id}?shelf={shelf}"
_USER_AGENT = "book-lens-v2/goodreads-sync (+https://github.com/; read-only shelf sync)"
_REQUEST_DELAY_SECONDS = 1.0

_PROFILE_URL_RE = re.compile(
    r"^https?://(www\.)?goodreads\.com/user/show/(\d+)(-[^/?]*)?/?(\?.*)?$"
)


class GoodreadsError(Exception):
    """A shelf fetch failed -- non-200 response or unparseable XML."""


def normalize_user_id(raw: str) -> str:
    """Extract a bare numeric Goodreads user id from an id or a profile URL.

    Accepts a bare numeric id, or a `.../user/show/<digits>-<slug>` profile
    URL (with an optional trailing slash or query string, the two forms a
    browser address bar actually produces). Raises `ValueError` on anything
    else.
    """
    value = raw.strip()
    if value.isdigit():
        return value
    match = _PROFILE_URL_RE.match(value)
    if match:
        return match.group(2)
    raise ValueError(
        f"not a Goodreads user id or profile URL: {raw!r} -- expected a numeric id "
        "(e.g. '12345') or a profile URL (e.g. "
        "'https://www.goodreads.com/user/show/12345-your-name')"
    )


@dataclass(frozen=True)
class GoodreadsBook:
    review_id: str
    book_id: str
    title: str
    author: str
    isbn: str | None
    num_pages: int | None
    published_year: int | None
    description: str | None
    cover_small: str | None
    cover_medium: str | None
    cover_large: str | None
    average_rating: float | None
    user_rating: int | None  # None when 0/unrated
    user_review: str | None
    shelf: str  # the exclusive shelf this was fetched from
    custom_shelves: tuple[str, ...]  # parsed from user_shelves
    date_added: str | None  # ISO-8601
    date_read: str | None  # ISO-8601, from user_read_at
    date_created: str | None  # ISO-8601
    date_started: str | None  # always None from RSS


@dataclass(frozen=True)
class ShelfFetch:
    shelf: str
    books: tuple[GoodreadsBook, ...]
    truncated: bool  # True when len(books) >= FEED_ITEM_CAP


def _text(item, tag: str) -> str | None:
    """The stripped text of a child element, or None if absent/empty."""
    el = item.find(tag)
    if el is None or el.text is None:
        return None
    value = el.text.strip()
    return value or None


def _int(item, tag: str) -> int | None:
    value = _text(item, tag)
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _float(item, tag: str) -> float | None:
    value = _text(item, tag)
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _parse_date(value: str | None) -> str | None:
    """Parse an RFC-2822-ish Goodreads date to ISO-8601, tolerating both the
    zero-padded and non-padded day forms and any unparseable garbage."""
    if not value:
        return None
    try:
        return parsedate_to_datetime(value).isoformat()
    except (TypeError, ValueError):
        return None


def _review_id_from_guid(guid: str | None) -> str:
    """`guid` is a `/review/show/{review_id}` URL; the id is the stable identity."""
    if not guid:
        return ""
    return guid.rstrip("/").rsplit("/", 1)[-1]


def _custom_shelves(item) -> tuple[str, ...]:
    """`user_shelves` carries only custom tags for exclusive-shelf feeds."""
    raw = _text(item, "user_shelves")
    if not raw:
        return ()
    return tuple(s.strip() for s in raw.split(",") if s.strip())


def parse_feed(xml_bytes: bytes, shelf: str) -> tuple[GoodreadsBook, ...]:
    """Parse one shelf feed's raw XML into books, tagged with the shelf fetched."""
    try:
        root = etree.fromstring(xml_bytes)
    except etree.XMLSyntaxError as exc:
        raise GoodreadsError(f"could not parse feed XML for shelf {shelf!r}: {exc}") from exc

    channel = root.find("channel")
    if channel is None:
        raise GoodreadsError(f"feed for shelf {shelf!r} has no <channel> element")

    books = []
    for item in channel.findall("item"):
        user_rating = _int(item, "user_rating")
        book_el = item.find("book")
        num_pages = None
        if book_el is not None:
            num_pages = _int(book_el, "num_pages")

        books.append(
            GoodreadsBook(
                review_id=_review_id_from_guid(_text(item, "guid")),
                book_id=_text(item, "book_id") or "",
                title=_text(item, "title") or "",
                author=_text(item, "author_name") or "",
                isbn=_text(item, "isbn"),
                num_pages=num_pages,
                published_year=_int(item, "book_published"),
                description=_text(item, "book_description"),
                cover_small=_text(item, "book_small_image_url"),
                cover_medium=_text(item, "book_medium_image_url"),
                cover_large=_text(item, "book_large_image_url"),
                average_rating=_float(item, "average_rating"),
                user_rating=user_rating if user_rating else None,
                user_review=_text(item, "user_review"),
                shelf=shelf,
                custom_shelves=_custom_shelves(item),
                date_added=_parse_date(_text(item, "user_date_added")),
                date_read=_parse_date(_text(item, "user_read_at")),
                date_created=_parse_date(_text(item, "user_date_created")),
                date_started=None,
            )
        )
    return tuple(books)


def fetch_shelf(user_id: str, shelf: str, *, client=None) -> ShelfFetch:
    """Fetch and parse one exclusive shelf's feed.

    Raises `GoodreadsError` on a non-200 response or unparseable XML rather
    than returning an empty result -- a fetch failure must never look like an
    empty shelf.
    """
    url = _FEED_URL_TEMPLATE.format(user_id=user_id, shelf=shelf)
    getter = client.get if client is not None else httpx.get
    try:
        resp = getter(url, headers={"User-Agent": _USER_AGENT}, timeout=30.0)
    except httpx.HTTPError as exc:
        raise GoodreadsError(f"request failed for shelf {shelf!r}: {type(exc).__name__}") from exc

    if resp.status_code != 200:
        raise GoodreadsError(
            f"Goodreads returned status {resp.status_code} for shelf {shelf!r}"
        )

    books = parse_feed(resp.content, shelf)
    return ShelfFetch(shelf=shelf, books=books, truncated=len(books) >= FEED_ITEM_CAP)


def fetch_all_shelves(
    user_id: str, *, dnf_shelf: str | None = None, client=None
) -> dict[str, ShelfFetch]:
    """Fetch the three exclusive shelves plus `dnf_shelf` when given.

    Sequential with a fixed delay between requests -- polite by construction,
    never concurrent.
    """
    shelves = list(EXCLUSIVE_SHELVES)
    if dnf_shelf:
        shelves.append(dnf_shelf)

    results = {}
    for i, shelf in enumerate(shelves):
        if i > 0:
            time.sleep(_REQUEST_DELAY_SECONDS)
        results[shelf] = fetch_shelf(user_id, shelf, client=client)
    return results
