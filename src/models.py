"""Data models for the BookLens application."""

from dataclasses import dataclass
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, ConfigDict


class BookStatus(str, Enum):
    """Status of a book in the library."""

    NOT_STARTED = "not_started"
    READING = "reading"
    COMPLETED = "completed"


class Chapter(BaseModel):
    """Chapter metadata stored in library."""

    index: int  # 0-based
    label: str  # "Chapter 1", "Prologue", etc.


class Book(BaseModel):
    """Book metadata and state."""

    index: int
    title: str
    status: BookStatus
    chapters: List[Chapter]
    current_chapter_index: Optional[int] = None
    has_cover: bool = False
    cover_url: Optional[str] = None


class Series(BaseModel):
    """Series containing multiple books."""

    id: str
    name: str
    books: List[Book]


class Library(BaseModel):
    """Complete library state.

    All books live inside a Series, including standalone novels.
    A standalone novel is represented as a single-book series — this avoids
    a separate code path in the query engine and keeps the data model uniform.
    """

    series: List[Series]


@dataclass
class ParsedChapter:
    """
    Temporary data structure for parsed chapter content.

    This is used during epub parsing and is not persisted to library.json.
    Contains the full chapter text which we don't store in the library state.
    """

    index: int
    label: str
    text: str


class ChunkRecord(BaseModel):
    """Represents a chunk of text from a chapter with metadata."""

    chunk_id: str
    chapter_index: int
    chapter_label: str
    text: str
    word_count: int
    position: int  # Chunk number within chapter (0-indexed)

    model_config = ConfigDict(frozen=True)  # Immutable like ParsedChapter
