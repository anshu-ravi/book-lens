"""Semantic chunking for parsed chapters."""

from src.models import ChunkRecord, ParsedChapter


def chunk_chapter(
    chapter: ParsedChapter, chunk_size: int = 400, overlap: int = 50
) -> list[ChunkRecord]:
    """
    Split a chapter into overlapping chunks of approximately chunk_size words.

    Args:
        chapter: Parsed chapter from epub_parser
        chunk_size: Target words per chunk (default 400)
        overlap: Words to overlap between chunks (default 50)

    Returns:
        List of ChunkRecords in reading order
    """
    paragraphs = _split_into_paragraphs(chapter.text)

    if not paragraphs:
        return []

    chunks: list[ChunkRecord] = []
    current_chunk_text = ""
    prev_chunk_text = ""
    chunk_position = 0

    for paragraph in paragraphs:
        # Try adding this paragraph to current chunk
        if current_chunk_text:
            temp_text = current_chunk_text + "\n\n" + paragraph
        else:
            temp_text = paragraph

        # If adding this paragraph keeps us under the limit, add it
        if _count_words(temp_text) <= chunk_size:
            current_chunk_text = temp_text
        else:
            # Current chunk is full, finalize it
            if current_chunk_text:
                # Add overlap from previous chunk if exists
                if prev_chunk_text and overlap > 0:
                    overlap_text = _get_last_n_words(prev_chunk_text, overlap)
                    final_text = overlap_text + "\n\n" + current_chunk_text
                else:
                    final_text = current_chunk_text

                chunk = ChunkRecord(
                    chunk_id=_create_chunk_id(chapter.index, chunk_position),
                    chapter_index=chapter.index,
                    chapter_label=chapter.label,
                    text=final_text,
                    word_count=_count_words(final_text),
                    position=chunk_position,
                )
                chunks.append(chunk)

                # Move to next chunk
                prev_chunk_text = current_chunk_text
                chunk_position += 1

            # Start new chunk with current paragraph
            current_chunk_text = paragraph

    # Finalize last chunk if any text remains
    if current_chunk_text:
        if prev_chunk_text and overlap > 0:
            overlap_text = _get_last_n_words(prev_chunk_text, overlap)
            final_text = overlap_text + "\n\n" + current_chunk_text
        else:
            final_text = current_chunk_text

        chunk = ChunkRecord(
            chunk_id=_create_chunk_id(chapter.index, chunk_position),
            chapter_index=chapter.index,
            chapter_label=chapter.label,
            text=final_text,
            word_count=_count_words(final_text),
            position=chunk_position,
        )
        chunks.append(chunk)

    return chunks


def _split_into_paragraphs(text: str) -> list[str]:
    """
    Split text on paragraph boundaries (\\n\\n).

    Args:
        text: Full chapter text

    Returns:
        List of paragraphs (empty paragraphs filtered out)
    """
    paragraphs = text.split("\n\n")
    # Filter out empty paragraphs
    return [p.strip() for p in paragraphs if p.strip()]


def _count_words(text: str) -> int:
    """
    Count words in text (simple split on whitespace).

    Args:
        text: Text to count words in

    Returns:
        Number of words
    """
    return len(text.split())


def _get_last_n_words(text: str, n: int) -> str:
    """
    Extract last N words from text for overlap.

    Args:
        text: Source text
        n: Number of words to extract

    Returns:
        Last N words (or entire text if fewer than N words)
    """
    words = text.split()
    return " ".join(words[-n:]) if len(words) >= n else text


def _create_chunk_id(chapter_index: int, chunk_position: int) -> str:
    """
    Generate unique chunk ID (e.g., 'chapter_3_chunk_2').

    Args:
        chapter_index: Chapter index (0-based)
        chunk_position: Position of chunk within chapter (0-based)

    Returns:
        Unique chunk ID string
    """
    return f"chapter_{chapter_index}_chunk_{chunk_position}"
