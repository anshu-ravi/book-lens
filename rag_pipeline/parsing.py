"""Convert EPUB chapters into LlamaIndex Document objects."""

from pathlib import Path
from typing import Optional

from llama_index.core import Document

from src.ingestion.epub_parser import parse_epub


def load_documents(
    book_path: Path,
    limit: Optional[int] = None,
    book_title: str = "Red Rising",
) -> list[Document]:
    """Parse an EPUB and return one LlamaIndex Document per chapter.

    Each Document carries chapter_index and chapter_label as metadata so
    downstream spoiler-safety filters can gate on chapter position.

    Args:
        book_path: Path to the .epub file.
        limit: If set, only load the first N chapters.
        book_title: Used as metadata on every document.

    Returns:
        List of Documents ordered by chapter index.
    """
    chapters = parse_epub(book_path)
    if limit is not None:
        chapters = chapters[:limit]

    documents = []
    for ch in chapters:
        doc = Document(
            text=ch.text,
            metadata={
                "chapter_index": ch.index,
                "chapter_label": ch.label,
                "book_title": book_title,
            },
            # Don't leak chapter_index into the text seen by the LLM or embedder —
            # it's only used as a filter key.
            excluded_llm_metadata_keys=["chapter_index"],
            excluded_embed_metadata_keys=["chapter_index"],
        )
        documents.append(doc)

    return documents
