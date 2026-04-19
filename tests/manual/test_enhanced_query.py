#!/usr/bin/env python3
"""Manual tests for Phase 4: enhanced query engine.

Tests cover:
  - QuestionType classification (heuristics, entity mention extraction)
  - Context builder output per question type
  - build_prompt() backwards compatibility and enriched form

Usage:
    poetry run python tests/manual/test_enhanced_query.py
"""

# ---------------------------------------------------------------------------
# Part 1: Classifier — QuestionType + extract_entity_mentions
# ---------------------------------------------------------------------------

from src.query.classifier import QuestionType, classify_question, extract_entity_mentions

_ALIAS_REGISTRY = {
    "darrow": "Darrow",
    "the reaper": "Darrow",
    "darrow of lykos": "Darrow",
    "sevro": "Sevro",
    "goblin": "Sevro",
    "cassius": "Cassius",
    "mustang": "Mustang",
    "virginia au augustus": "Mustang",
}


def test_classify_character_questions() -> None:
    """'Who is X?' and 'Tell me about X' → CHARACTER."""
    assert classify_question("Who is Darrow?") == QuestionType.CHARACTER
    assert classify_question("who is sevro") == QuestionType.CHARACTER
    assert classify_question("Tell me about Mustang") == QuestionType.CHARACTER
    assert classify_question("Describe Cassius") == QuestionType.CHARACTER
    print("  PASS: classify CHARACTER questions")


def test_classify_character_arc_questions() -> None:
    """Questions about a character's journey/arc → CHARACTER_ARC."""
    assert classify_question("What is Darrow's journey so far?") == QuestionType.CHARACTER_ARC
    assert classify_question("Trace Darrow's arc through the series") == QuestionType.CHARACTER_ARC
    assert classify_question("How has Sevro changed over the books?") == QuestionType.CHARACTER_ARC
    assert classify_question("What is Darrow's character development?") == QuestionType.CHARACTER_ARC
    print("  PASS: classify CHARACTER_ARC questions")


def test_classify_relationship_questions() -> None:
    """Questions about relationships/history between characters → RELATIONSHIP."""
    assert classify_question("What's the relationship between Darrow and Cassius?") == QuestionType.RELATIONSHIP
    assert classify_question("Tell me the history between Sevro and Darrow") == QuestionType.RELATIONSHIP
    assert classify_question("What's between Darrow and Mustang?") == QuestionType.RELATIONSHIP
    print("  PASS: classify RELATIONSHIP questions")


def test_classify_recap_questions() -> None:
    """'What happened in...', 'Recap...', 'summarize...' → RECAP."""
    assert classify_question("What happened in Book 1?") == QuestionType.RECAP
    assert classify_question("Recap chapters 10-15") == QuestionType.RECAP
    assert classify_question("Summarize the first book") == QuestionType.RECAP
    assert classify_question("What happened so far?") == QuestionType.RECAP
    print("  PASS: classify RECAP questions")


def test_classify_world_building_questions() -> None:
    """'How does X work?', questions about factions/systems → WORLD_BUILDING."""
    assert classify_question("How does the color system work?") == QuestionType.WORLD_BUILDING
    assert classify_question("What is the Society?") == QuestionType.WORLD_BUILDING
    assert classify_question("Explain the Gold hierarchy") == QuestionType.WORLD_BUILDING
    print("  PASS: classify WORLD_BUILDING questions")


def test_classify_causal_questions() -> None:
    """'Why did X?', 'What caused...?' → CAUSAL."""
    assert classify_question("Why did Darrow betray Cassius?") == QuestionType.CAUSAL
    assert classify_question("Why does Sevro act the way he does?") == QuestionType.CAUSAL
    assert classify_question("What caused the war?") == QuestionType.CAUSAL
    print("  PASS: classify CAUSAL questions")


def test_classify_detail_fallback() -> None:
    """Short or ambiguous questions fall back to DETAIL."""
    assert classify_question("What chapter?") == QuestionType.DETAIL
    assert classify_question("When?") == QuestionType.DETAIL
    print("  PASS: classify DETAIL fallback")


def test_extract_entity_mentions_direct_name() -> None:
    """Direct canonical name in question → returns canonical name."""
    result = extract_entity_mentions("Who is Darrow?", _ALIAS_REGISTRY)
    assert result == ["Darrow"]
    print("  PASS: extract_entity_mentions direct name")


def test_extract_entity_mentions_alias() -> None:
    """Alias in question → returns canonical name."""
    result = extract_entity_mentions("What about the Goblin?", _ALIAS_REGISTRY)
    assert result == ["Sevro"]
    print("  PASS: extract_entity_mentions alias resolution")


def test_extract_entity_mentions_longest_match_first() -> None:
    """Longer alias wins over shorter alias for the same span."""
    result = extract_entity_mentions("darrow of lykos arrived", _ALIAS_REGISTRY)
    # "darrow of lykos" matches before "darrow" alone
    assert result == ["Darrow"]
    print("  PASS: extract_entity_mentions longest match")


def test_extract_entity_mentions_multiple_entities() -> None:
    """Multiple entities in one question → all returned, deduplicated."""
    result = extract_entity_mentions(
        "What is the relationship between Darrow and Sevro?", _ALIAS_REGISTRY
    )
    assert set(result) == {"Darrow", "Sevro"}
    print("  PASS: extract_entity_mentions multiple entities")


def test_extract_entity_mentions_no_match() -> None:
    """Question with no known entities → empty list."""
    result = extract_entity_mentions("What is the color system?", _ALIAS_REGISTRY)
    assert result == []
    print("  PASS: extract_entity_mentions no match")


def test_extract_entity_mentions_deduplicates() -> None:
    """Same entity mentioned twice (different aliases) → returned once."""
    result = extract_entity_mentions("the reaper is Darrow", _ALIAS_REGISTRY)
    assert result == ["Darrow"]
    print("  PASS: extract_entity_mentions deduplication")


# ---------------------------------------------------------------------------
# Part 2: Context builder
# ---------------------------------------------------------------------------

from src.knowledge.models import (
    ChapterRef,
    ChapterSummary,
    CharacterEntity,
    CharacterEvent,
    KnowledgeBase,
    Relationship,
    RelationshipMoment,
    WorldFact,
)
from src.query.context_builder import build_entity_context


def _make_test_kb() -> KnowledgeBase:
    """Build a representative KB for context builder tests."""
    darrow = CharacterEntity(
        name="Darrow",
        aliases=["the reaper", "darrow of lykos"],
        faction="Red",
        role="protagonist",
        description="A Red miner who infiltrates the Golds to destroy the Society.",
        first_appearance=ChapterRef(book_index=0, chapter_index=0),
        key_events=[
            CharacterEvent(description="Eo is executed", book_index=0, chapter_index=2),
            CharacterEvent(description="Carved into a Gold", book_index=0, chapter_index=5),
            CharacterEvent(description="Wins the Institute", book_index=0, chapter_index=15),
        ],
    )
    sevro = CharacterEntity(
        name="Sevro",
        aliases=["goblin"],
        faction="Gold",
        role="ally",
        description="A fierce and unpredictable fighter, Darrow's closest ally.",
        first_appearance=ChapterRef(book_index=0, chapter_index=8),
        key_events=[
            CharacterEvent(description="Joins Darrow's house", book_index=0, chapter_index=8),
        ],
    )
    rel = Relationship(
        character_a="Darrow",
        character_b="Sevro",
        type="ally",
        description="Darrow's most loyal and unpredictable ally.",
        moments=[
            RelationshipMoment(
                description="First meeting at the Institute", book_index=0, chapter_index=8
            ),
            RelationshipMoment(
                description="Sevro pledges loyalty to Darrow", book_index=0, chapter_index=10
            ),
        ],
    )
    world_color = WorldFact(
        category="concept",
        name="Color System",
        description="Society is divided by birth into colors: Gold at the top, Red at the bottom.",
        book_index=0,
        chapter_index=0,
    )
    world_gold = WorldFact(
        category="faction",
        name="Gold",
        description="The ruling class of the Society.",
        book_index=0,
        chapter_index=0,
    )
    summaries = [
        ChapterSummary(
            book_index=0,
            chapter_index=0,
            chapter_label="Chapter 1",
            summary="Darrow works as a helldiver in the mines of Mars.",
            characters_present=["Darrow"],
            key_events=["Darrow wins the song competition"],
        ),
        ChapterSummary(
            book_index=0,
            chapter_index=8,
            chapter_label="Chapter 9",
            summary="Darrow meets Sevro at the Institute.",
            characters_present=["Darrow", "Sevro"],
            key_events=["Sevro joins Darrow's house"],
        ),
    ]
    return KnowledgeBase(
        series_id="test",
        characters=[darrow, sevro],
        relationships=[rel],
        world_facts=[world_color, world_gold],
        summaries=summaries,
        alias_registry={
            "the reaper": "Darrow",
            "darrow of lykos": "Darrow",
            "goblin": "Sevro",
        },
        extracted_chapters=[],
    )


def test_character_context_includes_profile() -> None:
    """CHARACTER type returns the full profile of the mentioned character."""
    kb = _make_test_kb()
    context = build_entity_context(QuestionType.CHARACTER, ["Darrow"], kb, max_tokens=3000)
    assert "Darrow" in context
    assert "Red" in context  # faction
    assert "protagonist" in context  # role
    assert "infiltrates" in context  # description
    print("  PASS: CHARACTER context includes character profile")


def test_character_arc_context_includes_events() -> None:
    """CHARACTER_ARC type includes key_events for the character."""
    kb = _make_test_kb()
    context = build_entity_context(QuestionType.CHARACTER_ARC, ["Darrow"], kb, max_tokens=3000)
    assert "Eo is executed" in context
    assert "Carved into a Gold" in context
    assert "Wins the Institute" in context
    print("  PASS: CHARACTER_ARC context includes key events")


def test_relationship_context_includes_moments() -> None:
    """RELATIONSHIP type includes the relationship entry and its moments."""
    kb = _make_test_kb()
    context = build_entity_context(
        QuestionType.RELATIONSHIP, ["Darrow", "Sevro"], kb, max_tokens=3000
    )
    assert "Darrow" in context
    assert "Sevro" in context
    assert "ally" in context
    assert "pledges loyalty" in context
    print("  PASS: RELATIONSHIP context includes relationship moments")


def test_recap_context_includes_summaries() -> None:
    """RECAP type returns chapter summaries."""
    kb = _make_test_kb()
    context = build_entity_context(QuestionType.RECAP, [], kb, max_tokens=3000)
    assert "Chapter 1" in context or "helldiver" in context
    print("  PASS: RECAP context includes chapter summaries")


def test_world_building_context_includes_facts() -> None:
    """WORLD_BUILDING type returns relevant world facts."""
    kb = _make_test_kb()
    context = build_entity_context(QuestionType.WORLD_BUILDING, [], kb, max_tokens=3000)
    assert "Color System" in context or "Gold" in context
    print("  PASS: WORLD_BUILDING context includes world facts")


def test_empty_kb_returns_empty_string() -> None:
    """Empty KB returns empty string for any question type."""
    kb = KnowledgeBase(series_id="empty")
    context = build_entity_context(QuestionType.CHARACTER, ["Darrow"], kb, max_tokens=3000)
    assert context == ""
    print("  PASS: empty KB returns empty context")


def test_unknown_entity_returns_empty_string() -> None:
    """Mentioned entity not in KB returns empty string."""
    kb = _make_test_kb()
    context = build_entity_context(QuestionType.CHARACTER, ["Ares"], kb, max_tokens=3000)
    assert context == ""
    print("  PASS: unknown entity returns empty context")


# ---------------------------------------------------------------------------
# Part 3: Updated prompt_builder — backwards compat + enriched form
# ---------------------------------------------------------------------------

from src.models import Book, BookStatus, Chapter, Series
from src.query.prompt_builder import QuestionType as PBQuestionType  # re-exported
from src.query.prompt_builder import build_prompt
from src.vector_store.base import SearchResult


def _make_series() -> Series:
    return Series(
        id="red-rising",
        name="Red Rising",
        books=[
            Book(
                index=0,
                title="Red Rising",
                status=BookStatus.COMPLETED,
                chapters=[Chapter(index=i, label=f"Ch {i}") for i in range(20)],
            )
        ],
    )


def _make_chunks() -> list[SearchResult]:
    return [
        SearchResult(
            chunk_id="chunk-1",
            text="Darrow is a Red helldiver from the mines of Mars.",
            chapter_index=0,
            chapter_label="Chapter 1",
            series_id="red-rising",
            book_index=0,
            score=0.9,
        )
    ]


def test_build_prompt_backwards_compatible() -> None:
    """build_prompt without new params still works (no entity_context, no question_type)."""
    prompt = build_prompt("Who is Darrow?", _make_chunks(), _make_series())
    assert "Who is Darrow?" in prompt
    assert "Red Rising" in prompt
    assert "helldiver" in prompt
    print("  PASS: build_prompt backwards compatible (no entity_context)")


def test_build_prompt_with_entity_context() -> None:
    """build_prompt with entity_context includes the structured knowledge section."""
    entity_ctx = "CHARACTER PROFILE — Darrow\nA Red miner who becomes a Gold."
    prompt = build_prompt(
        "Who is Darrow?",
        _make_chunks(),
        _make_series(),
        entity_context=entity_ctx,
        question_type=PBQuestionType.CHARACTER,
    )
    assert "Structured knowledge" in prompt or "CHARACTER PROFILE" in prompt
    assert "Who is Darrow?" in prompt
    print("  PASS: build_prompt includes entity_context when provided")


def test_build_prompt_question_type_instruction() -> None:
    """build_prompt adds question-type-specific instruction when type is provided."""
    prompt = build_prompt(
        "Recap Book 1",
        _make_chunks(),
        _make_series(),
        entity_context="Some summaries here.",
        question_type=PBQuestionType.RECAP,
    )
    # RECAP instruction should appear
    assert "chronological" in prompt.lower() or "recap" in prompt.lower()
    print("  PASS: build_prompt adds question-type instruction")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    """Run all Phase 4 unit tests."""
    print("=== Phase 4: classifier tests ===")
    test_classify_character_questions()
    test_classify_character_arc_questions()
    test_classify_relationship_questions()
    test_classify_recap_questions()
    test_classify_world_building_questions()
    test_classify_causal_questions()
    test_classify_detail_fallback()

    print("\n=== Phase 4: entity mention extraction ===")
    test_extract_entity_mentions_direct_name()
    test_extract_entity_mentions_alias()
    test_extract_entity_mentions_longest_match_first()
    test_extract_entity_mentions_multiple_entities()
    test_extract_entity_mentions_no_match()
    test_extract_entity_mentions_deduplicates()

    print("\n=== Phase 4: context builder ===")
    test_character_context_includes_profile()
    test_character_arc_context_includes_events()
    test_relationship_context_includes_moments()
    test_recap_context_includes_summaries()
    test_world_building_context_includes_facts()
    test_empty_kb_returns_empty_string()
    test_unknown_entity_returns_empty_string()

    print("\n=== Phase 4: prompt builder ===")
    test_build_prompt_backwards_compatible()
    test_build_prompt_with_entity_context()
    test_build_prompt_question_type_instruction()

    print("\nAll Phase 4 unit tests passed.")


if __name__ == "__main__":
    main()
