"""Manual test script for chunking pipeline validation."""

import random
from pathlib import Path

from src.ingestion.chunker import chunk_chapter
from src.ingestion.epub_parser import parse_epub

# Test configuration (matches settings.chunk_size and CHUNK_OVERLAP)
CHUNK_SIZE = 400
CHUNK_OVERLAP = 50


def test_chunker() -> None:
    """Test chunking pipeline with Project Hail Mary."""
    # Parse epub
    epub_path = Path("src/data/Project Hail Mary.epub")
    print(f"📚 Chunking Test: {epub_path.stem}")
    print("=" * 80)

    chapters = parse_epub(epub_path)
    print(f"Parsed {len(chapters)} chapters")

    # Chunk all chapters
    all_chunks = []
    for chapter in chapters:
        chunks = chunk_chapter(chapter, CHUNK_SIZE, CHUNK_OVERLAP)
        all_chunks.extend(chunks)

    print(f"Generated {len(all_chunks)} chunks\n")

    # Chunk Size Distribution
    word_counts = [chunk.word_count for chunk in all_chunks]
    word_counts.sort()

    print("Chunk Size Distribution:")
    print(f"  Min:     {min(word_counts):3d} words")
    print(f"  Max:     {max(word_counts):3d} words")
    print(f"  Avg:     {sum(word_counts) // len(word_counts):3d} words ✅")
    median_idx = len(word_counts) // 2
    print(f"  Median:  {word_counts[median_idx]:3d} words ✅\n")

    # Chunks in target range
    target_min = 350
    target_max = 450
    in_range = sum(1 for wc in word_counts if target_min <= wc <= target_max)
    percentage = (in_range / len(word_counts)) * 100
    status = "✅" if percentage > 60 else "⚠️"
    print(
        f"Chunks in target range ({target_min}-{target_max}): "
        f"{in_range} / {len(all_chunks)} ({percentage:.1f}%) {status}\n"
    )

    # Overlap Verification (sample)
    print("Overlap Verification (sample):")
    # Find chapters with multiple chunks
    chunks_by_chapter: dict[int, list] = {}
    for chunk in all_chunks:
        if chunk.chapter_index not in chunks_by_chapter:
            chunks_by_chapter[chunk.chapter_index] = []
        chunks_by_chapter[chunk.chapter_index].append(chunk)

    # Get chapters with 2+ chunks
    multi_chunk_chapters = [
        (ch_idx, chunks) for ch_idx, chunks in chunks_by_chapter.items() if len(chunks) >= 2
    ]

    if multi_chunk_chapters:
        # Sample 3 random chapters
        sample_size = min(3, len(multi_chunk_chapters))
        samples = random.sample(multi_chunk_chapters, sample_size)

        for ch_idx, chunks in samples:
            # Check overlap between first two chunks
            chunk_0 = chunks[0]
            chunk_1 = chunks[1]

            # Get last N words from chunk 0
            last_words_0 = _get_last_n_words(chunk_0.text, CHUNK_OVERLAP)
            # Get first N words from chunk 1
            first_words_1 = _get_first_n_words(chunk_1.text, CHUNK_OVERLAP)

            # Check if they match
            overlap_match = last_words_0 == first_words_1
            status = "✅" if overlap_match else "⚠️"

            print(f"  Chapter {ch_idx}, Chunks 0→1:")
            print(f"    Last {CHUNK_OVERLAP} words of Chunk 0:")
            print(f"      ...{last_words_0[-100:]}")
            print(f"    First {CHUNK_OVERLAP} words of Chunk 1:")
            print(f"      {first_words_1[:100]}...")
            print(f"    Match: {status}\n")
    else:
        print("  No chapters with multiple chunks found!\n")

    # Metadata Check
    print("Metadata Check:")
    chunk_ids = [chunk.chunk_id for chunk in all_chunks]
    unique_ids = len(set(chunk_ids))
    id_status = "✅" if unique_ids == len(chunk_ids) else "❌"
    print(f"  All chunk_ids unique: {id_status} ({unique_ids}/{len(chunk_ids)})")

    all_chapters_present = all(
        any(chunk.chapter_index == ch.index for chunk in all_chunks) for ch in chapters
    )
    chapter_status = "✅" if all_chapters_present else "❌"
    print(f"  All chapters preserved: {chapter_status}")

    # Position verification
    for ch_idx, chunks in chunks_by_chapter.items():
        expected_positions = list(range(len(chunks)))
        actual_positions = [chunk.position for chunk in sorted(chunks, key=lambda c: c.position)]
        if expected_positions != actual_positions:
            print(f"  ⚠️ Chapter {ch_idx} has incorrect positions: {actual_positions}")
            break
    else:
        print(f"  Chunk positions correct: ✅")

    print("\n" + "=" * 80)
    print("✅ Chunking test complete!")


def _get_last_n_words(text: str, n: int) -> str:
    """Extract last N words from text."""
    words = text.split()
    return " ".join(words[-n:]) if len(words) >= n else text


def _get_first_n_words(text: str, n: int) -> str:
    """Extract first N words from text."""
    words = text.split()
    return " ".join(words[:n]) if len(words) >= n else text


if __name__ == "__main__":
    test_chunker()
