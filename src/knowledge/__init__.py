"""Knowledge base package for entity extraction and structured retrieval."""

from src.knowledge.extractor import extract_chapter
from src.knowledge.merger import merge_extraction
from src.knowledge.pipeline import extract_book_knowledge
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
from src.knowledge.store import (
    delete_book_knowledge,
    delete_series_knowledge,
    filter_to_progress,
    is_chapter_extracted,
    load_knowledge,
    save_knowledge,
)

__all__ = [
    # Extraction
    "extract_book_knowledge",
    "extract_chapter",
    "merge_extraction",
    # Models
    "ChapterExtraction",
    "ChapterRef",
    "ChapterSummary",
    "CharacterEntity",
    "CharacterEvent",
    "KnowledgeBase",
    "Relationship",
    "RelationshipMoment",
    "WorldFact",
    # Store
    "delete_book_knowledge",
    "delete_series_knowledge",
    "filter_to_progress",
    "is_chapter_extracted",
    "load_knowledge",
    "save_knowledge",
]
