#!/usr/bin/env python3
"""BRONZE stage: Extract knowledge from EPUB chapters."""

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

from src.knowledge.extractor import Extractor
from src.ingestion.epub_parser import parse_epub


def main() -> None:
    """Run extraction."""
    arg_parser = argparse.ArgumentParser(description="Extract knowledge from EPUB")
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

    # Parse chapters
    parsed_chapters = parse_epub(epub_path)
    chapters = [(ch.label, ch.text) for ch in parsed_chapters]

    # Extract knowledge
    extractor = Extractor()
    for idx, (label, text) in enumerate(chapters):
        if args.limit and idx >= args.limit:
            break
        print(f"Extracting chapter {idx}: {label}")
        extractor.extract(text, args.series, idx, label)

    print(f"Extraction complete: {len(chapters)} chapters processed")


if __name__ == "__main__":
    main()
