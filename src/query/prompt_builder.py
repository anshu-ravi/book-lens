"""Claude prompt assembly for spoiler-safe Q&A."""

from src.models import BookStatus, Series
from src.vector_store.base import SearchResult


def build_reading_summary(series: Series) -> str:
    """Summarise the user's reading progress for the series.

    Args:
        series: The series with book statuses and chapter progress.

    Returns:
        Human-readable progress string, e.g.:
        "Red Rising (completed), Golden Son (reading — up to Chapter 5)"
    """
    parts: list[str] = []
    for book in sorted(series.books, key=lambda b: b.index):
        if book.status == BookStatus.COMPLETED:
            parts.append(f"{book.title} (completed)")
        elif book.status == BookStatus.READING:
            if book.current_chapter_index is not None and book.chapters:
                # Find the label for the current chapter
                label = next(
                    (c.label for c in book.chapters if c.index == book.current_chapter_index),
                    f"chapter {book.current_chapter_index}",
                )
                parts.append(f"{book.title} (reading — up to {label})")
            else:
                parts.append(f"{book.title} (reading)")
        # NOT_STARTED books are omitted — user hasn't started them
    return ", ".join(parts) if parts else "No books started yet."


def build_prompt(
    question: str,
    chunks: list[SearchResult],
    series: Series,
) -> str:
    """Assemble the full prompt to send to Claude.

    The prompt instructs Claude to answer only from the provided context,
    preventing hallucination about content the user has not yet read.

    Args:
        question: The user's question.
        chunks: Retrieved context passages (already spoiler-filtered).
        series: The series being queried (for progress summary and name).

    Returns:
        Complete prompt string ready for the Claude messages API.
    """
    reading_summary = build_reading_summary(series)

    context_passages = "\n\n".join(
        f"[{i + 1}] ({chunk.chapter_label}, book {chunk.book_index + 1}):\n{chunk.text}"
        for i, chunk in enumerate(chunks)
    )

    return f"""You are a spoiler-safe reading companion for the "{series.name}" series.

Your job is to answer questions based ONLY on the context passages provided below. \
Do not use any knowledge beyond what is in these passages. \
If the answer cannot be found in the passages, say: \
"I don't have enough information from your reading so far to answer that."

Reading progress:
{reading_summary}

Context passages:
{context_passages}

Question: {question}"""
