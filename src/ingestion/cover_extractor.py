"""Extract cover image from an epub file, with Open Library fallback."""

from pathlib import Path

import ebooklib
import requests
from ebooklib import epub

_OL_SEARCH_URL = "https://openlibrary.org/search.json"
_OL_COVER_URL = "https://covers.openlibrary.org/b"


def extract_cover(epub_path: Path) -> tuple[bytes, str] | None:
    """Extract the cover image from an epub file.

    Tries four strategies in order:
    1. ebooklib ITEM_COVER type
    2. OPF manifest item with properties="cover-image"
    3. OPF <meta name="cover"> reference by item ID (EPUB2 style)
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

    # Strategy 3: EPUB2 <meta name="cover" content="{item-id}"> under OPF namespace.
    # ebooklib stores these under the key "meta", not "cover".
    opf_meta = book.metadata.get("http://www.idpf.org/2007/opf", {})
    for _value, attrs in opf_meta.get("meta", []):
        if attrs.get("name") == "cover":
            cover_id = attrs.get("content")
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


def fetch_cover_open_library(title: str, epub_path: Path | None = None) -> tuple[bytes, str] | None:
    """Fetch a cover image from Open Library.

    Tries ISBN lookup first (if epub_path is provided and contains an ISBN),
    then falls back to a title search.

    Args:
        title: Book title used for the search fallback.
        epub_path: Optional path to the epub file for ISBN extraction.

    Returns:
        Tuple of (image_bytes, ".jpg") or None if no cover found.
    """
    # Try ISBN from epub metadata
    if epub_path is not None:
        isbn = _extract_isbn(epub_path)
        if isbn:
            result = _fetch_ol_cover("isbn", isbn)
            if result:
                return result

    # Fall back to title search
    return _fetch_by_title(title)


def _extract_isbn(epub_path: Path) -> str | None:
    """Extract ISBN-13 or ISBN-10 from epub DC metadata.

    Args:
        epub_path: Path to the epub file.

    Returns:
        ISBN string (digits only) or None if not found.
    """
    book = epub.read_epub(str(epub_path), options={"ignore_ncx": True})
    dc_meta = book.metadata.get("http://purl.org/dc/elements/1.1/", {})
    for value, attrs in dc_meta.get("identifier", []):
        scheme = attrs.get("{http://www.idpf.org/2007/opf}scheme", "").lower()
        if "isbn" in scheme and value:
            return str(value).replace("-", "").strip()
    return None


def _fetch_by_title(title: str) -> tuple[bytes, str] | None:
    """Search Open Library by title and fetch the first result's cover.

    Args:
        title: Book title to search for.

    Returns:
        Tuple of (image_bytes, ".jpg") or None if not found.
    """
    try:
        resp = requests.get(
            _OL_SEARCH_URL,
            params={"title": title, "limit": 1, "fields": "cover_i"},
            timeout=10,
        )
        resp.raise_for_status()
    except requests.RequestException:
        return None

    docs = resp.json().get("docs", [])
    if not docs or "cover_i" not in docs[0]:
        return None

    return _fetch_ol_cover("id", str(docs[0]["cover_i"]))


def _fetch_ol_cover(key: str, value: str) -> tuple[bytes, str] | None:
    """Fetch a cover image from the Open Library covers CDN.

    Args:
        key: Lookup key type — "isbn", "id", "olid", etc.
        value: The value to look up.

    Returns:
        Tuple of (image_bytes, ".jpg") or None if not found or placeholder.
    """
    url = f"{_OL_COVER_URL}/{key}/{value}-L.jpg?default=false"
    try:
        resp = requests.get(url, timeout=10)
    except requests.RequestException:
        return None

    if resp.status_code != 200 or len(resp.content) < 1000:
        return None

    return resp.content, ".jpg"
