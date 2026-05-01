"""Open Library search and metadata helpers.

Uses the Open Library Search API (no auth required):
  https://openlibrary.org/search.json?q=<query>&fields=...&limit=10
"""

import re
import logging
import httpx
from pydantic import BaseModel

logger = logging.getLogger(__name__)

OL_SEARCH_URL = "https://openlibrary.org/search.json"
OL_COVER_URL = "https://covers.openlibrary.org/b/id/{cover_id}-M.jpg"


class OLBookResult(BaseModel):
    """A single search result from Open Library."""

    ol_id: str  # e.g. "OL12345W"
    title: str
    author: str | None = None
    series_name: str | None = None
    series_position: float | None = None
    cover_url: str | None = None
    canonical_series_id: str  # slugified series_name or ol_id


def _canonical_series_id(series_name: str) -> str:
    """Convert series name to a stable slug."""
    slug = series_name.lower()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)  # strip punctuation
    slug = re.sub(r"\s+", "-", slug.strip())  # spaces → hyphens
    slug = re.sub(r"-+", "-", slug)  # collapse multiple hyphens
    return slug


def search_books(query: str, limit: int = 10) -> list[OLBookResult]:
    """Search Open Library and return up to `limit` results.

    Args:
        query: Free-text search (title, author, etc.)
        limit: Max results to return.

    Returns:
        List of OLBookResult objects, best matches first.
    """
    fields = "key,title,author_name,series,series_number,cover_i,subject"
    try:
        resp = httpx.get(
            OL_SEARCH_URL,
            params={"q": query, "fields": fields, "limit": limit},
            timeout=10.0,
        )
        resp.raise_for_status()
        docs = resp.json().get("docs", [])
    except Exception as exc:
        logger.warning("Open Library search failed: %s", exc)
        return []

    results: list[OLBookResult] = []
    for doc in docs:
        raw_key = doc.get("key", "")
        ol_id = raw_key.split("/")[-1] if raw_key else ""
        if not ol_id:
            continue

        title = doc.get("title", "").strip()
        if not title:
            continue

        authors = doc.get("author_name") or []
        author = authors[0] if authors else None

        series_list = doc.get("series") or []
        series_name = series_list[0].strip() if series_list else None

        # Fallback: parse "series:Some Name" entries from subject tags
        if not series_name:
            for subj in (doc.get("subject") or []):
                if subj.startswith("series:"):
                    series_name = subj[len("series:"):].strip()
                    break

        series_number_raw = doc.get("series_number") or []
        series_position: float | None = None
        if series_number_raw:
            try:
                series_position = float(str(series_number_raw[0]).strip())
            except (ValueError, TypeError):
                pass

        cover_id = doc.get("cover_i")
        cover_url = OL_COVER_URL.format(cover_id=cover_id) if cover_id else None

        if series_name:
            can_series_id = _canonical_series_id(series_name)
        else:
            can_series_id = ol_id

        results.append(
            OLBookResult(
                ol_id=ol_id,
                title=title,
                author=author,
                series_name=series_name,
                series_position=series_position,
                cover_url=cover_url,
                canonical_series_id=can_series_id,
            )
        )

    return results
