"""Book-level extraction orchestration.

extract_book_knowledge() processes all chapters in a book sequentially,
building up the KnowledgeBase chapter by chapter. Sequential processing is
intentional: each chapter feeds its extracted aliases forward into the next
chapter's prompt, which is how coreference resolution works without an
NLP pipeline.

Crash recovery: the KB is saved after every chapter, so a restart will
skip already-extracted chapters via is_chapter_extracted().
"""

import logging

import anthropic

from src.knowledge.extractor import extract_chapter
from src.knowledge.merger import merge_extraction
from src.knowledge.models import KnowledgeBase
from src.knowledge.store import is_chapter_extracted, load_knowledge, save_knowledge
from src.models import ParsedChapter

logger = logging.getLogger(__name__)


def extract_book_knowledge(
    chapters: list[ParsedChapter],
    series_id: str,
    book_index: int,
    client: anthropic.Anthropic,
    extraction_model: str,
) -> KnowledgeBase:
    """Extract structured knowledge from all chapters of a book.

    Processes chapters in order. Each chapter's extracted aliases are merged
    into the KB before the next chapter is processed, so later chapters
    benefit from knowing all previously established canonical names.

    Chapters already present in extracted_chapters are skipped, making
    this function safe to call multiple times (idempotent).

    Args:
        chapters: Parsed chapters from parse_epub(), in reading order.
        series_id: Series this book belongs to.
        book_index: 0-based book index within the series.
        client: Anthropic client for LLM calls.
        extraction_model: Model ID to use for extraction.

    Returns:
        Updated KnowledgeBase after processing all chapters.
    """
    kb = load_knowledge(series_id)

    total = len(chapters)
    skipped = 0
    processed = 0

    for chapter in chapters:
        if is_chapter_extracted(kb, book_index, chapter.index):
            skipped += 1
            continue

        logger.info(
            "[%s] Book %d — extracting %d/%d: %s",
            series_id,
            book_index,
            chapter.index + 1,
            total,
            chapter.label,
        )

        extraction = extract_chapter(
            chapter=chapter,
            book_index=book_index,
            kb=kb,
            client=client,
            extraction_model=extraction_model,
        )

        kb = merge_extraction(kb, extraction, book_index=book_index, chapter_index=chapter.index)

        # Save after every chapter for crash recovery.
        save_knowledge(kb)
        processed += 1

    logger.info(
        "[%s] Book %d extraction complete — %d processed, %d skipped",
        series_id,
        book_index,
        processed,
        skipped,
    )

    return kb
