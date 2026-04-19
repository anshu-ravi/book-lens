"""Merge a ChapterExtraction into an existing KnowledgeBase.

The single entry point is merge_extraction(). It handles:

  Characters — deduplicated by canonical name and alias matching.
    If an extracted character's name or any of its aliases already exists
    in the alias_registry, it is merged into the existing character
    (new aliases added, new key_events appended, first_appearance preserved).
    Otherwise it is added as a new character.

  Relationships — deduplicated by unordered (character_a, character_b) pair.
    New moments are appended; description updated to the latest version.

  World facts — deduplicated by (category.lower(), name.lower()).
    The longer description is kept.

  Summaries — appended unconditionally (one per chapter).

  alias_registry — rebuilt after every merge to reflect all current aliases.

  extracted_chapters — current chapter appended.
"""

from src.knowledge.models import (
    ChapterExtraction,
    ChapterRef,
    ChapterSummary,
    CharacterEntity,
    KnowledgeBase,
    Relationship,
    WorldFact,
)


def _find_existing_character_index(
    name: str,
    aliases: list[str],
    alias_registry: dict[str, str],
    characters: list[CharacterEntity],
) -> int | None:
    """Return the index of an existing character that matches name or any alias.

    Lookup order:
    1. Check if name.lower() is a known alias → get canonical name → find char.
    2. Check if any of the new aliases (lowercased) is a known alias.
    3. Direct case-insensitive name comparison against all existing characters.

    Args:
        name: Canonical name from the new extraction.
        aliases: Aliases from the new extraction.
        alias_registry: Current lowercased-alias → canonical-name mapping.
        characters: Current character list.

    Returns:
        Index into characters, or None if no match found.
    """
    # Build a quick index: canonical_name_lower → list position
    name_to_idx: dict[str, int] = {c.name.lower(): i for i, c in enumerate(characters)}

    # Check the extracted name itself against the alias registry
    candidate = alias_registry.get(name.lower())
    if candidate and candidate.lower() in name_to_idx:
        return name_to_idx[candidate.lower()]

    # Check each alias from the new extraction
    for alias in aliases:
        candidate = alias_registry.get(alias.lower())
        if candidate and candidate.lower() in name_to_idx:
            return name_to_idx[candidate.lower()]

    # Direct name match (handles case where alias_registry hasn't caught up yet)
    if name.lower() in name_to_idx:
        return name_to_idx[name.lower()]

    return None


def _rebuild_alias_registry(characters: list[CharacterEntity]) -> dict[str, str]:
    """Rebuild the alias_registry from all current characters.

    All aliases (including the canonical name itself) are lowercased and
    mapped to the canonical name. Called after every merge.

    Args:
        characters: Full updated character list.

    Returns:
        Fresh alias_registry dict.
    """
    registry: dict[str, str] = {}
    for char in characters:
        registry[char.name.lower()] = char.name
        for alias in char.aliases:
            registry[alias.lower()] = char.name
    return registry


def merge_extraction(
    kb: KnowledgeBase,
    extraction: ChapterExtraction,
    book_index: int,
    chapter_index: int,
) -> KnowledgeBase:
    """Merge a single chapter's extraction into the knowledge base.

    Returns a new KnowledgeBase — does not mutate the input.

    Args:
        kb: Current knowledge base.
        extraction: Extraction result from extractor.extract_chapter().
        book_index: Book this chapter belongs to.
        chapter_index: Chapter position within the book.

    Returns:
        Updated KnowledgeBase with the new chapter's knowledge merged in.
    """
    # Work on mutable copies so the original is not mutated.
    characters: list[CharacterEntity] = list(kb.characters)
    alias_registry: dict[str, str] = dict(kb.alias_registry)

    # ------------------------------------------------------------------
    # Merge characters
    # ------------------------------------------------------------------
    for new_char in extraction.characters:
        idx = _find_existing_character_index(
            new_char.name, new_char.aliases, alias_registry, characters
        )

        if idx is not None:
            existing = characters[idx]
            # Merge: preserve canonical name and first_appearance;
            # extend aliases (deduped); append new key_events.
            merged_aliases = list(existing.aliases)
            for alias in new_char.aliases:
                if alias not in merged_aliases and alias != existing.name:
                    merged_aliases.append(alias)

            characters[idx] = CharacterEntity(
                name=existing.name,
                aliases=merged_aliases,
                faction=new_char.faction or existing.faction,
                role=new_char.role or existing.role,
                # Keep existing description unless the new one is longer/richer.
                description=(
                    new_char.description
                    if len(new_char.description) > len(existing.description)
                    else existing.description
                ),
                first_appearance=existing.first_appearance,
                key_events=existing.key_events + new_char.key_events,
            )
        else:
            # New character — add directly.
            characters.append(new_char)

        # Update alias_registry immediately so subsequent characters in the
        # same extraction can resolve against newly added aliases.
        alias_registry = _rebuild_alias_registry(characters)

    # ------------------------------------------------------------------
    # Merge relationships
    # ------------------------------------------------------------------
    relationships: list[Relationship] = list(kb.relationships)

    for new_rel in extraction.relationships:
        # Normalise pair order for deduplication.
        pair = frozenset({new_rel.character_a, new_rel.character_b})
        existing_idx: int | None = None
        for i, rel in enumerate(relationships):
            if frozenset({rel.character_a, rel.character_b}) == pair:
                existing_idx = i
                break

        if existing_idx is not None:
            existing_rel = relationships[existing_idx]
            relationships[existing_idx] = Relationship(
                character_a=existing_rel.character_a,
                character_b=existing_rel.character_b,
                type=new_rel.type,  # Use latest type assessment
                description=new_rel.description,  # Use latest description
                moments=existing_rel.moments + new_rel.moments,
            )
        else:
            relationships.append(new_rel)

    # ------------------------------------------------------------------
    # Merge world facts
    # ------------------------------------------------------------------
    world_facts: list[WorldFact] = list(kb.world_facts)

    for new_wf in extraction.world_facts:
        key = (new_wf.category.lower(), new_wf.name.lower())
        existing_idx = None
        for i, wf in enumerate(world_facts):
            if (wf.category.lower(), wf.name.lower()) == key:
                existing_idx = i
                break

        if existing_idx is not None:
            existing_wf = world_facts[existing_idx]
            # Keep whichever description is more detailed (longer).
            world_facts[existing_idx] = WorldFact(
                category=existing_wf.category,
                name=existing_wf.name,
                description=(
                    new_wf.description
                    if len(new_wf.description) > len(existing_wf.description)
                    else existing_wf.description
                ),
                book_index=existing_wf.book_index,
                chapter_index=existing_wf.chapter_index,
            )
        else:
            world_facts.append(new_wf)

    # ------------------------------------------------------------------
    # Append summary and mark chapter as extracted
    # ------------------------------------------------------------------
    summaries: list[ChapterSummary] = list(kb.summaries)
    if extraction.summary is not None:
        summaries.append(extraction.summary)

    extracted_chapters = list(kb.extracted_chapters) + [
        ChapterRef(book_index=book_index, chapter_index=chapter_index)
    ]

    return KnowledgeBase(
        series_id=kb.series_id,
        characters=characters,
        relationships=relationships,
        world_facts=world_facts,
        summaries=summaries,
        alias_registry=alias_registry,
        extracted_chapters=extracted_chapters,
    )
