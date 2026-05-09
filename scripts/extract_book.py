#!/usr/bin/env python3
"""CLI script to manually trigger book extraction."""

import argparse
import asyncio
import logging
import sys
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

# Load environment variables
load_dotenv(Path(__file__).parent.parent / ".env")

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.knowledge.extraction_service import ExtractionService
from src.models import Chapter
from src.supabase_client import get_supabase_client

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


async def extract_book(
    user_id: str,
    book_id: str,
    limit: Optional[int] = None,
    refresh_mode: str = "skip",
    refresh_chapters: Optional[str] = None,
) -> None:
    """Extract knowledge for a specific book.

    Args:
        user_id: User identifier.
        book_id: Book identifier.
        limit: Maximum number of chapters to extract (for testing).
        refresh_mode: "skip" (default), "all", or "specific".
        refresh_chapters: Comma-separated chapter indices (for "specific" mode).
    """
    client = get_supabase_client()

    # Get book from database
    resp = (
        client.table("books")
        .select("id, title, series_id, chapters, epub_path")
        .filter("id", "eq", book_id)
        .filter("user_id", "eq", user_id)
        .execute()
    )

    if not resp.data:
        logger.error(f"Book {book_id} not found for user {user_id}")
        return

    book = resp.data[0]
    logger.info(f"Extracting book: {book['title']}")
    logger.info(f"Refresh mode: {refresh_mode}")
    if limit:
        logger.info(f"Limited to {limit} chapters")

    # Parse refresh_chapters
    refresh_ch_list = None
    if refresh_chapters:
        try:
            refresh_ch_list = [int(ch.strip()) for ch in refresh_chapters.split(",")]
            logger.info(f"Refreshing chapters: {refresh_ch_list}")
        except ValueError:
            logger.error("Invalid chapter indices format")
            return

    # Get EPUB from storage
    epub_path = book["epub_path"]
    try:
        epub_bytes = client.storage.from_("books").download(epub_path)
    except Exception as e:
        logger.error(f"Failed to download EPUB: {e}")
        return

    # Convert chapters dict to Chapter objects
    chapters = [
        Chapter(index=ch["index"], label=ch["label"]) for ch in book.get("chapters", [])
    ]

    # Run extraction
    series_id = book.get("series_id")
    service = ExtractionService(user_id, book_id, series_id)
    await service.extract_book(
        epub_bytes,
        chapters,
        limit=limit,
        series_id=series_id,
        refresh_mode=refresh_mode,
        refresh_chapters=refresh_ch_list,
    )
    logger.info("Extraction complete")


async def extract_all_for_user(
    user_id: str,
    limit: Optional[int] = None,
    refresh_mode: str = "skip",
    refresh_chapters: Optional[str] = None,
) -> None:
    """Extract knowledge for all books of a user.

    Args:
        user_id: User identifier.
        limit: Maximum number of chapters to extract per book (for testing).
        refresh_mode: "skip" (default), "all", or "specific".
        refresh_chapters: Comma-separated chapter indices (for "specific" mode).
    """
    client = get_supabase_client()

    # Get all books for user
    resp = (
        client.table("books")
        .select("id, title, chapters, epub_path")
        .filter("user_id", "eq", user_id)
        .execute()
    )

    if not resp.data:
        logger.warning(f"No books found for user {user_id}")
        return

    for book in resp.data:
        logger.info(f"Starting extraction for: {book['title']}")
        try:
            await extract_book(
                user_id,
                book["id"],
                limit=limit,
                refresh_mode=refresh_mode,
                refresh_chapters=refresh_chapters,
            )
        except Exception as e:
            logger.error(f"Extraction failed for {book['id']}: {e}", exc_info=True)
            continue


def main() -> None:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(description="Manually trigger book extraction")
    parser.add_argument("user_id", help="User ID")
    parser.add_argument(
        "--book-id",
        help="Specific book ID to extract (if not provided, extracts all user's books)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Extract up to this chapter index (e.g., --limit 15 extracts chapters 0-15)",
    )
    parser.add_argument(
        "--refresh",
        choices=["skip", "all", "specific"],
        default="skip",
        help="Refresh mode: skip (default, skip extracted), all (re-extract all), specific (re-extract specified chapters)",
    )
    parser.add_argument(
        "--refresh-chapters",
        help="Comma-separated chapter indices to refresh (e.g., 0,5,10). Only for --refresh=specific",
    )

    args = parser.parse_args()

    if args.book_id:
        asyncio.run(
            extract_book(
                args.user_id,
                args.book_id,
                args.limit,
                refresh_mode=args.refresh,
                refresh_chapters=args.refresh_chapters,
            )
        )
    else:
        asyncio.run(
            extract_all_for_user(
                args.user_id,
                args.limit,
                refresh_mode=args.refresh,
                refresh_chapters=args.refresh_chapters,
            )
        )


if __name__ == "__main__":
    main()
