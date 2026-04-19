#!/usr/bin/env python3
"""Manual tests for the extraction pipeline (pipeline.py + main.py endpoints).

Split into two sections:
  - Pipeline unit tests: mock the extractor, test orchestration logic only.
  - Live tests: call Claude API against a real epub. Requires ANTHROPIC_API_KEY.

Usage:
    # Unit tests only (no API calls):
    poetry run python tests/manual/test_extraction_pipeline.py

    # Full suite including live extraction:
    poetry run python tests/manual/test_extraction_pipeline.py --live
"""

import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import anthropic

from src.config import settings
from src.knowledge.models import (
    ChapterExtraction,
    ChapterRef,
    ChapterSummary,
    CharacterEntity,
    CharacterEvent,
    KnowledgeBase,
)
from src.knowledge.pipeline import extract_book_knowledge
from src.models import ParsedChapter

_EPUB_PATH = Path("src/data/Red rising _ Book I of The Red Rising Trilogy.epub")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_chapter(index: int) -> ParsedChapter:
    return ParsedChapter(index=index, label=f"Chapter {index + 1}", text=f"Text of chapter {index}.")


def _make_empty_extraction(chapter_index: int) -> ChapterExtraction:
    return ChapterExtraction(
        characters=[
            CharacterEntity(
                name=f"Character{chapter_index}",
                aliases=[],
                description="A character.",
                first_appearance=ChapterRef(book_index=0, chapter_index=chapter_index),
                key_events=[
                    CharacterEvent(
                        description="Did something.",
                        book_index=0,
                        chapter_index=chapter_index,
                    )
                ],
            )
        ],
        relationships=[],
        world_facts=[],
        summary=ChapterSummary(
            book_index=0,
            chapter_index=chapter_index,
            chapter_label=f"Chapter {chapter_index + 1}",
            summary="Summary.",
            characters_present=[f"Character{chapter_index}"],
            key_events=["Did something."],
        ),
    )


# ---------------------------------------------------------------------------
# Pipeline unit tests (no LLM)
# ---------------------------------------------------------------------------


def test_pipeline_processes_all_chapters() -> None:
    """extract_book_knowledge calls extract_chapter for each chapter."""
    chapters = [_make_chapter(i) for i in range(3)]
    call_count = 0

    def fake_extract(chapter, book_index, kb, client, extraction_model):  # type: ignore[no-untyped-def]
        nonlocal call_count
        call_count += 1
        return _make_empty_extraction(chapter.index)

    empty_kb = KnowledgeBase(series_id="test")

    with patch("src.knowledge.pipeline.load_knowledge", return_value=empty_kb):
        with patch("src.knowledge.pipeline.save_knowledge"):
            with patch("src.knowledge.pipeline.extract_chapter", side_effect=fake_extract):
                kb = extract_book_knowledge(
                    chapters=chapters,
                    series_id="test",
                    book_index=0,
                    client=MagicMock(),
                    extraction_model="claude-haiku-4-5-20251001",
                )

    assert call_count == 3, f"Expected 3 extract calls, got {call_count}"
    assert len(kb.summaries) == 3
    print("  PASS: pipeline processes all chapters")


def test_pipeline_skips_already_extracted() -> None:
    """extract_book_knowledge skips chapters already in extracted_chapters."""
    chapters = [_make_chapter(i) for i in range(3)]
    call_count = 0

    def fake_extract(chapter, book_index, kb, client, extraction_model):  # type: ignore[no-untyped-def]
        nonlocal call_count
        call_count += 1
        return _make_empty_extraction(chapter.index)

    # Pre-populate KB with chapter 0 already extracted
    pre_kb = KnowledgeBase(
        series_id="test",
        extracted_chapters=[ChapterRef(book_index=0, chapter_index=0)],
        summaries=[
            ChapterSummary(
                book_index=0,
                chapter_index=0,
                chapter_label="Chapter 1",
                summary="Already done.",
                characters_present=[],
                key_events=[],
            )
        ],
    )

    with patch("src.knowledge.pipeline.load_knowledge", return_value=pre_kb):
        with patch("src.knowledge.pipeline.save_knowledge"):
            with patch("src.knowledge.pipeline.extract_chapter", side_effect=fake_extract):
                kb = extract_book_knowledge(
                    chapters=chapters,
                    series_id="test",
                    book_index=0,
                    client=MagicMock(),
                    extraction_model="claude-haiku-4-5-20251001",
                )

    # Only chapters 1 and 2 extracted (chapter 0 was pre-populated)
    assert call_count == 2, f"Expected 2 extract calls (skipping ch0), got {call_count}"
    assert len(kb.summaries) == 3  # 1 pre-existing + 2 new
    print("  PASS: pipeline skips already-extracted chapters")


def test_pipeline_saves_after_each_chapter() -> None:
    """extract_book_knowledge saves the KB after every chapter (crash recovery)."""
    chapters = [_make_chapter(i) for i in range(3)]

    def fake_extract(chapter, book_index, kb, client, extraction_model):  # type: ignore[no-untyped-def]
        return _make_empty_extraction(chapter.index)

    empty_kb = KnowledgeBase(series_id="test")

    with patch("src.knowledge.pipeline.load_knowledge", return_value=empty_kb):
        with patch("src.knowledge.pipeline.save_knowledge") as mock_save:
            with patch("src.knowledge.pipeline.extract_chapter", side_effect=fake_extract):
                extract_book_knowledge(
                    chapters=chapters,
                    series_id="test",
                    book_index=0,
                    client=MagicMock(),
                    extraction_model="claude-haiku-4-5-20251001",
                )

    assert mock_save.call_count == 3, f"Expected 3 save calls, got {mock_save.call_count}"
    print("  PASS: pipeline saves after each chapter")


# ---------------------------------------------------------------------------
# Live extraction tests (require ANTHROPIC_API_KEY and epub file)
# ---------------------------------------------------------------------------


def run_live_tests() -> None:
    """Run live tests against a real epub file and Claude API."""
    if not _EPUB_PATH.exists():
        print(f"\n  SKIP: epub not found at {_EPUB_PATH}")
        return

    print("\nRunning live extraction tests...")
    from src.ingestion.epub_parser import parse_epub

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    test_series_id = "test-pipeline-live"

    with tempfile.TemporaryDirectory() as tmp:
        with patch("src.knowledge.store.settings") as mock_store_settings:
            mock_store_settings.knowledge_dir = tmp

            # Parse only the first 3 chapters to keep test fast
            print("  Parsing epub (first 3 chapters)...")
            all_chapters = parse_epub(_EPUB_PATH)
            chapters = all_chapters[:3]
            print(f"  Testing with chapters: {[c.label for c in chapters]}")

            # Test 1: First extraction
            print("  Running first extraction...")
            kb = extract_book_knowledge(
                chapters=chapters,
                series_id=test_series_id,
                book_index=0,
                client=client,
                extraction_model=settings.extraction_model,
            )

            assert len(kb.summaries) == 3, f"Expected 3 summaries, got {len(kb.summaries)}"
            assert len(kb.characters) >= 1, "Should have extracted at least 1 character"
            assert len(kb.alias_registry) >= 1, "alias_registry should be populated"
            assert len(kb.extracted_chapters) == 3

            print(f"  Characters: {[c.name for c in kb.characters]}")
            print(f"  World facts: {[wf.name for wf in kb.world_facts]}")
            print(f"  alias_registry: {dict(list(kb.alias_registry.items())[:5])}")
            print("  PASS: first extraction produces structured KB")

            # Test 2: Re-run is idempotent (skips all chapters)
            print("  Re-running extraction (should skip all chapters)...")
            with patch("src.knowledge.pipeline.extract_chapter") as mock_extract:
                extract_book_knowledge(
                    chapters=chapters,
                    series_id=test_series_id,
                    book_index=0,
                    client=client,
                    extraction_model=settings.extraction_model,
                )
                assert mock_extract.call_count == 0, (
                    f"Expected 0 extract calls (all skipped), got {mock_extract.call_count}"
                )
            print("  PASS: re-extraction skips already-processed chapters")

    print("\nAll live extraction tests passed.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    live = "--live" in sys.argv

    print("Running pipeline unit tests (no API calls)...")
    test_pipeline_processes_all_chapters()
    test_pipeline_skips_already_extracted()
    test_pipeline_saves_after_each_chapter()
    print("\nAll pipeline unit tests passed.")

    if live:
        run_live_tests()
    else:
        print("\n(Skipping live tests. Run with --live to include them.)")


if __name__ == "__main__":
    main()
