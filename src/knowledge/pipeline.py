"""Book-level extraction orchestration.

extract_book_knowledge() processes all chapters in a book sequentially,
building up the shared KnowledgeBase chapter by chapter.

canonical_series_id: the shared series key (no user_id)
book_index: 0-based position of this book in the series (derived from series_position ordering)
"""

import asyncio
import logging

from src.llm import LLMClient
from src.knowledge.extractor import extract_chapter
from src.knowledge.merger import merge_extraction
from src.knowledge.models import KnowledgeBase
from src.knowledge.store import is_chapter_extracted, load_knowledge, save_knowledge
from src.models import ParsedChapter

logger = logging.getLogger(__name__)


async def extract_book_knowledge(
    chapters: list[ParsedChapter],
    canonical_series_id: str,
    book_index: int,
    client: LLMClient,
    extraction_model: str,
    concurrency: int = 2,
) -> KnowledgeBase:
    """Extract structured knowledge from all chapters of a book.

    Args:
        chapters: Parsed chapters from epub.
        canonical_series_id: Shared series key (no user_id).
        book_index: 0-based position of this book in the series.
        client: LLM client (provider-agnostic).
        extraction_model: Claude model ID for extraction.
        concurrency: Max parallel LLM calls.

    Returns:
        Updated KnowledgeBase.
    """
    kb = await load_knowledge(canonical_series_id)

    to_extract = [c for c in chapters if not is_chapter_extracted(kb, book_index, c.index)]
    if not to_extract:
        logger.info("[%s] Book %d — already fully extracted.", canonical_series_id, book_index)
        return kb

    total = len(chapters)
    logger.info(
        "[%s] Book %d — starting extraction for %d/%d chapters (concurrency=%d)",
        canonical_series_id, book_index, len(to_extract), total, concurrency,
    )

    semaphore = asyncio.Semaphore(concurrency)

    async def _safe_extract(chapter: ParsedChapter, current_kb: KnowledgeBase) -> KnowledgeBase:
        async with semaphore:
            return await extract_chapter(
                chapter=chapter,
                book_index=book_index,
                kb=current_kb,
                client=client,
                extraction_model=extraction_model,
            )

    seed_chapters = [c for c in to_extract if c.index < 2]
    remaining_chapters = [c for c in to_extract if c.index >= 2]

    for chapter in seed_chapters:
        logger.info("[%s] Book %d — seed chapter %d: %s", canonical_series_id, book_index, chapter.index + 1, chapter.label)
        extraction = await _safe_extract(chapter, kb)
        kb = merge_extraction(kb, extraction, book_index=book_index, chapter_index=chapter.index)
        await save_knowledge(kb, canonical_series_id)

    if remaining_chapters:
        tasks = {}
        for c in remaining_chapters:
            tasks[c.index] = asyncio.create_task(_safe_extract(c, kb))
            await asyncio.sleep(1.0)

        for idx in sorted(tasks.keys()):
            extraction = await tasks[idx]
            kb = merge_extraction(kb, extraction, book_index=book_index, chapter_index=idx)
            await save_knowledge(kb, canonical_series_id)
            logger.info("[%s] Book %d — chapter %d merged and saved", canonical_series_id, book_index, idx + 1)

    logger.info("[%s] Book %d extraction complete.", canonical_series_id, book_index)
    return kb
