"""Book-level extraction orchestration.

extract_book_knowledge() processes all chapters in a book sequentially,
building up the KnowledgeBase chapter by chapter. Sequential processing is
intentional: each chapter feeds its extracted aliases forward into the next
chapter's prompt, which is how coreference resolution works without an
NLP pipeline.

Crash recovery: the KB is saved after every chapter, so a restart will
skip already-extracted chapters via is_chapter_extracted().
"""

import asyncio
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
    concurrency: int = 2,
) -> KnowledgeBase:
    """Extract structured knowledge from all chapters of a book using parallel processing."""
    kb = await load_knowledge(series_id, user_id)

    # 1. Filter chapters that need extraction
    to_extract = [c for c in chapters if not is_chapter_extracted(kb, book_index, c.index)]
    if not to_extract:
        logger.info("[%s] Book %d — already fully extracted.", series_id, book_index)
        return kb

    total = len(chapters)
    logger.info(
        "[%s] Book %d — starting parallel extraction for %d/%d chapters (concurrency=%d)",
        series_id,
        book_index,
        len(to_extract),
        total,
        concurrency,
    )

    # Use a semaphore to limit parallel LLM calls
    semaphore = asyncio.Semaphore(concurrency)

    async def _safe_extract(chapter: ParsedChapter, current_kb: KnowledgeBase):
        async with semaphore:
            return await extract_chapter(
                chapter=chapter,
                book_index=book_index,
                kb=current_kb,
                client=client,
                extraction_model=extraction_model,
            )

    # For the first few chapters (or if the KB is empty), we may want to be sequential 
    # to establish core characters. We'll pick the first 2 chapters if they aren't done.
    seed_chapters = [c for c in to_extract if c.index < 2]
    remaining_chapters = [c for c in to_extract if c.index >= 2]

    # Phase 1: Seed chapters (Sequential)
    for chapter in seed_chapters:
        logger.info("[%s] Book %d — extracting seed chapter %d: %s", series_id, book_index, chapter.index + 1, chapter.label)
        extraction = await _safe_extract(chapter, kb)
        kb = merge_extraction(kb, extraction, book_index=book_index, chapter_index=chapter.index)
        await save_knowledge(kb, user_id)

    # Phase 2: Parallel extraction
    if remaining_chapters:
        logger.info("[%s] Book %d — launching parallel extraction for remaining %d chapters (concurrency=%d)", series_id, book_index, len(remaining_chapters), concurrency)
        
        # We pass the 'current' KB (after seed chapters) to ALL remaining chapters.
        # This provides the canonical names for existing characters.
        tasks = {}
        for c in remaining_chapters:
            tasks[c.index] = asyncio.create_task(_safe_extract(c, kb))
            # Small staggered delay to prevent hitting RPM/TPM limits all at once
            await asyncio.sleep(1.0)

        
        # Merge results sequentially as they finish to ensure alias_registry grows correctly
        for idx in sorted(tasks.keys()):
            logger.info("[%s] Book %d — awaiting extraction/merge for chapter %d", series_id, book_index, idx + 1)
            extraction = await tasks[idx]
            kb = merge_extraction(kb, extraction, book_index=book_index, chapter_index=idx)
            
            # Save after every merge for crash recovery.
            await save_knowledge(kb, user_id)
            logger.info("[%s] Book %d — chapter %d merged and saved", series_id, book_index, idx + 1)

    logger.info("[%s] Book %d extraction complete.", series_id, book_index)
    return kb

