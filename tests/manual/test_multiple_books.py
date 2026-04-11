"""Test chunking across multiple books to verify robustness."""

from pathlib import Path

from src.ingestion.chunker import chunk_chapter
from src.ingestion.epub_parser import parse_epub

# Test configuration
CHUNK_SIZE = 400
CHUNK_OVERLAP = 50

books = [
    "Project Hail Mary.epub",
    "Red rising _ Book I of The Red Rising Trilogy.epub",
    "Golden Son_ Book 2 of the Red Rising Saga -- Pierce Brown.epub",
]

print("📚 Multi-Book Chunking Test")
print("=" * 80)

for book_filename in books:
    epub_path = Path(f"src/data/{book_filename}")
    if not epub_path.exists():
        print(f"⚠️  Skipping {book_filename} (not found)")
        continue

    try:
        chapters = parse_epub(epub_path)

        # Chunk all chapters
        all_chunks = []
        for chapter in chapters:
            chunks = chunk_chapter(chapter, CHUNK_SIZE, CHUNK_OVERLAP)
            all_chunks.extend(chunks)

        # Calculate stats
        word_counts = [chunk.word_count for chunk in all_chunks]
        word_counts.sort()
        avg = sum(word_counts) // len(word_counts) if word_counts else 0
        median = word_counts[len(word_counts) // 2] if word_counts else 0

        # Chunks in target range
        in_range = sum(1 for wc in word_counts if 350 <= wc <= 450)
        percentage = (in_range / len(word_counts) * 100) if word_counts else 0

        # Display results
        print(f"\n{epub_path.stem[:50]}")
        print(f"  Chapters: {len(chapters):3d}  |  Chunks: {len(all_chunks):4d}")
        print(f"  Avg: {avg:3d} words  |  Median: {median:3d} words")
        print(
            f"  In range (350-450): {in_range}/{len(all_chunks)} "
            f"({percentage:.1f}%) {'✅' if percentage > 80 else '⚠️'}"
        )

    except Exception as e:
        print(f"❌ Error processing {book_filename}: {e}")

print("\n" + "=" * 80)
print("✅ Multi-book test complete!")
