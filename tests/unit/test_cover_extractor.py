"""Unit tests for epub cover extractor."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import ebooklib
import pytest

from src.ingestion.cover_extractor import extract_cover


def _make_item(
    item_type: int,
    name: str,
    content: bytes,
    properties: list[str] | None = None,
) -> MagicMock:
    item = MagicMock()
    item.get_type.return_value = item_type
    item.get_name.return_value = name
    item.get_content.return_value = content
    item.properties = properties or []
    return item


@patch("src.ingestion.cover_extractor.epub.read_epub")
def test_extract_cover_item_cover_type(mock_read_epub: MagicMock) -> None:
    """Strategy 1: ebooklib ITEM_COVER type."""
    cover_bytes = b"fake-cover-jpg"
    cover_item = _make_item(ebooklib.ITEM_COVER, "images/cover.jpg", cover_bytes)

    book = MagicMock()
    book.get_items.return_value = [cover_item]
    book.metadata = {}
    mock_read_epub.return_value = book

    result = extract_cover(Path("dummy.epub"))

    assert result is not None
    assert result[0] == cover_bytes
    assert result[1] == ".jpg"


@patch("src.ingestion.cover_extractor.epub.read_epub")
def test_extract_cover_properties(mock_read_epub: MagicMock) -> None:
    """Strategy 2: OPF properties='cover-image'."""
    cover_bytes = b"fake-cover-png"
    cover_item = _make_item(
        ebooklib.ITEM_IMAGE, "images/cover.png", cover_bytes, ["cover-image"]
    )

    book = MagicMock()
    book.get_items.return_value = [cover_item]
    book.metadata = {}
    mock_read_epub.return_value = book

    result = extract_cover(Path("dummy.epub"))

    assert result is not None
    assert result[0] == cover_bytes
    assert result[1] == ".png"


@patch("src.ingestion.cover_extractor.epub.read_epub")
def test_extract_cover_metadata_reference(mock_read_epub: MagicMock) -> None:
    """Strategy 3: meta name='cover' reference by item ID."""
    cover_bytes = b"fake-cover-jpeg"
    cover_item = _make_item(ebooklib.ITEM_IMAGE, "OEBPS/cover.jpeg", cover_bytes)

    book = MagicMock()
    book.get_items.return_value = [cover_item]
    book.get_item_with_id.return_value = cover_item
    book.metadata = {
        "http://www.idpf.org/2007/opf": {"cover": [("cover-image-id", {})]}
    }
    mock_read_epub.return_value = book

    result = extract_cover(Path("dummy.epub"))

    assert result is not None
    assert result[0] == cover_bytes
    assert result[1] == ".jpeg"


@patch("src.ingestion.cover_extractor.epub.read_epub")
def test_extract_cover_filename_fallback(mock_read_epub: MagicMock) -> None:
    """Strategy 4: First image with 'cover' in filename."""
    cover_bytes = b"fake-cover-jpg"
    doc_item = _make_item(ebooklib.ITEM_DOCUMENT, "chapter1.xhtml", b"text")
    cover_item = _make_item(ebooklib.ITEM_IMAGE, "OEBPS/Images/Cover.jpg", cover_bytes)

    book = MagicMock()
    book.get_items.return_value = [doc_item, cover_item]
    book.metadata = {}
    mock_read_epub.return_value = book

    result = extract_cover(Path("dummy.epub"))

    assert result is not None
    assert result[0] == cover_bytes
    assert result[1] == ".jpg"


@patch("src.ingestion.cover_extractor.epub.read_epub")
def test_extract_cover_returns_none_when_no_cover(mock_read_epub: MagicMock) -> None:
    """Returns None when epub has no identifiable cover image."""
    doc_item = _make_item(ebooklib.ITEM_DOCUMENT, "chapter1.xhtml", b"text")

    book = MagicMock()
    book.get_items.return_value = [doc_item]
    book.metadata = {}
    mock_read_epub.return_value = book

    result = extract_cover(Path("dummy.epub"))

    assert result is None


@patch("src.ingestion.cover_extractor.epub.read_epub")
def test_extract_cover_no_extension_defaults_to_jpg(mock_read_epub: MagicMock) -> None:
    """When image has no file extension, defaults to .jpg."""
    cover_bytes = b"fake-cover"
    cover_item = _make_item(ebooklib.ITEM_COVER, "images/cover", cover_bytes)

    book = MagicMock()
    book.get_items.return_value = [cover_item]
    book.metadata = {}
    mock_read_epub.return_value = book

    result = extract_cover(Path("dummy.epub"))

    assert result is not None
    assert result[1] == ".jpg"
