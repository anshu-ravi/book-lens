"""Cookie-authenticated enrichment for start dates, read counts, and genres.

RSS (`feed.py`) stays the credential-free primary path. This module adds an
optional pass over the authenticated `/review/list` table view and per-book
`/book/show` pages, both of which require a Goodreads session cookie that
RSS does not need. The cookie is read from `GOODREADS_COOKIE` and is never
persisted, logged, or embedded in an exception message.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

import httpx
from lxml import html as lhtml

from booklens.goodreads.feed import GoodreadsError

_REVIEW_LIST_URL_TEMPLATE = (
    "https://www.goodreads.com/review/list/{user_id}?shelf={shelf}"
    "&per_page=100&page={page}&print=true&view=table"
)
_BOOK_SHOW_URL_TEMPLATE = "https://www.goodreads.com/book/show/{book_id}"
_USER_AGENT = "book-lens-v2/goodreads-sync (+https://github.com/; read-only shelf sync)"
_MAX_PAGES = 20

_EDIT_SUFFIX_RE = re.compile(r"\[edit\]\s*$", re.IGNORECASE)
_NULL_CELL_VALUES = {"not set", "—", "-", ""}

_MONTH_NAMES = {
    "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
    "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
}
_FULL_DATE_RE = re.compile(r"^(?P<mon>[A-Za-z]{3}) (?P<day>\d{1,2}), (?P<year>\d{4})$")
_MONTH_YEAR_RE = re.compile(r"^(?P<mon>[A-Za-z]{3}) (?P<year>\d{4})$")
_YEAR_ONLY_RE = re.compile(r"^(?P<year>\d{4})$")

# Embedded JSON inside the book page's script payload:
# `"name":"Fantasy","webUrl":"https://www.goodreads.com/genres/fantasy"`.
_GENRE_RE = re.compile(r'"name":"(?P<name>[^"]+)"\s*,\s*"webUrl":"https://www\.goodreads\.com/genres/[^"]+"')


class GoodreadsAuthError(GoodreadsError):
    """The cookie is missing, expired, or Goodreads bounced the request to sign-in."""


@dataclass(frozen=True)
class ReviewRow:
    review_id: str
    title: str
    date_started: str | None  # ISO-8601, precision matches what the reader recorded
    date_read: str | None
    read_count: int | None
    num_pages: int | None


def _cookie_or_raise(cookie: str | None) -> str:
    if cookie is not None:
        return cookie
    value = os.environ.get("GOODREADS_COOKIE")
    if not value:
        raise GoodreadsAuthError(
            "GOODREADS_COOKIE is not set -- authenticated enrichment requires a "
            "Goodreads session cookie in the environment"
        )
    return value


def _parse_review_date(text: str | None) -> str | None:
    """Parse a review-table date cell to ISO-8601, never guessing a missing day."""
    if not text:
        return None
    text = text.strip()

    m = _FULL_DATE_RE.match(text)
    if m:
        month = _MONTH_NAMES.get(m.group("mon"))
        if month is None:
            return None
        return f"{m.group('year')}-{month:02d}-{int(m.group('day')):02d}"

    m = _MONTH_YEAR_RE.match(text)
    if m:
        month = _MONTH_NAMES.get(m.group("mon"))
        if month is None:
            return None
        return f"{m.group('year')}-{month:02d}"

    m = _YEAR_ONLY_RE.match(text)
    if m:
        return m.group("year")

    return None


def _cell_text(td) -> str:
    parts = [t.strip() for t in td.itertext()]
    joined = " ".join(p for p in parts if p)
    return _EDIT_SUFFIX_RE.sub("", joined).strip()


def _clean_cell(td) -> str | None:
    text = _cell_text(td)
    return None if text.lower() in _NULL_CELL_VALUES else text


def _to_int(value: str | None) -> int | None:
    if value is None:
        return None
    digits = re.sub(r"[^\d]", "", value)
    if not digits:
        return None
    try:
        return int(digits)
    except ValueError:
        return None


def parse_review_table(html_bytes: bytes) -> tuple[ReviewRow, ...]:
    """Parse one page of the authenticated `/review/list` table view."""
    tree = lhtml.fromstring(html_bytes)
    rows = []
    for tr in tree.xpath('//tr[starts-with(@id, "review_")]'):
        review_id = (tr.get("id") or "").split("_", 1)[-1]
        if not review_id:
            continue

        fields: dict[str, str | None] = {}
        for td in tr.xpath(".//td"):
            classes = (td.get("class") or "").split()
            if "field" not in classes:
                continue
            name = next((c for c in classes if c != "field"), None)
            if name is None:
                continue
            fields[name] = _clean_cell(td)

        rows.append(
            ReviewRow(
                review_id=review_id,
                title=fields.get("title") or "",
                date_started=_parse_review_date(fields.get("date_started")),
                date_read=_parse_review_date(fields.get("date_read")),
                read_count=_to_int(fields.get("read_count")),
                num_pages=_to_int(fields.get("num_pages")),
            )
        )
    return tuple(rows)


def fetch_review_rows(
    user_id: str, *, shelf: str = "%23ALL%23", cookie: str | None = None, client=None
) -> tuple[ReviewRow, ...]:
    """Fetch every page of the authenticated review table for one shelf.

    Loops until a page yields zero rows, capped at `_MAX_PAGES`. A redirect
    response (the unauthenticated behaviour) raises `GoodreadsAuthError`
    rather than being followed into a sign-in page that would silently parse
    as an empty result.
    """
    resolved_cookie = _cookie_or_raise(cookie)
    getter = client.get if client is not None else httpx.get

    all_rows: list[ReviewRow] = []
    for page in range(1, _MAX_PAGES + 1):
        url = _REVIEW_LIST_URL_TEMPLATE.format(user_id=user_id, shelf=shelf, page=page)
        try:
            resp = getter(
                url,
                headers={"User-Agent": _USER_AGENT, "Cookie": resolved_cookie},
                timeout=30.0,
                follow_redirects=False,
            )
        except httpx.HTTPError as exc:
            raise GoodreadsError(
                f"request failed for review list page {page}: {type(exc).__name__}"
            ) from exc

        if 300 <= resp.status_code < 400:
            raise GoodreadsAuthError(
                "Goodreads redirected to sign-in fetching the review list -- "
                "GOODREADS_COOKIE is missing or expired"
            )
        if resp.status_code != 200:
            raise GoodreadsError(
                f"Goodreads returned status {resp.status_code} for review list page {page}"
            )

        page_rows = parse_review_table(resp.content)
        if not page_rows:
            break
        all_rows.extend(page_rows)

    return tuple(all_rows)


def parse_genres(html_bytes: bytes) -> tuple[str, ...]:
    """Extract the de-duplicated, vote-ordered genre list embedded in a book page."""
    text = html_bytes.decode("utf-8", errors="replace")
    seen: set[str] = set()
    genres = []
    for m in _GENRE_RE.finditer(text):
        name = m.group("name")
        if name not in seen:
            seen.add(name)
            genres.append(name)
    return tuple(genres)


def fetch_genres(book_id: str, *, cookie: str | None = None, client=None) -> tuple[str, ...]:
    """Fetch and parse one book's genre list from its `/book/show` page.

    Unauthenticated (or with an expired cookie) Goodreads returns a non-200
    bot-mitigation response here rather than a redirect, so any non-200 is
    treated as a hard failure -- the caller decides whether to stop.
    """
    resolved_cookie = _cookie_or_raise(cookie)
    getter = client.get if client is not None else httpx.get
    url = _BOOK_SHOW_URL_TEMPLATE.format(book_id=book_id)
    try:
        resp = getter(
            url, headers={"User-Agent": _USER_AGENT, "Cookie": resolved_cookie}, timeout=30.0
        )
    except httpx.HTTPError as exc:
        raise GoodreadsError(f"request failed for book {book_id!r}: {type(exc).__name__}") from exc

    if resp.status_code != 200:
        raise GoodreadsError(
            f"Goodreads returned status {resp.status_code} fetching genres for book {book_id!r}"
        )
    return parse_genres(resp.content)
