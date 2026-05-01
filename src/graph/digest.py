"""Generate a narrative story digest for a given reading window.

Filters chapter summaries from the KnowledgeBase to the requested window,
then calls the configured LLM to produce a 3-4 paragraph plain-English recap.
"""

from src.llm import LLMClient
from src.knowledge.models import ChapterSummary, KnowledgeBase


def _filter_summaries(
    kb: KnowledgeBase,
    from_book: int,
    from_chapter: int,
    to_book: int,
    to_chapter: int,
) -> list[ChapterSummary]:
    """Return chapter summaries within the requested window, sorted chronologically."""
    return sorted(
        [
            s for s in kb.summaries
            if (from_book, from_chapter) <= (s.book_index, s.chapter_index) <= (to_book, to_chapter)
        ],
        key=lambda s: (s.book_index, s.chapter_index),
    )


async def generate_digest(
    kb: KnowledgeBase,
    from_book: int,
    from_chapter: int,
    to_book: int,
    to_chapter: int,
    client: LLMClient,
    model: str,
) -> str:
    """Generate a narrative story digest for the given window.

    Args:
        kb: KnowledgeBase filtered to reading progress.
        from_book: Window start (book index, 0-based).
        from_chapter: Window start (chapter index, 0-based).
        to_book: Window end (book index, 0-based).
        to_chapter: Window end (chapter index, 0-based).
        client: LLM client (provider-agnostic).
        model: Claude model ID to use.

    Returns:
        A 3-4 paragraph narrative recap as a markdown string.
        Returns a fallback message if no summaries exist in the window.
    """
    summaries = _filter_summaries(kb, from_book, from_chapter, to_book, to_chapter)

    if not summaries:
        return "No chapter summaries are available for this window yet. Try running knowledge extraction first."

    # Build a compact chapter-by-chapter brief for Claude.
    chapter_briefs = "\n\n".join(
        f"**{s.chapter_label} (Book {s.book_index + 1})**\n{s.summary}"
        for s in summaries
    )

    prompt = (
        "You are a reading companion helping a reader recap a story before continuing.\n\n"
        "Below are chapter summaries for the period the reader wants to review:\n\n"
        f"{chapter_briefs}\n\n"
        "Write a flowing 3-4 paragraph narrative recap of what has happened. "
        "Focus on the major story beats, character arcs, and turning points — not a chapter-by-chapter list. "
        "Write in present tense, spoiler-aware only to what is shown above. "
        "Keep it engaging, like a knowledgeable friend catching you up before a big finale. "
        "Use markdown formatting (bold for character names on first mention)."
    )

    return await client.generate(
        messages=[{"role": "user", "content": prompt}],
        max_tokens=800,
    )
