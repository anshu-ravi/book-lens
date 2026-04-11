"""Epub parsing functionality to extract structured chapter data."""

from pathlib import Path
from typing import List

import ebooklib  # type: ignore[import-untyped]
from bs4 import BeautifulSoup
from ebooklib import epub  # type: ignore[import-untyped]

from src.models import ParsedChapter


def parse_epub(filepath: str | Path) -> List[ParsedChapter]:
    """
    Parse an epub file into a list of chapters with labels and text.

    Args:
        filepath: Path to the epub file.

    Returns:
        List of ParsedChapter objects in reading order.

    Raises:
        FileNotFoundError: If epub file doesn't exist.
        ebooklib.epub.EpubException: If file is not a valid epub.
    """
    filepath = Path(filepath)
    if not filepath.exists():
        raise FileNotFoundError(f"Epub file not found: {filepath}")

    # Read the epub file
    book = epub.read_epub(str(filepath))

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

        # Extract chapter label
        label = _extract_chapter_label(soup, index)

        # Extract body text (remove HTML tags)
        text = soup.get_text(separator=" ", strip=True)

        # Skip very short sections (likely metadata, copyright pages, etc.)
        if len(text) < 100:
            continue

        # Create parsed chapter
        chapters.append(ParsedChapter(index=index, label=label, text=text))
        index += 1

    # Handle duplicate labels
    chapters = _deduplicate_labels(chapters)

    return chapters


def _extract_chapter_label(soup: BeautifulSoup, fallback_index: int) -> str:
    """
    Extract chapter label with priority hierarchy.

    Priority:
    1. h1/h2/h3 text content
    2. h1/h2/h3 img alt attribute (for image-based chapter titles)
    3. Elements with class containing "chapter"/"title"/"heading"
    4. Fallback: "Section {index + 1}"

    Args:
        soup: BeautifulSoup object of the chapter HTML.
        fallback_index: Index to use for fallback label.

    Returns:
        Extracted chapter label.
    """
    # Try h1, h2, h3 tags
    for tag_name in ["h1", "h2", "h3"]:
        tag = soup.find(tag_name)
        if tag:
            # First try text content
            text = tag.get_text(strip=True)
            if text:
                return text

            # ENHANCEMENT: Check for image alt text
            # This is critical for epubs that use images for chapter titles
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
