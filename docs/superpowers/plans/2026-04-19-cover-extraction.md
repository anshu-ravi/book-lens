# Book Cover Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract the cover image from uploaded epub files and display real cover art in the BookLens library UI instead of the generated CSS placeholders.

**Architecture:** A new `cover_extractor.py` utility tries four strategies to find the cover in an epub (ITEM_COVER type, OPF properties, metadata reference, filename match). The cover is saved to disk during upload (`uploads/{series_id}/cover_{book_index}{ext}`). A new GET endpoint serves it. The `Book` model gains a `has_cover` flag so the frontend knows which books have real art. The library view and continue-card both conditionally swap the generated cover div for a real `<img>`.

**Tech Stack:** Python 3.11, ebooklib, FastAPI FileResponse, Alpine.js `x-show`/`@error`.

---

## File Map

| File | Change |
|------|--------|
| `src/ingestion/cover_extractor.py` | Create — epub cover extraction logic |
| `src/models.py` | Modify — add `has_cover: bool = False` to `Book` |
| `src/main.py` | Modify — import extractor, call in upload, add cover endpoint |
| `src/static/index.html` | Modify — show real cover image in series strip and continue-card |
| `tests/unit/test_cover_extractor.py` | Create — unit tests for extractor (mocked epub) |

---

## Task 1: Cover extractor utility

**Files:**
- Create: `src/ingestion/cover_extractor.py`
- Create: `tests/unit/test_cover_extractor.py`

- [ ] **Step 1: Create the tests directory and write failing tests**

```bash
mkdir -p tests/unit
touch tests/unit/__init__.py
```

Create `tests/unit/test_cover_extractor.py`:

```python
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
    """Strategy 3: <meta name='cover'> reference by item ID."""
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
poetry run pytest tests/unit/test_cover_extractor.py -v
```

Expected: `FAILED` — `ModuleNotFoundError: No module named 'src.ingestion.cover_extractor'`

- [ ] **Step 3: Implement the cover extractor**

Create `src/ingestion/cover_extractor.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
poetry run pytest tests/unit/test_cover_extractor.py -v
```

Expected: 6 tests PASSED

- [ ] **Step 5: Commit**

```bash
git add src/ingestion/cover_extractor.py tests/unit/__init__.py tests/unit/test_cover_extractor.py
git commit -m "feat(ingestion): add epub cover extractor with 4-strategy fallback"
```

---

## Task 2: Wire into upload pipeline and add cover endpoint

**Files:**
- Modify: `src/models.py` (add `has_cover` field to `Book`)
- Modify: `src/main.py` (call extractor in upload, add GET endpoint)

- [ ] **Step 1: Add `has_cover` to the `Book` model**

In `src/models.py`, change the `Book` class (lines 25–33):

```python
class Book(BaseModel):
    """Book metadata and state."""

    index: int
    title: str
    status: BookStatus
    chapters: List[Chapter]
    current_chapter_index: Optional[int] = None
    has_cover: bool = False
```

- [ ] **Step 2: Add the cover extractor import to `main.py`**

In `src/main.py`, add to the imports block after line 17 (`from src.ingestion.epub_parser import parse_epub`):

```python
from src.ingestion.cover_extractor import extract_cover
```

- [ ] **Step 3: Save cover during upload**

In `src/main.py`, in the `upload_book` function, replace the existing `# Update library state` block (starting at line 240) with:

```python
    # Extract and save cover image (best-effort — failure does not abort upload)
    has_cover = False
    cover_result = extract_cover(epub_path)
    if cover_result is not None:
        cover_bytes, cover_ext = cover_result
        cover_file = save_dir / f"cover_{book_index}{cover_ext}"
        cover_file.write_bytes(cover_bytes)
        has_cover = True

    # Update library state
    chapters = [Chapter(index=c.index, label=c.label) for c in parsed_chapters]
    book = Book(
        index=book_index,
        title=title,
        status=BookStatus.NOT_STARTED,
        chapters=chapters,
        has_cover=has_cover,
    )
    updated = upsert_book(library, series_id, book)
    save_library(updated)
```

- [ ] **Step 4: Add the cover serve endpoint**

In `src/main.py`, add this new endpoint after the `upload_book` function (after line 257, before the `delete_series` endpoint):

```python
@app.get("/library/series/{series_id}/books/{book_index}/cover")
def get_book_cover(series_id: str, book_index: int) -> FileResponse:
    """Serve the cover image for a book.

    Args:
        series_id: Series identifier.
        book_index: 0-based book index.

    Returns:
        Cover image file.

    Raises:
        404: If no cover image exists for this book.
    """
    cover_dir = settings.upload_dir / series_id
    for ext in [".jpg", ".jpeg", ".png", ".webp", ".gif"]:
        cover_path = cover_dir / f"cover_{book_index}{ext}"
        if cover_path.exists():
            return FileResponse(str(cover_path))
    raise HTTPException(status_code=404, detail="No cover image for this book.")
```

- [ ] **Step 5: Run the unit tests to confirm nothing regressed**

```bash
poetry run pytest tests/unit/ -v
```

Expected: 6 tests PASSED

- [ ] **Step 6: Smoke-test the endpoint manually**

Start the server:
```bash
poetry run uvicorn src.main:app --reload
```

In a separate terminal, upload a book through the web UI. Then:
```bash
curl -I http://localhost:8000/library/series/<your-series-id>/books/0/cover
```

Expected: `HTTP/1.1 200 OK` with a `content-type: image/jpeg` (or png) header if the epub had a cover, or `HTTP/1.1 404 Not Found` if it didn't.

- [ ] **Step 7: Commit**

```bash
git add src/models.py src/main.py
git commit -m "feat(api): save epub cover on upload and add GET cover endpoint"
```

---

## Task 3: Display real cover images in the frontend

**Files:**
- Modify: `src/static/index.html`

The library view has two places that render covers:
1. **Series strip** — large covers (~line 1153), `width:104px;height:158px`
2. **Continue-card** — small covers (~line 1091), `width:54px;height:82px`

In both places, if `book.has_cover` is true, overlay an `<img>` that fills the cover and hides the generated interior (frame, inner text, sheen). Use `@error="book.has_cover = false"` so if the image 404s unexpectedly, the generated cover gracefully reappears.

- [ ] **Step 1: Update the series strip cover (large cover)**

Find the `<button class="cover"` block in the series strip (around line 1153). Replace it with:

```html
                    <button
                      class="cover"
                      :class="'cover-family-' + (seriesIndex % 5)"
                      style="width:104px;height:158px;"
                      @click="openProgressModal(series, book)"
                      :title="book.title"
                      :aria-label="book.title">
                      <!-- Real cover image -->
                      <img
                        x-show="book.has_cover"
                        :src="`/library/series/${series.id}/books/${book.index}/cover`"
                        :alt="book.title"
                        style="position:absolute;inset:0;width:100%;height:100%;object-fit:cover;border-radius:inherit;z-index:1;"
                        @error="book.has_cover = false">
                      <!-- Generated cover (hidden when real image shown) -->
                      <div class="cover-frame" x-show="!book.has_cover"></div>
                      <div class="cover-inner" x-show="!book.has_cover">
                        <div class="cover-series-label" x-text="series.name"></div>
                        <div class="cover-rule"></div>
                        <div class="cover-title" style="font-size:14px;" x-text="book.title"></div>
                        <div class="cover-bottom">
                          <div class="cover-vol" x-text="'VOL. ' + String(book.index + 1).padStart(2, '0')"></div>
                        </div>
                      </div>
                      <div class="cover-progress-bar" x-show="book.status === 'reading' && book.chapters && book.chapters.length">
                        <div class="cover-progress-fill" :style="'width:' + chapterProgress(book) + '%'"></div>
                      </div>
                      <div class="cover-badge" x-show="book.status === 'completed'">
                        <svg viewBox="0 0 12 12" fill="none"><path d="M2 6l3 3 5-7" stroke="white" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>
                      </div>
                      <div class="cover-unread-tag" x-show="book.status === 'not_started'">UNREAD</div>
                      <div class="cover-sheen" x-show="!book.has_cover"></div>
                    </button>
```

- [ ] **Step 2: Update the continue-card cover (small cover)**

Find the `<div class="cover"` in the continue-card (around line 1091). Replace it with:

```html
              <div class="cover" :class="'cover-family-' + (book._seriesIndex % 5)"
                style="width:54px;height:82px;flex-shrink:0;cursor:default;">
                <!-- Real cover image -->
                <img
                  x-show="book.has_cover"
                  :src="`/library/series/${book._series.id}/books/${book.index}/cover`"
                  :alt="book.title"
                  style="position:absolute;inset:0;width:100%;height:100%;object-fit:cover;border-radius:inherit;z-index:1;"
                  @error="book.has_cover = false">
                <!-- Generated cover (hidden when real image shown) -->
                <div class="cover-frame" x-show="!book.has_cover"></div>
                <div class="cover-inner" style="inset:6px 5px;" x-show="!book.has_cover">
                  <div class="cover-title" style="font-size:9px;" x-text="book.title"></div>
                </div>
                <div class="cover-sheen" x-show="!book.has_cover"></div>
              </div>
```

- [ ] **Step 3: Verify in browser**

Start the server (`poetry run uvicorn src.main:app --reload`) and open `http://localhost:8000`.

- Books uploaded before this change: generated CSS cover still shows (their `has_cover` is `false` in library.json)
- Re-upload an epub — if the epub has a cover, the real image should now appear in both the series strip and continue-card
- When hovering, the cover lift effect should still apply (it's on `.cover:hover` which wraps the img)

- [ ] **Step 4: Commit**

```bash
git add src/static/index.html
git commit -m "feat(frontend): display real epub cover art when available"
```

---

## Self-Review

**Spec coverage:**
- ✅ Cover extracted from epub — Task 1
- ✅ Cover saved to disk on upload — Task 2
- ✅ `has_cover` persisted in library.json — Task 2
- ✅ Endpoint serves cover — Task 2
- ✅ Series strip shows real cover — Task 3
- ✅ Continue-card shows real cover — Task 3
- ✅ Graceful fallback on missing/broken image — Task 3 (`@error`)
- ✅ Previously-uploaded books unaffected — `has_cover` defaults to `false`

**Placeholder scan:** No TBD/TODO. All code blocks are complete.

**Type consistency:** `extract_cover` returns `tuple[bytes, str] | None` everywhere. `Book.has_cover: bool = False` used consistently in models and upload handler.
