"""Data models for the BookLens application."""

from dataclasses import dataclass
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel


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


class Series(BaseModel):
    """Series containing multiple books."""

    id: str
    name: str
    books: List[Book]


class Library(BaseModel):
    """Complete library state."""

    series: List[Series]
    standalone_books: List[Book] = []


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
