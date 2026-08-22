"""Reading statistics computed from the cached Goodreads shelves.

Pure functions over an open `goodreads.db` connection -- no network, no
mutation. Every metric except the to-read/currently-reading/backlog/series
figures is scoped to the `read` shelf, since the point is what was actually
read, not the whole cache.
"""

from __future__ import annotations

import re
import sqlite3
import statistics
from collections import Counter, defaultdict
from datetime import date

_SERIES_RE = re.compile(r"^(?P<base>.*)\s\((?P<series>[^,()]+),\s*#(?P<number>\d+(?:\.\d+)?)\)\s*$")

# Goodreads mixes these into a book's genre/shelf list; none of them are a
# genre, so they'd otherwise dominate every book's top-3 as "the" genre.
GENRE_DENYLIST = frozenset(
    s.lower() for s in (
        "Audiobook", "Audiobooks", "Ebook", "Ebooks", "Book Club",
        "Owned", "Currently Reading", "To Read", "Favorites",
    )
)


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


def strip_series_suffix(title: str) -> str:
    """A title with its trailing `(Series, #N)` suffix removed, for display.

    Returns `title` unchanged when it carries no parseable series marker.
    """
    match = _SERIES_RE.match(title.strip())
    return match.group("base").strip() if match is not None else title


def _to_series_number(raw: str) -> int | float:
    """A `parse_series` number string as JSON-friendly int or float."""
    value = float(raw)
    return int(value) if value.is_integer() else value


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
    with_date_started = sum(1 for r in read_rows if r["date_started"])
    with_genres = sum(1 for r in read_rows if r["genres"])
    return {
        "read_total": len(read_rows),
        "with_date_read": with_date_read,
        "with_date_started": with_date_started,
        "with_genres": with_genres,
    }


def _to_date(iso: str | None) -> date | None:
    """A full `YYYY-MM-DD` prefix as a `date`, or `None` for anything shorter or unparseable.

    Deliberately excludes month-only/year-only enrichment dates -- a
    duration needs day precision on both ends.
    """
    if not iso or len(iso) < 10:
        return None
    try:
        return date.fromisoformat(iso[:10])
    except ValueError:
        return None


def _durations(read_rows: list[sqlite3.Row]) -> dict:
    entries = []
    for r in read_rows:
        started = _to_date(r["date_started"])
        finished = _to_date(r["date_read"])
        if started is None or finished is None:
            continue
        days = (finished - started).days
        if days < 0:
            continue
        entries.append({
            "title": r["title"], "days": days,
            "pages": r["num_pages"], "rating": r["user_rating"],
        })

    if not entries:
        return {
            "count": 0, "median_days": None, "mean_days": None,
            "fastest": None, "slowest": None, "books": [],
        }

    entries.sort(key=lambda e: e["days"])
    days_list = [e["days"] for e in entries]
    return {
        "count": len(entries),
        "median_days": round(statistics.median(days_list)),
        "mean_days": round(sum(days_list) / len(days_list), 1),
        "fastest": {"title": entries[0]["title"], "days": entries[0]["days"]},
        "slowest": {"title": entries[-1]["title"], "days": entries[-1]["days"]},
        "books": entries,
    }


def _top3_genres(genres_field: str | None) -> list[str]:
    """The book's genres, denylist-filtered, capped at 3, in Goodreads' vote order."""
    if not genres_field:
        return []
    names = [g.strip() for g in genres_field.split(",") if g.strip()]
    return [g for g in names if g.lower() not in GENRE_DENYLIST][:3]


def _genres(read_rows: list[sqlite3.Row]) -> list[dict]:
    counts: Counter[str] = Counter()
    for r in read_rows:
        for g in _top3_genres(r["genres"]):
            counts[g] += 1
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return [{"genre": g, "books": n} for g, n in ranked[:12]]


def _rating_by_genre(read_rows: list[sqlite3.Row]) -> list[dict]:
    ratings: dict[str, list[int]] = defaultdict(list)
    for r in read_rows:
        if r["user_rating"] is None:
            continue
        for g in _top3_genres(r["genres"]):
            ratings[g].append(r["user_rating"])

    result = [
        {"genre": g, "avg_rating": round(sum(vals) / len(vals), 2), "books": len(vals)}
        for g, vals in ratings.items()
        if len(vals) >= 3
    ]
    result.sort(key=lambda e: -e["avg_rating"])
    return result


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


def _book_record(row: sqlite3.Row) -> dict:
    """A single finished-book record, as carried in a `by_month` entry."""
    parsed = parse_series(row["title"])
    return {
        "goodreads_book_id": row["book_id"],
        "title": strip_series_suffix(row["title"]),
        "author": row["author"],
        "series": parsed[0] if parsed else None,
        "series_number": _to_series_number(parsed[1]) if parsed else None,
        "cover": row["cover_large"] or row["cover_medium"] or row["cover_small"],
        "pages": row["num_pages"],
        "rating": row["user_rating"],
        "date_read": row["date_read"],
    }


def _by_month(read_rows: list[sqlite3.Row]) -> list[dict]:
    dated = [r for r in read_rows if r["date_read"]]
    if not dated:
        return []

    books_by_month: dict[str, list[sqlite3.Row]] = defaultdict(list)
    pages = defaultdict(int)
    for r in dated:
        key = _month_key(r["date_read"])
        books_by_month[key].append(r)
        pages[key] += r["num_pages"] or 0

    keys = sorted(books_by_month)
    full_range = _month_range(keys[0], keys[-1])
    result = []
    for m in full_range:
        rows = sorted(books_by_month.get(m, []), key=lambda r: (r["date_read"], r["title"]))
        result.append({
            "month": m,
            "count": len(rows),
            "pages": pages.get(m, 0),
            "books": [_book_record(r) for r in rows],
        })
    return result


def _top_authors(read_rows: list[sqlite3.Row]) -> list[dict]:
    """The most-read authors, capped at 10 -- authors read exactly once carry
    no ranking information and are excluded before the cap is applied."""
    counts = Counter(r["author"] for r in read_rows)
    ranked = sorted(
        ((author, n) for author, n in counts.items() if n >= 2),
        key=lambda kv: (-kv[1], kv[0]),
    )
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
        # A single unread TBR book that happens to be book one of a series
        # isn't a series the reader is tracking -- drop it. A series with
        # any read progress, or more than one volume owned, stays.
        if not (data["total"] == 1 and data["read"] == 0)
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
        "durations": _durations(read_rows),
        "genres": _genres(read_rows),
        "rating_by_genre": _rating_by_genre(read_rows),
    }
