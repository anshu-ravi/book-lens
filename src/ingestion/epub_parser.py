"""Epub parsing functionality to extract structured chapter data."""

from pathlib import Path
from typing import List, BinaryIO, Union

import ebooklib  # type: ignore[import-untyped]
from bs4 import BeautifulSoup
from ebooklib import epub  # type: ignore[import-untyped]

from src.models import ParsedChapter


def parse_epub(data: Union[str, Path, BinaryIO]) -> List[ParsedChapter]:
    """
    Parse an epub file into a list of chapters with labels and text.

    Args:
        data: Path to the epub file or a file-like object.

    Returns:
        List of ParsedChapter objects in reading order.

    Raises:
        FileNotFoundError: If epub file doesn't exist (path only).
        ebooklib.epub.EpubException: If file is not a valid epub.
    """
    if isinstance(data, (str, Path)):
        filepath = Path(data)
        if not filepath.exists():
            raise FileNotFoundError(f"Epub file not found: {filepath}")
        # Read the epub file
        book = epub.read_epub(str(filepath), options={"ignore_ncx": True})
    else:
        # data is a file-like object (e.g. BytesIO)
        book = epub.read_epub(data, options={"ignore_ncx": True})

    # Build TOC mapping: href -> label
    toc_map = _build_toc_mapping(book.toc)

    chapters: List[ParsedChapter] = []
    index = 0

    # Iterate through spine (ordered reading sequence)
    for item_id, _ in book.spine:
        item = book.get_item_with_id(item_id)

        # Only process document items (skip images, CSS, etc.)
        if item.get_type() != ebooklib.ITEM_DOCUMENT:
            continue

        # Parse HTML content (epub uses XHTML/XML)
        html_content = item.get_content()
        soup = BeautifulSoup(html_content, "xml")

        # Extract body text (preserve paragraph breaks)
        # Use "\n\n" separator to maintain paragraph boundaries for chunking
        text = soup.get_text(separator="\n\n", strip=True)

        # Skip very short sections (likely metadata, copyright pages, part dividers)
        if len(text) < 100:
            continue

        # Extract chapter label from TOC first, then fallback to content-based extraction
        label = _extract_chapter_label_with_toc(item, soup, toc_map, index)

        # Skip front matter (copyright, contents, etc.)
        if _is_front_matter(label, text):
            continue

        # Create parsed chapter
        chapters.append(ParsedChapter(index=index, label=label, text=text))
        index += 1

    # Handle duplicate labels
    chapters = _deduplicate_labels(chapters)

    return chapters


def _build_toc_mapping(toc: List) -> dict[str, str]:
    """
    Build a mapping from file hrefs to chapter labels from the TOC.

    Handles both flat TOC (list of Links) and nested TOC (Sections with children).

    Args:
        toc: The book's table of contents (can be Links, Sections, or nested tuples).

    Returns:
        Dictionary mapping href (filename) to chapter label.
    """
    toc_map: dict[str, str] = {}

    def process_toc_item(item: object) -> None:
        """Recursively process TOC items (Links and Sections)."""
        # Handle Link objects directly
        if hasattr(item, "href") and hasattr(item, "title"):
            # Extract filename from href (remove anchors like #section1)
            href = str(item.href).split("#")[0]
            toc_map[href] = str(item.title)

        # Handle Section objects (which have children)
        elif hasattr(item, "children"):
            # Process all children (don't add the section itself)
            for child in item.children:
                process_toc_item(child)

        # Handle tuple format: (Section, [children])
        elif isinstance(item, tuple) and len(item) >= 2:
            section, children = item[0], item[1]
            # Process the section itself
            if hasattr(section, "href") and hasattr(section, "title"):
                href = str(section.href).split("#")[0]
                toc_map[href] = str(section.title)
            # Process children
            if isinstance(children, list):
                for child in children:
                    process_toc_item(child)

    # Process all top-level TOC items
    for item in toc:
        process_toc_item(item)

    return toc_map


def _extract_chapter_label_with_toc(
    item: object, soup: BeautifulSoup, toc_map: dict[str, str], fallback_index: int
) -> str:
    """
    Extract chapter label using TOC first, then fallback to content-based extraction.

    Priority:
    1. TOC mapping (href -> label)
    2. Content-based extraction from HTML

    Args:
        item: The epub item being processed.
        soup: BeautifulSoup object of the chapter HTML.
        toc_map: Mapping from href to TOC label.
        fallback_index: Index to use for final fallback.

    Returns:
        Extracted chapter label.
    """
    # Try TOC mapping first
    if hasattr(item, "get_name"):
        item_name = item.get_name()
        if item_name in toc_map:
            return toc_map[item_name]

    # Fallback to content-based extraction
    return _extract_chapter_label(soup, fallback_index)


def _extract_chapter_label(soup: BeautifulSoup, fallback_index: int) -> str:
    """
    Extract chapter label from HTML content with priority hierarchy.

    Priority:
    1. Combined h1 tags (for "number + title" pattern like Red Rising)
    2. Single h1/h2/h3 text content
    3. h1/h2/h3 img alt attribute (for image-based chapter titles)
    4. Elements with class containing "chapter"/"title"/"heading"
    5. Fallback: "Section {index + 1}"

    Args:
        soup: BeautifulSoup object of the chapter HTML.
        fallback_index: Index to use for fallback label.

    Returns:
        Extracted chapter label.
    """
    # Try to detect "number + empty + title" pattern (Red Rising style)
    h1_tags = soup.find_all("h1", limit=3)
    if len(h1_tags) >= 2:
        texts = [tag.get_text(strip=True) for tag in h1_tags]
        # If we have a number, possibly empty middle, and title
        if texts[0] and len(texts) >= 3 and texts[2]:
            # Combine number and title: "1" + "HELLDIVER" -> "1: HELLDIVER"
            return f"{texts[0]}: {texts[2]}"

    # Try h1, h2, h3 tags (single tag approach)
    for tag_name in ["h1", "h2", "h3"]:
        tag = soup.find(tag_name)
        if tag:
            # First try text content
            text = tag.get_text(strip=True)
            if text:
                return text

            # Check for image alt text (critical for image-based chapter titles)
            img = tag.find("img")
            if img:
                alt_text = img.get("alt")
                if alt_text and isinstance(alt_text, str):
                    return alt_text

    # Try class-based elements
    for class_hint in ["chapter", "title", "heading"]:
        elem = soup.find(class_=lambda c: c and class_hint in c.lower())
        if elem:
            text = elem.get_text(strip=True)
            if text:
                return text

    # Fallback to section number
    return f"Section {fallback_index + 1}"


def _is_front_matter(label: str, text: str) -> bool:
    """
    Determine if a section is front matter (copyright, TOC, etc.) vs actual content.

    Front matter to filter:
    - Copyright pages
    - Table of contents
    - Dedication, acknowledgments
    - Publisher info, ISBN pages
    - Character lists
    - Part dividers (very short sections marking book parts)

    NOT filtered (kept as useful content):
    - "The Story So Far" sections (provide context from previous books)
    - Prologues, epilogues (actual story content)

    Args:
        label: The chapter label.
        text: The full text content.

    Returns:
        True if this appears to be front matter, False otherwise.
    """
    label_lower = label.lower()

    # Common front matter keywords to filter
    front_matter_keywords = [
        "copyright",
        "contents",
        "table of contents",
        "toc",
        "dedication",
        "acknowledgment",
        "acknowledgement",
        "also by",
        "other books",
        "title page",
        "half title",
        "publisher",
        "isbn",
        "about the author",
        "praise for",
        "books by",
        "dramatis person",  # Matches "Dramatis Personae"
        "character list",
        "cast of characters",
    ]

    # Check if label matches front matter keywords
    if any(keyword in label_lower for keyword in front_matter_keywords):
        return True

    # Filter part dividers (very short sections that just mark book parts)
    # Example: "Part I: Slave" with only 29 words
    if label_lower.startswith("part ") and len(text.split()) < 100:
        return True

    # Additional heuristic: Very short sections with copyright-like content
    if len(text) < 500 and any(
        phrase in text.lower()
        for phrase in ["copyright ©", "all rights reserved", "published by", "isbn"]
    ):
        return True

    return False


def _deduplicate_labels(chapters: List[ParsedChapter]) -> List[ParsedChapter]:
    """
    Handle duplicate labels by appending (2), (3), etc.

    Modifies chapter labels in place to ensure uniqueness.

    Args:
        chapters: List of parsed chapters.

    Returns:
        List of chapters with deduplicated labels.
    """
    label_counts: dict[str, int] = {}

    for chapter in chapters:
        original_label = chapter.label

        if original_label in label_counts:
            label_counts[original_label] += 1
            chapter.label = f"{original_label} ({label_counts[original_label]})"
        else:
            label_counts[original_label] = 1

    return chapters
