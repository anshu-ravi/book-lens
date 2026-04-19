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


async def extract_book_knowledge(
    chapters: list[ParsedChapter],
    series_id: str,
    book_index: int,
    user_id: str,
    client: anthropic.AsyncAnthropic,
    extraction_model: str,
) -> KnowledgeBase:
    """Extract structured knowledge from all chapters of a book."""
    kb = await load_knowledge(series_id, user_id)

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

        extraction = await extract_chapter(
            chapter=chapter,
            book_index=book_index,
            kb=kb,
            client=client,
            extraction_model=extraction_model,
        )

        kb = merge_extraction(kb, extraction, book_index=book_index, chapter_index=chapter.index)

        # Save after every chapter for crash recovery.
        await save_knowledge(kb, user_id)
        processed += 1

    logger.info(
        "[%s] Book %d extraction complete — %d processed, %d skipped",
        series_id,
        book_index,
        processed,
        skipped,
    )

    return kb
