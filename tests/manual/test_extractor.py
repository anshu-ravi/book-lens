#!/usr/bin/env python3
"""Manual tests for the extraction pipeline (extractor + merger).

Split into two sections:
  - Merger tests: pure logic, no LLM calls, always fast.
  - Live extraction test: calls Claude API, requires ANTHROPIC_API_KEY.

Usage:
    # Merger tests only (no API key needed):
    poetry run python tests/manual/test_extractor.py

    # Full suite including live extraction:
    poetry run python tests/manual/test_extractor.py --live
"""

import sys

import anthropic

from src.config import settings
from src.knowledge.extractor import _build_known_characters_context, extract_chapter
from src.knowledge.merger import merge_extraction
from src.knowledge.models import (
    ChapterExtraction,
    ChapterRef,
    ChapterSummary,
    CharacterEntity,
    CharacterEvent,
    KnowledgeBase,
    Relationship,
    RelationshipMoment,
    WorldFact,
)
from src.models import ParsedChapter

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _empty_kb() -> KnowledgeBase:
    return KnowledgeBase(series_id="test")


def _make_char(
    name: str,
    aliases: list[str] | None = None,
    book_index: int = 0,
    chapter_index: int = 0,
) -> CharacterEntity:
    return CharacterEntity(
        name=name,
        aliases=aliases or [],
        description=f"{name} description.",
        first_appearance=ChapterRef(book_index=book_index, chapter_index=chapter_index),
        key_events=[
            CharacterEvent(description=f"{name} did something.", book_index=book_index, chapter_index=chapter_index)
        ],
    )


def _make_extraction(
    characters: list[CharacterEntity] | None = None,
    relationships: list[Relationship] | None = None,
    world_facts: list[WorldFact] | None = None,
) -> ChapterExtraction:
    summary = ChapterSummary(
        book_index=0,
        chapter_index=0,
        chapter_label="Chapter 1",
        summary="A chapter summary.",
        characters_present=[c.name for c in (characters or [])],
        key_events=[],
    )
    return ChapterExtraction(
        characters=characters or [],
        relationships=relationships or [],
        world_facts=world_facts or [],
        summary=summary,
    )


# ---------------------------------------------------------------------------
# Merger tests (no LLM)
# ---------------------------------------------------------------------------


def test_merge_adds_new_character() -> None:
    """Merging an extraction with a new character adds it to the KB."""
    kb = _empty_kb()
    extraction = _make_extraction(characters=[_make_char("Darrow")])
    updated = merge_extraction(kb, extraction, book_index=0, chapter_index=0)

    assert len(updated.characters) == 1
    assert updated.characters[0].name == "Darrow"
    assert updated.alias_registry["darrow"] == "Darrow"
    print("  PASS: merge adds new character")


def test_merge_updates_existing_character_by_name() -> None:
    """Re-extracting the same character merges events, preserves first_appearance."""
    kb = _empty_kb()
    ch1_extraction = _make_extraction(characters=[_make_char("Darrow", book_index=0, chapter_index=0)])
    kb = merge_extraction(kb, ch1_extraction, book_index=0, chapter_index=0)

    # Chapter 2: Darrow appears again with a new event
    darrow_ch2 = CharacterEntity(
        name="Darrow",
        aliases=["the Reaper"],
        description="Darrow, now known as the Reaper.",
        first_appearance=ChapterRef(book_index=0, chapter_index=1),
        key_events=[
            CharacterEvent(description="Darrow wins the trial.", book_index=0, chapter_index=1)
        ],
    )
    ch2_extraction = _make_extraction(characters=[darrow_ch2])
    kb = merge_extraction(kb, ch2_extraction, book_index=0, chapter_index=1)

    assert len(kb.characters) == 1
    darrow = kb.characters[0]
    assert darrow.name == "Darrow"
    # first_appearance preserved from chapter 0
    assert darrow.first_appearance is not None
    assert darrow.first_appearance.chapter_index == 0
    # Events from both chapters present
    assert len(darrow.key_events) == 2
    # New alias added
    assert "the Reaper" in darrow.aliases
    # alias_registry updated
    assert kb.alias_registry["the reaper"] == "Darrow"
    print("  PASS: merge updates existing character by name")


def test_merge_deduplicates_by_alias() -> None:
    """A character extracted under an alias is merged into the existing canonical entry."""
    # Chapter 1: character introduced as "Darrow"
    kb = _empty_kb()
    ch1 = _make_extraction(characters=[_make_char("Darrow", aliases=["the Reaper"])])
    kb = merge_extraction(kb, ch1, book_index=0, chapter_index=0)

    # Chapter 2: same character referred to as "the Reaper" (no canonical name given)
    reaper_char = CharacterEntity(
        name="the Reaper",
        aliases=[],
        description="The fearsome Reaper of the Institute.",
        first_appearance=ChapterRef(book_index=0, chapter_index=1),
        key_events=[
            CharacterEvent(description="Reaper defeats House Minerva.", book_index=0, chapter_index=1)
        ],
    )
    ch2 = _make_extraction(characters=[reaper_char])
    kb = merge_extraction(kb, ch2, book_index=0, chapter_index=1)

    # Should still be 1 character, not 2
    assert len(kb.characters) == 1
    darrow = kb.characters[0]
    assert darrow.name == "Darrow"
    assert len(darrow.key_events) == 2
    print("  PASS: merge deduplicates character by alias")


def test_merge_two_new_characters() -> None:
    """Merging two new characters in one extraction produces two distinct entries."""
    kb = _empty_kb()
    extraction = _make_extraction(
        characters=[_make_char("Darrow"), _make_char("Sevro", aliases=["Goblin"])]
    )
    kb = merge_extraction(kb, extraction, book_index=0, chapter_index=0)

    assert len(kb.characters) == 2
    names = {c.name for c in kb.characters}
    assert names == {"Darrow", "Sevro"}
    assert kb.alias_registry["goblin"] == "Sevro"
    print("  PASS: merge adds two distinct new characters")


def test_merge_relationship_deduplication() -> None:
    """Same relationship pair extracted twice merges moments, updates description."""
    kb = _empty_kb()

    rel1 = Relationship(
        character_a="Darrow",
        character_b="Sevro",
        type="ally",
        description="Uneasy alliance at the Institute.",
        moments=[RelationshipMoment(description="First meeting.", book_index=0, chapter_index=0)],
    )
    kb = merge_extraction(kb, _make_extraction(relationships=[rel1]), book_index=0, chapter_index=0)

    rel2 = Relationship(
        character_a="Sevro",  # reversed order — should still deduplicate
        character_b="Darrow",
        type="ally",
        description="Loyal friendship forged in battle.",
        moments=[RelationshipMoment(description="Fight side by side.", book_index=0, chapter_index=5)],
    )
    kb = merge_extraction(kb, _make_extraction(relationships=[rel2]), book_index=0, chapter_index=5)

    assert len(kb.relationships) == 1
    rel = kb.relationships[0]
    assert len(rel.moments) == 2
    assert rel.description == "Loyal friendship forged in battle."
    print("  PASS: relationship deduplication (reversed pair order)")


def test_merge_world_fact_deduplication() -> None:
    """Same world fact extracted twice keeps the longer description."""
    kb = _empty_kb()

    wf1 = WorldFact(category="concept", name="Color System", description="Short.", book_index=0, chapter_index=0)
    kb = merge_extraction(kb, _make_extraction(world_facts=[wf1]), book_index=0, chapter_index=0)

    wf2 = WorldFact(
        category="Concept",  # different case — should still deduplicate
        name="color system",  # different case
        description="Society is divided into colors from Gold at the top to Red at the bottom.",
        book_index=0,
        chapter_index=2,
    )
    kb = merge_extraction(kb, _make_extraction(world_facts=[wf2]), book_index=0, chapter_index=2)

    assert len(kb.world_facts) == 1
    # Longer description kept
    assert "Gold" in kb.world_facts[0].description
    print("  PASS: world fact deduplication (case-insensitive, longer description kept)")


def test_merge_summaries_always_appended() -> None:
    """Each chapter produces a new summary entry — never deduplicated."""
    kb = _empty_kb()
    kb = merge_extraction(kb, _make_extraction(), book_index=0, chapter_index=0)
    kb = merge_extraction(kb, _make_extraction(), book_index=0, chapter_index=1)

    assert len(kb.summaries) == 2
    print("  PASS: summaries always appended")


def test_merge_tracks_extracted_chapters() -> None:
    """extracted_chapters is updated after each merge."""
    kb = _empty_kb()
    kb = merge_extraction(kb, _make_extraction(), book_index=0, chapter_index=0)
    kb = merge_extraction(kb, _make_extraction(), book_index=0, chapter_index=1)
    kb = merge_extraction(kb, _make_extraction(), book_index=1, chapter_index=0)

    assert len(kb.extracted_chapters) == 3
    assert ChapterRef(book_index=0, chapter_index=0) in kb.extracted_chapters
    assert ChapterRef(book_index=1, chapter_index=0) in kb.extracted_chapters
    print("  PASS: extracted_chapters tracked correctly")


def test_known_characters_context_empty() -> None:
    """_build_known_characters_context returns empty string when no characters."""
    kb = _empty_kb()
    result = _build_known_characters_context(kb)
    assert result == ""
    print("  PASS: known characters context is empty for empty KB")


def test_known_characters_context_with_aliases() -> None:
    """_build_known_characters_context lists canonical names and aliases."""
    kb = _empty_kb()
    extraction = _make_extraction(
        characters=[_make_char("Darrow", aliases=["the Reaper", "Darrow of Lykos"])]
    )
    kb = merge_extraction(kb, extraction, book_index=0, chapter_index=0)

    context = _build_known_characters_context(kb)
    assert "Darrow" in context
    assert "the Reaper" in context
    assert "Darrow of Lykos" in context
    print("  PASS: known characters context includes aliases")


# ---------------------------------------------------------------------------
# Live extraction tests (require ANTHROPIC_API_KEY)
# ---------------------------------------------------------------------------

_SHORT_CHAPTER = ParsedChapter(
    index=0,
    label="Chapter 1: The Mines",
    text="""
Darrow worked the drill deep into the rock, sweat dripping from his brow.
He was a Helldiver, the best in Lykos, and he knew it.

His wife Eo waited for him at the surface, her red hair bright as copper wire.
She was the only person who made the mines bearable. She sang songs that were
forbidden — old songs from before the Society — and the Golds above would have
had her flogged for it.

"You push too hard," Eo told him that evening, pressing her palm to his cheek.
"The mines don't care how fast you work."

"The clan needs the helium-3," Darrow replied. "If we don't hit quota, they'll
send the Yellows down again."

Eo pulled away. "The quota will never be met. That's the point." She looked
toward the false sun the Society projected on the cavern ceiling. "They keep
us hungry so we keep digging. That's all we are to them, Darrow. Tools."

The Society divided all humanity into colors. Golds ruled from their high
citadels. Reds like Darrow and Eo lived at the very bottom, mining the core
of Mars, never seeing the real sun. Between them were a dozen other colors —
Obsidians who served as soldiers, Grays who policed the masses, Yellows who
healed the worthy.

Darrow had never questioned it. He had always believed the lie: that their
sacrifice would one day terraform Mars and free all humanity. That was the
purpose given to the Reds.

Eo had stopped believing the lie long ago.
""",
)


def run_live_tests() -> None:
    """Run live extraction tests that call the Claude API."""
    print("\nRunning live extraction tests (requires ANTHROPIC_API_KEY)...")
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    # Test 1: Extract from a short chapter
    print("  Extracting from short chapter...")
    kb = KnowledgeBase(series_id="test-live")
    extraction = extract_chapter(
        chapter=_SHORT_CHAPTER,
        book_index=0,
        kb=kb,
        client=client,
        extraction_model=settings.extraction_model,
    )

    assert extraction.summary is not None, "Summary should not be None"
    assert len(extraction.summary.summary) > 50, "Summary should be non-trivial"
    assert len(extraction.characters) >= 2, f"Expected ≥2 characters, got {len(extraction.characters)}"

    char_names = {c.name for c in extraction.characters}
    print(f"    Characters found: {sorted(char_names)}")
    # Darrow and Eo should be found (exact names may vary)
    assert any("darrow" in n.lower() for n in char_names), "Darrow not found"
    assert any("eo" in n.lower() for n in char_names), "Eo not found"

    assert len(extraction.world_facts) >= 1, "Color System or similar should be extracted"
    world_fact_names = [wf.name for wf in extraction.world_facts]
    print(f"    World facts found: {world_fact_names}")

    print("  PASS: live extraction returns structured output")

    # Test 2: Merge then extract a second chapter with alias context
    print("  Merging extraction then verifying alias context propagation...")
    kb = merge_extraction(kb, extraction, book_index=0, chapter_index=0)

    assert len(kb.characters) >= 2
    assert len(kb.alias_registry) >= 2, "alias_registry should be populated"
    print(f"    alias_registry keys: {sorted(kb.alias_registry.keys())[:8]}")

    # Verify known_characters_context now includes characters
    from src.knowledge.extractor import _build_known_characters_context
    context = _build_known_characters_context(kb)
    assert "Darrow" in context or any(
        "darrow" in c.name.lower() for c in kb.characters
    ), "Darrow should appear in known characters context"
    print("  PASS: alias context populated after merge")

    print("\nAll live extraction tests passed.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    live = "--live" in sys.argv

    print("Running merger tests (no API calls)...")
    test_merge_adds_new_character()
    test_merge_updates_existing_character_by_name()
    test_merge_deduplicates_by_alias()
    test_merge_two_new_characters()
    test_merge_relationship_deduplication()
    test_merge_world_fact_deduplication()
    test_merge_summaries_always_appended()
    test_merge_tracks_extracted_chapters()
    test_known_characters_context_empty()
    test_known_characters_context_with_aliases()
    print("\nAll merger tests passed.")

    if live:
        run_live_tests()
    else:
        print("\n(Skipping live extraction tests. Run with --live to include them.)")


if __name__ == "__main__":
    main()
