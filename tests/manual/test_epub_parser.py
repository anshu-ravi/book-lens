#!/usr/bin/env python3
"""
Manual test script for epub parser.

Usage:
    poetry run python tests/manual/test_epub_parser.py
"""
from pathlib import Path

from src.ingestion.epub_parser import parse_epub


def test_project_hail_mary() -> None:
    """Test parsing Project Hail Mary epub."""
    epub_path = Path("src/data/Project Hail Mary.epub")

    print(f"📚 Parsing: {epub_path.name}\n")

    chapters = parse_epub(epub_path)

    print(f"✅ Total chapters extracted: {len(chapters)}\n")
    print("First 10 chapters:")
    print("-" * 60)

    for ch in chapters[:10]:
        word_count = len(ch.text.split())
        print(f"{ch.index:2d}. {ch.label:30s} ({word_count:,} words)")

    if len(chapters) > 10:
        print(f"\n... and {len(chapters) - 10} more chapters")

    print("\n" + "=" * 60)
    print("Sample text from Chapter 1:")
    print("=" * 60)
    if len(chapters) > 0:
        sample = chapters[0].text[:500]
        print(sample + "...\n")


if __name__ == "__main__":
    test_project_hail_mary()
