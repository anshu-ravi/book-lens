
import asyncio
import argparse
import sys
import os
from io import BytesIO
import logging

# Add the project root to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import anthropic
from src.config import settings
from src.supabase_client import get_supabase_client
from src.ingestion.epub_parser import parse_epub
from src.knowledge.pipeline import extract_book_knowledge
from src.library.manager import get_series, load_library
from src.knowledge.store import load_knowledge

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("manual_extract")

async def extract_one_book(user_id: str, series_id: str, book_index: int, anthropic_client: anthropic.AsyncAnthropic, concurrency: int = 2):
    """Run extraction for a single book if needed."""
    # 1. Fetch series to verify existence
    series = await get_series(series_id, user_id)
    if series is None:
        logger.error(f"Series '{series_id}' not found for user '{user_id}'.")
        return

    # 2. Check current knowledge base
    kb = await load_knowledge(series_id, user_id)
    book = next((b for b in series.books if b.index == book_index), None)
    if not book:
        logger.error(f"Book index {book_index} not found in series {series_id}")
        return
    
    extracted_count = sum(1 for ref in kb.extracted_chapters if ref.book_index == book_index)
    total_chapters = len(book.chapters)
    
    if extracted_count >= total_chapters and total_chapters > 0:
        logger.info(f"Skipping series={series_id}, book={book_index} ({book.title}) - already fully extracted ({extracted_count}/{total_chapters}).")
        return

    # 3. Download book file from Supabase Storage
    client = get_supabase_client()
    book_path = f"{user_id}/{series_id}/book_{book_index}.epub"
    logger.info(f"Downloading book from: {book_path} ({extracted_count}/{total_chapters} chapters done)")
    
    try:
        book_data = client.storage.from_("books").download(book_path)
    except Exception as e:
        logger.warning(f"Failed to download book {book_path}: {e}")
        return

    # 4. Parse EPUB
    try:
        parsed_chapters = parse_epub(BytesIO(book_data))
    except Exception as e:
        logger.error(f"Failed to parse EPUB: {e}")
        return

    # 5. Run Extraction
    logger.info(f"Starting extraction for series={series_id}, book={book_index}...")
    await extract_book_knowledge(
        chapters=parsed_chapters,
        series_id=series_id,
        book_index=book_index,
        user_id=user_id,
        client=anthropic_client,
        extraction_model=settings.extraction_model,
        concurrency=concurrency,
    )
    logger.info(f"Complete: series={series_id}, book={book_index}")

async def run_auto_extraction(user_id_filter: str = None, concurrency: int = 2):
    """Find all unextracted books and extract them."""
    client = get_supabase_client()
    
    # 1. Get all unique user IDs if no filter provided
    if user_id_filter:
        user_ids = [user_id_filter]
    else:
        logger.info("Fetching all users from database...")
        resp = client.table("series").select("user_id").execute()
        user_ids = list(set(item["user_id"] for item in resp.data))
        logger.info(f"Found {len(user_ids)} users.")

    anthropic_client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    for user_id in user_ids:
        logger.info(f"Checking library for user: {user_id}")
        library = await load_library(user_id)
        
        for series in library.series:
            for book in series.books:
                await extract_one_book(user_id, series.id, book.index, anthropic_client, concurrency)

def main():
    parser = argparse.ArgumentParser(description="Manually trigger knowledge extraction for a book.")
    parser.add_argument("--user-id", help="The user ID in Supabase.")
    parser.add_argument("--series-id", help="The series identifier.")
    parser.add_argument("--book-index", type=int, help="The 0-based book index.")
    parser.add_argument("--all", action="store_true", help="Extract all books in the library.")
    parser.add_argument("--concurrency", type=int, default=2, help="Max parallel chapters.")

    args = parser.parse_args()

    anthropic_client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    if args.series_id is not None and args.book_index is not None and args.user_id:
        asyncio.run(extract_one_book(args.user_id, args.series_id, args.book_index, anthropic_client, args.concurrency))
    elif args.all or (not args.user_id and not args.series_id and not args.book_index):
        logger.info(f"Starting automatic extraction for all books (concurrency={args.concurrency})...")
        asyncio.run(run_auto_extraction(args.user_id, args.concurrency))

    else:
        logger.error("Usage error: Provide all of --user-id, --series-id, --book-index OR run without arguments for auto-extraction.")
        sys.exit(1)

if __name__ == "__main__":
    main()
