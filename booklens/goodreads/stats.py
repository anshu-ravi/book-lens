"""Reading statistics computed from the cached Goodreads shelves.

Pure functions over an open `goodreads.db` connection -- no network, no
mutation. Every metric except the to-read/currently-reading/backlog/series
figures is scoped to the `read` shelf, since the point is what was actually
read, not the whole cache.
"""

from __future__ import annotations

import re
import sqlite3
from collections import Counter, defaultdict

_SERIES_RE = re.compile(r"^(?P<base>.*)\s\((?P<series>[^,()]+),\s*#(?P<number>\d+(?:\.\d+)?)\)\s*$")


def parse_series(title: str) -> tuple[str, str] | None:
    """Extract `(series_name, number)` from a trailing `(Series, #N)` suffix.

    Returns `None` when the title carries no parseable series marker. The
    number may be decimal (`#1.5`). A title with unrelated parentheses (no
    `, #N` inside) does not match.
    """
    match = _SERIES_RE.match(title.strip())
    if match is None:
        return None
    return match.group("series").strip(), match.group("number")


def _read_rows(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM goodreads_book WHERE shelf = 'read'").fetchall()


def _totals(read_rows: list[sqlite3.Row], conn: sqlite3.Connection) -> dict:
    books_read = len(read_rows)
    pages = [r["num_pages"] for r in read_rows if r["num_pages"] is not None]
    pages_read = sum(pages)
    avg_pages = round(pages_read / len(pages)) if pages else 0

    dnf_shelf = conn.execute(
        "SELECT value FROM goodreads_setting WHERE key = 'dnf_shelf'"
    ).fetchone()
    dnf = 0
    if dnf_shelf is not None:
        dnf = conn.execute(
            "SELECT COUNT(*) AS n FROM goodreads_book WHERE shelf = ?", (dnf_shelf["value"],)
        ).fetchone()["n"]
    want_to_read = conn.execute(
        "SELECT COUNT(*) AS n FROM goodreads_book WHERE shelf = 'to-read'"
    ).fetchone()["n"]
    currently_reading = conn.execute(
        "SELECT COUNT(*) AS n FROM goodreads_book WHERE shelf = 'currently-reading'"
    ).fetchone()["n"]
    backlog_pages = conn.execute(
        "SELECT COALESCE(SUM(num_pages), 0) AS n FROM goodreads_book WHERE shelf = 'to-read'"
    ).fetchone()["n"]

    longest = None
    shortest = None
    with_pages = [r for r in read_rows if r["num_pages"] is not None]
    if with_pages:
        longest_row = max(with_pages, key=lambda r: r["num_pages"])
        shortest_row = min(with_pages, key=lambda r: r["num_pages"])
        longest = {"title": longest_row["title"], "num_pages": longest_row["num_pages"]}
        shortest = {"title": shortest_row["title"], "num_pages": shortest_row["num_pages"]}

    return {
        "books_read": books_read,
        "pages_read": pages_read,
        "avg_pages": avg_pages,
        "dnf": dnf,
        "want_to_read": want_to_read,
        "currently_reading": currently_reading,
        "backlog_pages": backlog_pages,
        "longest": longest,
        "shortest": shortest,
    }


def _coverage(read_rows: list[sqlite3.Row]) -> dict:
    with_date_read = sum(1 for r in read_rows if r["date_read"])
    return {"read_total": len(read_rows), "with_date_read": with_date_read}


def _month_key(iso: str) -> str:
    return iso[:7]  # "YYYY-MM-DD..." -> "YYYY-MM"


def _month_range(start: str, end: str) -> list[str]:
    """Every "YYYY-MM" from `start` to `end` inclusive, ascending."""
    sy, sm = int(start[:4]), int(start[5:7])
    ey, em = int(end[:4]), int(end[5:7])
    months = []
    y, m = sy, sm
    while (y, m) <= (ey, em):
        months.append(f"{y:04d}-{m:02d}")
        m += 1
        if m > 12:
            m = 1
            y += 1
    return months


def _by_month(read_rows: list[sqlite3.Row]) -> list[dict]:
    dated = [r for r in read_rows if r["date_read"]]
    if not dated:
        return []

    books = Counter()
    pages = defaultdict(int)
    for r in dated:
        key = _month_key(r["date_read"])
        books[key] += 1
        pages[key] += r["num_pages"] or 0

    keys = sorted(books)
    full_range = _month_range(keys[0], keys[-1])
    return [
        {"month": m, "books": books.get(m, 0), "pages": pages.get(m, 0)}
        for m in full_range
    ]


def _top_authors(read_rows: list[sqlite3.Row]) -> list[dict]:
    counts = Counter(r["author"] for r in read_rows)
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return [{"author": author, "books": n} for author, n in ranked[:10]]


def _by_decade(read_rows: list[sqlite3.Row]) -> list[dict]:
    years = [r["published_year"] for r in read_rows if r["published_year"] is not None]
    if not years:
        return []

    counts = Counter((y // 10) * 10 for y in years)
    lo, hi = min(counts), max(counts)
    decades = range(lo, hi + 1, 10)
    return [{"decade": d, "books": counts.get(d, 0)} for d in decades]


def _series(conn: sqlite3.Connection) -> list[dict]:
    all_rows = conn.execute("SELECT title, shelf FROM goodreads_book").fetchall()

    grouped: dict[str, dict] = {}
    for row in all_rows:
        parsed = parse_series(row["title"])
        if parsed is None:
            continue
        name, _number = parsed
        entry = grouped.setdefault(name, {"total": 0, "read": 0, "shelves": set()})
        entry["total"] += 1
        entry["shelves"].add(row["shelf"])
        if row["shelf"] == "read":
            entry["read"] += 1

    result = [
        {
            "name": name,
            "read": data["read"],
            "total": data["total"],
            "shelves": sorted(data["shelves"]),
        }
        for name, data in grouped.items()
    ]

    def sort_key(entry: dict) -> tuple[int, str]:
        partial = 0 < entry["read"] < entry["total"]
        return (0 if partial else 1, entry["name"])

    result.sort(key=sort_key)
    return result


def compute_stats(conn: sqlite3.Connection) -> dict:
    """The full stats payload for `GET /api/goodreads/stats`.

    Always returns the same shape, zeroed out and with empty lists for an
    empty cache -- never raises on missing data.
    """
    read_rows = _read_rows(conn)
    return {
        "totals": _totals(read_rows, conn),
        "coverage": _coverage(read_rows),
        "by_month": _by_month(read_rows),
        "top_authors": _top_authors(read_rows),
        "by_decade": _by_decade(read_rows),
        "series": _series(conn),
    }
