"""Claude prompt assembly for spoiler-safe Q&A."""

from typing import Optional

from src.models import BookStatus, Series
from src.query.classifier import QuestionType
from src.vector_store.base import SearchResult

# Re-export so callers can import QuestionType from one place.
__all__ = ["build_prompt", "build_reading_summary", "QuestionType"]

_QUESTION_TYPE_INSTRUCTIONS: dict[QuestionType, str] = {
    QuestionType.CHARACTER: (
        "Provide a comprehensive character profile, drawing on the structured knowledge."
    ),
    QuestionType.CHARACTER_ARC: (
        "Trace this character's journey chronologically from their first appearance to now."
    ),
    QuestionType.RELATIONSHIP: (
        "Describe the full history and evolution of this relationship."
    ),
    QuestionType.RECAP: (
        "Give a detailed chronological recap of the events requested."
    ),
    QuestionType.CAUSAL: (
        "Explain the causal chain. Use the structured knowledge for context "
        "and the passages for specifics."
    ),
    QuestionType.WORLD_BUILDING: (
        "Explain this aspect of the world using the structured knowledge and passages provided."
    ),
    QuestionType.DETAIL: (
        "Answer from the context passages provided."
    ),
}


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
    entity_context: Optional[str] = None,
    question_type: Optional[QuestionType] = None,
    mode: str = "default",
) -> str:
    """Assemble the full prompt to send to Claude.

    The prompt instructs Claude to answer only from the provided context,
    preventing hallucination about content the user has not yet read.

    When entity_context is provided the prompt gains a structured knowledge
    section above the RAG passages. When question_type is provided a
    type-specific answering instruction is appended.

    Args:
        question: The user's question.
        chunks: Retrieved context passages (already spoiler-filtered).
        series: The series being queried (for progress summary and name).
        entity_context: Optional structured knowledge from the KnowledgeBase.
        question_type: Optional question type for tailored instructions.

    Returns:
        Complete prompt string ready for the Claude messages API.
    """
    reading_summary = build_reading_summary(series)

    context_passages = "\n\n".join(
        f"[{i + 1}] ({chunk.chapter_label}, book {chunk.book_index + 1}):\n{chunk.text}"
        for i, chunk in enumerate(chunks)
    )

    mode_instructions = {
        "theory": "MODE INTERVENTION: The user is in 'Theory' mode. Encourage speculation, brainstorm theories with them, and act as a sounding board without confirming any future facts from the series.",
        "recap": "MODE INTERVENTION: The user is in 'Recap' mode. Focus heavily on summarizing events chronologically up to the current progress.",
        "default": ""
    }
    mode_text = mode_instructions.get(mode, "")

    citation_instruction = (
        "IMPORTANT: When stating facts, YOU MUST explicitly cite your sources using the exact chapter label. "
        "Append [Ch. X] to your sentences where X is the chapter label from the context passages, for example: [Chapter 4]."
    )

    type_instruction = (
        _QUESTION_TYPE_INSTRUCTIONS.get(question_type, _QUESTION_TYPE_INSTRUCTIONS[QuestionType.DETAIL])
        if question_type is not None
        else "Answer from the context passages provided."
    )

    if entity_context:
        passages_section = (
            f"\nSupporting passages (for specific details):\n{context_passages}\n"
            if chunks
            else ""
        )
        return (
            f'You are a spoiler-safe reading companion for the "{series.name}" series.\n'
            "Answer based ONLY on the knowledge and passages below. Never use outside knowledge.\n"
            "If the answer cannot be found in the provided content, say: "
            '"I don\'t have enough information from your reading so far to answer that."\n\n'
            f"{mode_text}\n{citation_instruction}\n\n"
            f"Reading progress:\n{reading_summary}\n\n"
            f"Structured knowledge about the series so far:\n{entity_context}\n"
            f"{passages_section}\n"
            f"{type_instruction}\n\n"
            f"Question: {question}"
        )

    return (
        f'You are a spoiler-safe reading companion for the "{series.name}" series.\n\n'
        "Your job is to answer questions based ONLY on the context passages provided below. "
        "Do not use any knowledge beyond what is in these passages. "
        'If the answer cannot be found in the passages, say: '
        '"I don\'t have enough information from your reading so far to answer that."\n\n'
        f"{mode_text}\n{citation_instruction}\n\n"
        f"Reading progress:\n{reading_summary}\n\n"
        f"Context passages:\n{context_passages}\n\n"
        f"Question: {question}"
    )
