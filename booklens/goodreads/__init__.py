"""Read-only Goodreads shelf sync via the public RSS feeds, cached in its own database.

An optional cookie-authenticated enrichment pass (`enrich.py`) layers start
dates, read counts, and genres on top -- RSS stays the primary, credential-
free path.
"""

from booklens.goodreads.enrich import (GoodreadsAuthError, ReviewRow,
                                        fetch_genres, fetch_review_rows,
                                        parse_genres, parse_review_table)
from booklens.goodreads.feed import (EXCLUSIVE_SHELVES, FEED_ITEM_CAP,
                                      GoodreadsBook, GoodreadsError,
                                      ShelfFetch, fetch_all_shelves,
                                      fetch_shelf, normalize_user_id,
                                      parse_feed)
from booklens.goodreads.link import (Link, LinkReport, Unmatched, apply_links,
                                      autolink, link_for_book,
                                      linked_book_ids, match_keys,
                                      propose_links, remove_link, set_link)
from booklens.goodreads.stats import (compute_stats, parse_series,
                                       strip_series_suffix)
from booklens.goodreads.store import (EnrichReport, SyncReport, all_books,
                                       apply_genres, apply_review_rows,
                                       books_needing_genres, books_on_shelf,
                                       connect, enrich, get_setting, init,
                                       set_setting, sync, upsert_shelf)

__all__ = [
    "compute_stats",
    "parse_series",
    "strip_series_suffix",
    "Link",
    "LinkReport",
    "Unmatched",
    "apply_links",
    "autolink",
    "link_for_book",
    "linked_book_ids",
    "match_keys",
    "propose_links",
    "remove_link",
    "set_link",
    "EXCLUSIVE_SHELVES",
    "FEED_ITEM_CAP",
    "GoodreadsBook",
    "GoodreadsError",
    "GoodreadsAuthError",
    "ShelfFetch",
    "fetch_all_shelves",
    "fetch_shelf",
    "normalize_user_id",
    "parse_feed",
    "SyncReport",
    "EnrichReport",
    "ReviewRow",
    "all_books",
    "apply_genres",
    "apply_review_rows",
    "books_needing_genres",
    "books_on_shelf",
    "connect",
    "enrich",
    "fetch_genres",
    "fetch_review_rows",
    "get_setting",
    "init",
    "parse_genres",
    "parse_review_table",
    "set_setting",
    "sync",
    "upsert_shelf",
]
