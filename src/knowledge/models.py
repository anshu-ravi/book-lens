"""Data models for the BookLens knowledge base.

These models represent the structured entities extracted from book text:
characters, relationships, world facts, and chapter summaries. All persisted
models are Pydantic BaseModel; transient extraction results use @dataclass.

The KnowledgeBase is the root object persisted as knowledge/{series_id}.json.
"""

from dataclasses import dataclass, field
from typing import Optional

from pydantic import BaseModel


class ChapterRef(BaseModel):
    """Reference to a specific chapter within the series.

    Used as a stamp on every piece of knowledge so spoiler filtering
    can determine whether it is within the reader's current progress.
    """

    book_index: int
    chapter_index: int


class CharacterEvent(BaseModel):
    """A significant event involving a character at a specific chapter."""

    description: str
    book_index: int
    chapter_index: int


class CharacterEntity(BaseModel):
    """A named character in the series, with their profile and story events.

    The name field holds the canonical form (e.g. "Darrow"). All other
    names, titles, and nicknames are listed in aliases. The alias_registry
    on KnowledgeBase maps every lowercased alias → canonical name for fast lookup.
    """

    name: str
    aliases: list[str] = []
    faction: Optional[str] = None
    role: Optional[str] = None
    description: str = ""
    first_appearance: Optional[ChapterRef] = None
    key_events: list[CharacterEvent] = []


class RelationshipMoment(BaseModel):
    """A key moment that defined or changed a relationship between two characters."""

    description: str
    book_index: int
    chapter_index: int


class Relationship(BaseModel):
    """The relationship between two characters, tracked over time.

    character_a and character_b store canonical names. The pair is stored
    in a consistent order (alphabetical) so lookups are order-independent.
    """

    character_a: str
    character_b: str
    type: str  # "ally", "rival", "family", "romance", "mentor", "enemy", "other"
    description: str
    moments: list[RelationshipMoment] = []


class WorldFact(BaseModel):
    """A piece of world-building knowledge: factions, locations, concepts, rules.

    category is a free-form string (e.g. "faction", "location", "concept",
    "technology", "power_system") — not an enum, to accommodate any genre.
    """

    category: str
    name: str
    description: str
    book_index: int
    chapter_index: int  # Chapter where this fact was first established


class ChapterSummary(BaseModel):
    """A 200-300 word narrative summary of a single chapter.

    characters_present lists canonical names of characters who appear
    in the chapter, enabling fast lookup of "which chapters feature X?"
    """

    book_index: int
    chapter_index: int
    chapter_label: str
    summary: str
    characters_present: list[str] = []
    key_events: list[str] = []


class KnowledgeBase(BaseModel):
    """Complete structured knowledge for a series, persisted as JSON.

    One KnowledgeBase file per series: knowledge/{series_id}.json.

    alias_registry maps every known lowercased alias → canonical character name.
    This is built during extraction and used by the query engine for entity
    mention detection without scanning full character profiles.

    extracted_chapters tracks which (book_index, chapter_index) pairs have
    been processed, enabling idempotent and incremental extraction.
    """

    series_id: str
    characters: list[CharacterEntity] = []
    relationships: list[Relationship] = []
    world_facts: list[WorldFact] = []
    summaries: list[ChapterSummary] = []
    alias_registry: dict[str, str] = {}
    extracted_chapters: list[ChapterRef] = []


@dataclass
class ChapterExtraction:
    """Transient extraction result for a single chapter.

    Never persisted directly — merged into KnowledgeBase by merger.py.
    Mirrors ParsedChapter's pattern of using @dataclass for pipeline intermediates.
    """

    characters: list[CharacterEntity] = field(default_factory=list)
    relationships: list[Relationship] = field(default_factory=list)
    world_facts: list[WorldFact] = field(default_factory=list)
    summary: Optional[ChapterSummary] = None
