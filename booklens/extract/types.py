"""Data contracts for the extraction layer.

Pure data + exceptions. No behaviour lives here.
"""

from __future__ import annotations

from dataclasses import dataclass


class ExtractionError(Exception):
    """Base class for all extraction failures."""


class DrmProtectedError(ExtractionError):
    """A spine (content) document is encrypted; the book cannot be read."""


class MalformedEpubError(ExtractionError):
    """The EPUB container, OPF, or other required structure is unreadable or absent."""


@dataclass(frozen=True)
class Paragraph:
    """One paragraph of flattened text, the unit citations resolve to."""

    spine_idx: int
    para_idx: int  # 0-based index WITHIN the spine document
    text: str  # flattened, whitespace-normalised, never empty


@dataclass(frozen=True)
class Document:
    """One spine document and the paragraphs extracted from it."""

    spine_idx: int  # 0-based position in the resolved sequence
    href: str  # zip entry path, for re-extraction
    paragraphs: tuple[Paragraph, ...]


@dataclass(frozen=True)
class Chapter:
    """A run of spine documents the reader thinks of as one chapter."""

    chapter_idx: int  # 0-based, in reading order
    label: str  # e.g. "Chapter 12", "Prologue", "Document 47"
    part_label: str | None  # e.g. "Part III" when a part ladder resolved
    start_spine_idx: int
    end_spine_idx: int  # INCLUSIVE


@dataclass(frozen=True)
class BookExtraction:
    """Everything read out of one EPUB, before any of it reaches a database."""

    title: str
    author: str | None
    source_path: str
    sha256: str  # hex digest of the EPUB file bytes
    documents: tuple[Document, ...]
    chapters: tuple[Chapter, ...]
    sequence_tier: str  # "S1" | "S2" | "S3"
    label_tier: str  # "L1" | "L2" | "L3" | "L4", or composed: "L1+L3"
