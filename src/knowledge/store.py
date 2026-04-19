"""Knowledge base persistence and spoiler-safe filtering.

The knowledge base is stored as a single JSON file per series:
    knowledge/{series_id}.json

All functions are pure: they take and return KnowledgeBase objects without
holding state themselves. This mirrors the pattern in src/library/manager.py.

The filter_to_progress function is the knowledge-layer equivalent of
build_qdrant_filter() in src/query/retriever.py — it applies the same
spoiler boundary to structured entity data:
  - COMPLETED books: all knowledge visible
  - READING books: only knowledge up to current_chapter_index
  - NOT_STARTED books: excluded entirely
"""

import json
from pathlib import Path

from src.config import settings
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


def _knowledge_path(series_id: str) -> Path:
    """Return the path for a series knowledge file.

    Args:
        series_id: Series identifier.

    Returns:
        Path to knowledge/{series_id}.json.
    """
    return Path(settings.knowledge_dir) / f"{series_id}.json"


def load_knowledge(series_id: str) -> KnowledgeBase:
    """Read knowledge base from disk.

    Args:
        series_id: Series identifier.

    Returns:
        Persisted KnowledgeBase, or an empty KnowledgeBase if the file does not exist.
    """
    path = _knowledge_path(series_id)
    if not path.exists():
        return KnowledgeBase(series_id=series_id)
    return KnowledgeBase.model_validate_json(path.read_text(encoding="utf-8"))


def save_knowledge(kb: KnowledgeBase) -> None:
    """Write knowledge base to disk.

    Args:
        kb: KnowledgeBase to persist.
    """
    path = _knowledge_path(kb.series_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(kb.model_dump(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def is_chapter_extracted(kb: KnowledgeBase, book_index: int, chapter_index: int) -> bool:
    """Check whether a chapter has already been processed for extraction.

    Args:
        kb: Current knowledge base.
        book_index: Book to check.
        chapter_index: Chapter to check.

    Returns:
        True if the chapter is in extracted_chapters.
    """
    return any(
        ref.book_index == book_index and ref.chapter_index == chapter_index
        for ref in kb.extracted_chapters
    )


def _is_within_progress(
    book_index: int, chapter_index: int, series: Series
) -> bool:
    """Check if a (book_index, chapter_index) pair is within reading progress.

    Args:
        book_index: Book to check.
        chapter_index: Chapter to check.
        series: Series with book statuses and chapter progress.

    Returns:
        True if the content is within the reader's progress.
    """
    book = next((b for b in series.books if b.index == book_index), None)
    if book is None:
        return False
    if book.status == BookStatus.NOT_STARTED:
        return False
    if book.status == BookStatus.COMPLETED:
        return True
    # READING: only up to current_chapter_index
    max_chapter = book.current_chapter_index if book.current_chapter_index is not None else 0
    return chapter_index <= max_chapter


def filter_to_progress(kb: KnowledgeBase, series: Series) -> KnowledgeBase:
    """Return a KnowledgeBase containing only knowledge within reading progress.

    This is the knowledge-layer equivalent of build_qdrant_filter(). It applies
    the same spoiler boundary so the query engine never sees future content.

    For characters and relationships, the entities themselves are included if
    first_appearance is within scope, but their key_events / moments lists are
    truncated to only include entries within scope.

    Args:
        kb: Full knowledge base (all extracted knowledge).
        series: Series with current reading status per book.

    Returns:
        New KnowledgeBase with spoiler content removed.
    """
    def within(book_index: int, chapter_index: int) -> bool:
        return _is_within_progress(book_index, chapter_index, series)

    # Filter characters: include if first_appearance is in scope,
    # then truncate key_events to those within scope.
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

    # Filter relationships: include if all moments with a chapter stamp are in scope.
    # A relationship is visible if at least one moment is in scope (first moment establishes it).
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

    # Filter world facts by their establishment chapter.
    filtered_world_facts: list[WorldFact] = [
        wf for wf in kb.world_facts if within(wf.book_index, wf.chapter_index)
    ]

    # Filter summaries and extracted_chapters.
    filtered_summaries: list[ChapterSummary] = [
        s for s in kb.summaries if within(s.book_index, s.chapter_index)
    ]
    filtered_extracted: list[ChapterRef] = [
        r for r in kb.extracted_chapters if within(r.book_index, r.chapter_index)
    ]

    # Rebuild alias_registry to only include aliases for visible characters.
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


def delete_series_knowledge(series_id: str) -> None:
    """Delete the entire knowledge file for a series.

    A no-op if no knowledge file exists.

    Args:
        series_id: Series whose knowledge file should be deleted.
    """
    path = _knowledge_path(series_id)
    if path.exists():
        path.unlink()


def delete_book_knowledge(series_id: str, book_index: int) -> KnowledgeBase:
    """Remove all knowledge entries for a specific book from the knowledge base.

    Removes characters first-appearing in that book, relationships whose only
    moments are in that book, world facts established in that book, summaries
    for that book, and extracted_chapter entries for that book.

    Characters who first appeared in the deleted book but have events in other
    books are removed entirely — their first_appearance is gone.

    Args:
        series_id: Series containing the book.
        book_index: 0-based book index to remove.

    Returns:
        Updated KnowledgeBase with the book's entries removed. Also saves to disk.
    """
    kb = load_knowledge(series_id)

    # Remove characters first-appearing in this book.
    kept_characters: list[CharacterEntity] = []
    removed_names: set[str] = set()
    for char in kb.characters:
        if char.first_appearance is not None and char.first_appearance.book_index == book_index:
            removed_names.add(char.name)
        else:
            # Strip any events from this book.
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

    # Remove relationships whose all moments are in this book, or trim moments.
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

    # Rebuild alias_registry excluding removed characters.
    kept_aliases = {
        alias: canonical
        for alias, canonical in kb.alias_registry.items()
        if canonical not in removed_names
    }

    updated = KnowledgeBase(
        series_id=series_id,
        characters=kept_characters,
        relationships=kept_relationships,
        world_facts=kept_world_facts,
        summaries=kept_summaries,
        alias_registry=kept_aliases,
        extracted_chapters=kept_extracted,
    )
    save_knowledge(updated)
    return updated
