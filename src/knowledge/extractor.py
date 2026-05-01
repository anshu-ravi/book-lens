"""LLM-powered chapter entity extraction using Claude's tool_use API.

Processes a single chapter and returns a ChapterExtraction — a transient
dataclass containing characters, relationships, world facts, and a summary.
Never persists directly; callers pass the result to merger.merge_extraction().

Uses Claude's tool_use API with a defined schema to guarantee structured
output. With tool_choice forced to a specific tool, Claude's response is
always a ToolUseBlock whose .input is an already-parsed Python dict —
zero JSON parsing required.
"""

import logging

from src.llm import LLMClient

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

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Extraction tool schema
# ---------------------------------------------------------------------------

# Claude is forced to call this tool, guaranteeing the output shape.
# The extracted data matches this schema exactly.
_TOOL_NAME = "record_chapter_knowledge"
_TOOL_DESCRIPTION = (
    "Record all structured knowledge extracted from this fiction chapter: "
    "characters, relationships between them, world-building facts, and a summary."
)
_TOOL_SCHEMA: dict = {
    "type": "object",
    "required": ["characters", "relationships", "world_facts", "summary"],
    "properties": {
        "characters": {
            "type": "array",
            "description": "Characters who appear or are meaningfully referenced in this chapter.",
            "items": {
                "type": "object",
                "required": ["name", "aliases", "description", "key_events"],
                "properties": {
                    "name": {
                        "type": "string",
                        "description": (
                            "Canonical name. Prefer names from the known characters list. "
                            "For truly new characters, use the most formal/complete name."
                        ),
                    },
                    "aliases": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "All other names, titles, and nicknames used in this chapter.",
                    },
                    "faction": {"type": "string"},
                    "role": {
                        "type": "string",
                        "description": "Narrative role, e.g. protagonist, antagonist, mentor, ally.",
                    },
                    "description": {
                        "type": "string",
                        "description": "2-3 sentence description based on this chapter.",
                    },
                    "key_events": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Brief descriptions of significant things that happen "
                            "to or by this character in THIS chapter only."
                        ),
                    },
                },
            },
        },
        "relationships": {
            "type": "array",
            "description": "Relationships between characters shown or developed in this chapter.",
            "items": {
                "type": "object",
                "required": ["character_a", "character_b", "type", "description", "moments"],
                "properties": {
                    "character_a": {"type": "string", "description": "Canonical name."},
                    "character_b": {"type": "string", "description": "Canonical name."},
                    "type": {
                        "type": "string",
                        "enum": ["ally", "rival", "family", "romance", "mentor", "enemy", "other"],
                    },
                    "description": {
                        "type": "string",
                        "description": "Current state of the relationship after this chapter.",
                    },
                    "moments": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Key moments that define or shift the relationship in this chapter.",
                    },
                },
            },
        },
        "world_facts": {
            "type": "array",
            "description": "World-building facts meaningfully established or explained in this chapter.",
            "items": {
                "type": "object",
                "required": ["category", "name", "description"],
                "properties": {
                    "category": {
                        "type": "string",
                        "description": "e.g. faction, location, concept, technology, rule, power_system",
                    },
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                },
            },
        },
        "summary": {
            "type": "string",
            "description": (
                "200-300 word narrative recap of this chapter: "
                "main events, character appearances, and plot developments."
            ),
        },
    },
}


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------


def _build_known_characters_context(kb: KnowledgeBase) -> str:
    """Build a compact known-characters list to include in the extraction prompt.

    Feeding existing canonical names + aliases into each chapter's prompt is
    the coreference resolution strategy — Claude resolves "the Reaper" to
    "Darrow" because it's told that Darrow's aliases include "the Reaper".

    Args:
        kb: Current knowledge base.

    Returns:
        Formatted string listing known characters and their aliases,
        or empty string if no characters have been extracted yet.
    """
    if not kb.characters:
        return ""

    lines: list[str] = []
    for char in kb.characters:
        if char.aliases:
            alias_list = ", ".join(char.aliases)
            lines.append(f"- {char.name} (also known as: {alias_list})")
        else:
            lines.append(f"- {char.name}")
    return "\n".join(lines)


def _build_extraction_prompt(
    chapter: ParsedChapter,
    book_index: int,
    kb: KnowledgeBase,
) -> str:
    """Assemble the full extraction prompt for a chapter.

    Args:
        chapter: Parsed chapter with label and text.
        book_index: 0-based book index in the series.
        kb: Current knowledge base for known-character context.

    Returns:
        Complete prompt string.
    """
    known_context = _build_known_characters_context(kb)
    known_section = (
        f"Known characters in this series — use these exact canonical names:\n{known_context}\n\n"
        if known_context
        else "No characters have been extracted yet (this is the first chapter processed).\n\n"
    )

    return (
        f"{known_section}"
        f"Chapter to analyse:\n"
        f"  Book {book_index + 1}, position {chapter.index + 1}: \"{chapter.label}\"\n\n"
        f"<chapter>\n{chapter.text}\n</chapter>\n\n"
        "Instructions:\n"
        "- Only include characters who appear or are meaningfully referenced\n"
        "- Use canonical names from the known list; only introduce a new canonical name "
        "for a genuinely new character\n"
        "- For new characters, choose the most formal or complete name as canonical\n"
        "- Aliases should capture all other names, titles, and nicknames from this chapter\n"
        "- Key events: specific things that happen in THIS chapter — not general biography\n"
        "- Relationships: only those shown or developed in this chapter\n"
        "- World facts: only facts meaningfully established in this chapter\n"
        "- Summary: 200-300 words covering main events, character appearances, plot developments"
    )


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------


def _parse_tool_input(
    data: dict,
    book_index: int,
    chapter_index: int,
    chapter_label: str,
) -> ChapterExtraction:
    """Convert Claude's tool_use input dict into a ChapterExtraction.

    Args:
        data: The .input dict from the ToolUseBlock.
        book_index: For stamping entities with provenance.
        chapter_index: For stamping entities with provenance.
        chapter_label: For the ChapterSummary label field.

    Returns:
        Populated ChapterExtraction.
    """
    ref = ChapterRef(book_index=book_index, chapter_index=chapter_index)

    characters: list[CharacterEntity] = []
    for c in data.get("characters", []):
        characters.append(
            CharacterEntity(
                name=c["name"],
                aliases=c.get("aliases", []),
                faction=c.get("faction") or None,
                role=c.get("role") or None,
                description=c.get("description", ""),
                first_appearance=ref,
                key_events=[
                    CharacterEvent(
                        description=ev,
                        book_index=book_index,
                        chapter_index=chapter_index,
                    )
                    for ev in c.get("key_events", [])
                ],
            )
        )

    relationships: list[Relationship] = []
    for r in data.get("relationships", []):
        relationships.append(
            Relationship(
                character_a=r["character_a"],
                character_b=r["character_b"],
                type=r.get("type", "other"),
                description=r.get("description", ""),
                moments=[
                    RelationshipMoment(
                        description=m,
                        book_index=book_index,
                        chapter_index=chapter_index,
                    )
                    for m in r.get("moments", [])
                ],
            )
        )

    world_facts: list[WorldFact] = []
    for wf in data.get("world_facts", []):
        world_facts.append(
            WorldFact(
                category=wf.get("category", "concept"),
                name=wf["name"],
                description=wf.get("description", ""),
                book_index=book_index,
                chapter_index=chapter_index,
            )
        )

    summary_text = data.get("summary", "")
    summary = ChapterSummary(
        book_index=book_index,
        chapter_index=chapter_index,
        chapter_label=chapter_label,
        summary=summary_text,
        characters_present=[c.name for c in characters],
        key_events=[ev.description for c in characters for ev in c.key_events],
    )

    return ChapterExtraction(
        characters=characters,
        relationships=relationships,
        world_facts=world_facts,
        summary=summary,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def extract_chapter(
    chapter: ParsedChapter,
    book_index: int,
    kb: KnowledgeBase,
    client: LLMClient,
    extraction_model: str,
) -> ChapterExtraction:
    """Extract structured knowledge from a single chapter using the configured LLM."""
    prompt = _build_extraction_prompt(chapter, book_index, kb)

    logger.debug(
        'Extracting "%s" (book %d, chapter %d)',
        chapter.label,
        book_index,
        chapter.index,
    )

    input_data: dict = await client.extract_structured(
        messages=[{"role": "user", "content": prompt}],
        tool_name=_TOOL_NAME,
        tool_description=_TOOL_DESCRIPTION,
        tool_schema=_TOOL_SCHEMA,
        max_tokens=4096,
    )
    logger.debug(
        '  → %d characters, %d relationships, %d world facts',
        len(input_data.get("characters", [])),
        len(input_data.get("relationships", [])),
        len(input_data.get("world_facts", [])),
    )

    return _parse_tool_input(
        input_data,
        book_index=book_index,
        chapter_index=chapter.index,
        chapter_label=chapter.label,
    )
