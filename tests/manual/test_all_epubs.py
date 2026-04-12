#!/usr/bin/env python3
"""
Manual test script for all epub files.

Usage:
    poetry run python tests/manual/test_all_epubs.py
"""
from pathlib import Path

from src.ingestion.epub_parser import parse_epub


def test_epub(epub_path: Path) -> None:
    """Test parsing a single epub file."""
    print(f"\n{'='*80}")
    print(f"📚 Parsing: {epub_path.name}")
    print(f"{'='*80}\n")

    chapters = parse_epub(epub_path)

    print(f"✅ Total chapters extracted: {len(chapters)}\n")
    print("First 15 chapters:")
    print("-" * 80)

    for ch in chapters[:15]:
        word_count = len(ch.text.split())
        print(f"{ch.index:2d}. {ch.label:40s} ({word_count:,} words)")

    if len(chapters) > 15:
        print(f"\n... and {len(chapters) - 15} more chapters")

    print("\n" + "=" * 80)
    print("Sample from first chapter (index 0):")
    print("=" * 80)
    if len(chapters) > 0:
        sample = chapters[0].text[:300]
        print(f"Label: {chapters[0].label}")
        print(f"Text preview: {sample}...\n")


def main() -> None:
    """Test all epub files in src/data/."""
    epub_dir = Path("src/data")
    epub_files = sorted(epub_dir.glob("*.epub"))

    if not epub_files:
        print("No epub files found in src/data/")
        return

    for epub_path in epub_files:
        test_epub(epub_path)


if __name__ == "__main__":
    main()
