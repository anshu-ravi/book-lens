"""Knowledge base persistence and spoiler-safe filtering.

The knowledge base is stored as one row per canonical_series_id in Supabase:
    knowledge table: canonical_series_id (PK), data (JSONB)

Extraction is shared across users — no user_id in this layer.
Spoiler filtering (filter_to_progress) still takes a Series object, whichA
is built per-user from user_books + canonical_books by the library manager.
"""

from src.supabase_client import get_supabase_client
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
from src.models import BookStatus, Series


async def load_knowledge(canonical_series_id: str) -> KnowledgeBase:
    """Read shared knowledge base from Supabase.

    Args:
        canonical_series_id: Canonical series slug or standalone book id.

    Returns:
        KnowledgeBase object (empty if not yet extracted).
    """
    client = get_supabase_client()
    resp = (
        client.table("knowledge")
        .select("data")
        .filter("canonical_series_id", "eq", canonical_series_id)
        .execute()
    )
    if not resp.data:
        return KnowledgeBase(series_id=canonical_series_id)
    return KnowledgeBase.model_validate(resp.data[0]["data"])


async def save_knowledge(kb: KnowledgeBase, canonical_series_id: str) -> None:
    """Write shared knowledge base to Supabase.

    Args:
        kb: KnowledgeBase to persist.
        canonical_series_id: The series key.
    """
    client = get_supabase_client()
    data = kb.model_dump()
    client.table("knowledge").upsert(
        {"canonical_series_id": canonical_series_id, "data": data}
    ).execute()


def is_chapter_extracted(kb: KnowledgeBase, book_index: int, chapter_index: int) -> bool:
    """Check whether a chapter has already been processed for extraction."""
    return any(
        ref.book_index == book_index and ref.chapter_index == chapter_index
        for ref in kb.extracted_chapters
    )


def _is_within_progress(book_index: int, chapter_index: int, series: Series) -> bool:
    """Check if a (book_index, chapter_index) pair is within reading progress."""
    book = next((b for b in series.books if b.index == book_index), None)
    if book is None:
        return False
    if book.status == BookStatus.NOT_STARTED:
        return False
    if book.status == BookStatus.COMPLETED:
        return True
    max_chapter = book.current_chapter_index if book.current_chapter_index is not None else 0
    return chapter_index <= max_chapter


def filter_to_progress(kb: KnowledgeBase, series: Series) -> KnowledgeBase:
    """Return a KnowledgeBase containing only knowledge within reading progress."""
    def within(book_index: int, chapter_index: int) -> bool:
        return _is_within_progress(book_index, chapter_index, series)

    filtered_characters: list[CharacterEntity] = []
    for char in kb.characters:
        if char.first_appearance is None:
            continue
        if not within(char.first_appearance.book_index, char.first_appearance.chapter_index):
            continue
        safe_events: list[CharacterEvent] = [
            e for e in char.key_events if within(e.book_index, e.chapter_index)
        ]
        filtered_characters.append(
            CharacterEntity(
                name=char.name,
                aliases=char.aliases,
                faction=char.faction,
                role=char.role,
                description=char.description,
                first_appearance=char.first_appearance,
                key_events=safe_events,
            )
        )

    filtered_relationships: list[Relationship] = []
    for rel in kb.relationships:
        safe_moments: list[RelationshipMoment] = [
            m for m in rel.moments if within(m.book_index, m.chapter_index)
        ]
        if not safe_moments:
            continue
        filtered_relationships.append(
            Relationship(
                character_a=rel.character_a,
                character_b=rel.character_b,
                type=rel.type,
                description=rel.description,
                moments=safe_moments,
            )
        )

    filtered_world_facts: list[WorldFact] = [
        wf for wf in kb.world_facts if within(wf.book_index, wf.chapter_index)
    ]
    filtered_summaries: list[ChapterSummary] = [
        s for s in kb.summaries if within(s.book_index, s.chapter_index)
    ]
    filtered_extracted: list[ChapterRef] = [
        r for r in kb.extracted_chapters if within(r.book_index, r.chapter_index)
    ]

    visible_names = {c.name for c in filtered_characters}
    filtered_aliases = {
        alias: canonical
        for alias, canonical in kb.alias_registry.items()
        if canonical in visible_names
    }

    return KnowledgeBase(
        series_id=kb.series_id,
        characters=filtered_characters,
        relationships=filtered_relationships,
        world_facts=filtered_world_facts,
        summaries=filtered_summaries,
        alias_registry=filtered_aliases,
        extracted_chapters=filtered_extracted,
    )


async def delete_series_knowledge(canonical_series_id: str) -> None:
    """Delete the knowledge for a series (only if no other users reference it)."""
    client = get_supabase_client()
    client.table("knowledge").delete().filter("canonical_series_id", "eq", canonical_series_id).execute()


async def delete_book_knowledge(canonical_series_id: str, book_index: int) -> KnowledgeBase:
    """Remove knowledge entries for a specific book index and save."""
    kb = await load_knowledge(canonical_series_id)

    kept_characters: list[CharacterEntity] = []
    removed_names: set[str] = set()
    for char in kb.characters:
        if char.first_appearance is not None and char.first_appearance.book_index == book_index:
            removed_names.add(char.name)
        else:
            safe_events = [e for e in char.key_events if e.book_index != book_index]
            kept_characters.append(
                CharacterEntity(
                    name=char.name,
                    aliases=char.aliases,
                    faction=char.faction,
                    role=char.role,
                    description=char.description,
                    first_appearance=char.first_appearance,
                    key_events=safe_events,
                )
            )

    kept_relationships: list[Relationship] = []
    for rel in kb.relationships:
        if rel.character_a in removed_names or rel.character_b in removed_names:
            continue
        kept_moments = [m for m in rel.moments if m.book_index != book_index]
        if not kept_moments:
            continue
        kept_relationships.append(
            Relationship(
                character_a=rel.character_a,
                character_b=rel.character_b,
                type=rel.type,
                description=rel.description,
                moments=kept_moments,
            )
        )

    kept_world_facts = [wf for wf in kb.world_facts if wf.book_index != book_index]
    kept_summaries = [s for s in kb.summaries if s.book_index != book_index]
    kept_extracted = [r for r in kb.extracted_chapters if r.book_index != book_index]
    kept_aliases = {
        alias: canonical
        for alias, canonical in kb.alias_registry.items()
        if canonical not in removed_names
    }

    updated = KnowledgeBase(
        series_id=canonical_series_id,
        characters=kept_characters,
        relationships=kept_relationships,
        world_facts=kept_world_facts,
        summaries=kept_summaries,
        alias_registry=kept_aliases,
        extracted_chapters=kept_extracted,
    )
    await save_knowledge(updated, canonical_series_id)
    return updated
