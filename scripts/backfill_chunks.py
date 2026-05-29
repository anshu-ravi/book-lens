"""Backfill vector chunk embeddings for an existing book without re-running the full pipeline."""

import asyncio
import sys

from src.ingestion.epub_parser import parse_epub
from src.knowledge.chunk_store import ChunkStore
from src.supabase_client import get_supabase_client

# ── Book to backfill ──────────────────────────────────────────────────────────
USER_ID = "d5203e02-a3d8-4b9b-ba4e-1b08c8ebdc46"
BOOK_ID = "7af3a69a-1d3a-4899-881d-a33eceaa69a9"
SERIES_ID = "the-red-rising-saga"
EPUB_PATH = "d5203e02-a3d8-4b9b-ba4e-1b08c8ebdc46/7af3a69a-1d3a-4899-881d-a33eceaa69a9/book.epub"
STORAGE_BUCKET = "books"
# ─────────────────────────────────────────────────────────────────────────────


def main() -> None:
    client = get_supabase_client()

    print(f"Downloading epub from storage: {EPUB_PATH}")
    epub_bytes = client.storage.from_(STORAGE_BUCKET).download(EPUB_PATH)
    print(f"Downloaded {len(epub_bytes):,} bytes")

    print("Parsing epub...")
    from io import BytesIO
    parsed_chapters = parse_epub(BytesIO(epub_bytes))
    print(f"Parsed {len(parsed_chapters)} chapters")

    chapter_tuples = [(ch.index, ch.label, ch.text) for ch in parsed_chapters]

    print("Embedding and storing chunks (this may take a minute)...")
    store = ChunkStore()
    n = store.upsert_chapters(
        user_id=USER_ID,
        series_id=SERIES_ID,
        book_id=BOOK_ID,
        chapters=chapter_tuples,
    )
    print(f"Done — stored {n} chunks for '{SERIES_ID}'")


if __name__ == "__main__":
    main()
