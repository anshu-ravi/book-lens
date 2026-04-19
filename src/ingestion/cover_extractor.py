"""Extract cover image from an epub file."""

from pathlib import Path

import ebooklib
from ebooklib import epub


def extract_cover(epub_path: Path) -> tuple[bytes, str] | None:
    """Extract the cover image from an epub file.

    Tries four strategies in order:
    1. ebooklib ITEM_COVER type
    2. OPF manifest item with properties="cover-image"
    3. OPF <meta name="cover"> reference by item ID
    4. First image item with "cover" in the filename

    Args:
        epub_path: Path to the epub file.

    Returns:
        Tuple of (image_bytes, extension) or None if no cover found.
        Extension includes the dot, e.g. ".jpg", ".png". Defaults to ".jpg"
        when the epub item has no file extension.
    """
    book = epub.read_epub(str(epub_path), options={"ignore_ncx": True})

    # Strategy 1: ebooklib ITEM_COVER type
    for item in book.get_items():
        if item.get_type() == ebooklib.ITEM_COVER:
            ext = Path(item.get_name()).suffix or ".jpg"
            return item.get_content(), ext.lower()

    # Strategy 2: OPF manifest properties="cover-image"
    for item in book.get_items():
        props = getattr(item, "properties", None) or []
        if "cover-image" in props:
            ext = Path(item.get_name()).suffix or ".jpg"
            return item.get_content(), ext.lower()

    # Strategy 3: <meta name="cover"> referencing an item ID
    opf_meta = book.metadata.get("http://www.idpf.org/2007/opf", {})
    for meta_entry in opf_meta.get("cover", []):
        cover_id = meta_entry[0] if meta_entry else None
        if cover_id:
            item = book.get_item_with_id(cover_id)
            if item and item.get_type() == ebooklib.ITEM_IMAGE:
                ext = Path(item.get_name()).suffix or ".jpg"
                return item.get_content(), ext.lower()

    # Strategy 4: First image with "cover" in filename
    for item in book.get_items():
        if item.get_type() == ebooklib.ITEM_IMAGE:
            if "cover" in item.get_name().lower():
                ext = Path(item.get_name()).suffix or ".jpg"
                return item.get_content(), ext.lower()

    return None
