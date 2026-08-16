"""EPUB extraction: pure functions from an EPUB file to a BookExtraction."""

from .cover import CoverImage, extract_cover
from .epub import extract_book
from .series_hint import SeriesHint, read_series_hint
from .types import (
    BookExtraction,
    Chapter,
    Document,
    DrmProtectedError,
    ExtractionError,
    MalformedEpubError,
    Paragraph,
)

__all__ = [
    "extract_book",
    "extract_cover",
    "read_series_hint",
    "BookExtraction",
    "Chapter",
    "CoverImage",
    "Document",
    "DrmProtectedError",
    "ExtractionError",
    "MalformedEpubError",
    "Paragraph",
    "SeriesHint",
]
