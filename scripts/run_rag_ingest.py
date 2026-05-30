#!/usr/bin/env python3
"""Ingest an EPUB into the RAG pipeline (hierarchical nodes → Supabase pgvector).

Usage:
    poetry run python scripts/run_rag_ingest.py \\
        --epub local/uploads/red-rising/book_0.epub \\
        --series the-red-rising-saga \\
        --book-id 7af3a69a-1d3a-4899-881d-a33eceaa69a9 \\
        --user-id d5203e02-a3d8-4b9b-ba4e-1b08c8ebdc46 \\
        --title "Red Rising"
"""

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.rag import ingest_book
from backend.supabase_client import get_supabase_client


def main() -> None:
    """Run RAG ingestion for a single book."""
    parser = argparse.ArgumentParser(description="Ingest an EPUB into the RAG vector index")
    parser.add_argument("--epub", required=True, help="Path to the .epub file")
    parser.add_argument("--series", required=True, help="Series slug (e.g. 'the-red-rising-saga')")
    parser.add_argument("--book-id", required=True, help="Book UUID from the Supabase books table")
    parser.add_argument("--user-id", required=True, help="Supabase user UUID")
    parser.add_argument("--title", default="", help="Book title for embedding context")
    parser.add_argument("--limit", type=int, help="Cap at N chapters (useful for testing)")
    args = parser.parse_args()

    epub_path = Path(args.epub)
    if not epub_path.exists():
        print(f"Error: EPUB not found: {epub_path}", file=sys.stderr)
        sys.exit(1)

    anthropic_api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not anthropic_api_key:
        print("Warning: ANTHROPIC_API_KEY not set — will fail if no gold-layer summaries exist")

    supabase = get_supabase_client()

    print(f"Ingesting: {epub_path}")
    counts = ingest_book(
        epub_path=epub_path,
        series_id=args.series,
        book_id=args.book_id,
        user_id=args.user_id,
        supabase=supabase,
        anthropic_api_key=anthropic_api_key,
        book_title=args.title,
        chapters_limit=args.limit,
    )
    print(f"Done — {counts['new_nodes']} new nodes, {counts['new_embeddings']} new embeddings written.")


if __name__ == "__main__":
    main()
