#!/usr/bin/env python3
"""Full BRONZE → SILVER → GOLD pipeline."""

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

from backend.knowledge.pipeline import KnowledgePipeline


def main() -> None:
    """Run full pipeline."""
    arg_parser = argparse.ArgumentParser(description="Run full knowledge pipeline")
    arg_parser.add_argument("--epub", required=True, help="Path to EPUB file")
    arg_parser.add_argument("--series", required=True, help="Series identifier")
    arg_parser.add_argument("--limit", type=int, help="Limit chapters to process")
    args = arg_parser.parse_args()

    # Load environment
    load_dotenv()

    # Read EPUB
    epub_path = Path(args.epub)
    if not epub_path.exists():
        print(f"Error: EPUB file not found: {epub_path}", file=sys.stderr)
        sys.exit(1)

    with open(epub_path, "rb") as f:
        epub_bytes = f.read()

    # Run pipeline
    pipeline = KnowledgePipeline(args.series)
    pipeline.run_all(epub_bytes, limit=args.limit)


if __name__ == "__main__":
    main()
