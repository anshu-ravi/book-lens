"""BookLens FastAPI application."""

import logging
import os
import re
import tempfile
import uuid
from contextlib import asynccontextmanager
from io import BytesIO
from typing import Annotated, AsyncGenerator, Optional

from fastapi import (Depends, FastAPI, File, Form, Header,
                     HTTPException, Request, UploadFile)
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from src.config import settings
from src.ingestion.cover_extractor import extract_cover
from src.ingestion.epub_parser import parse_epub
from src.library.manager import (
    get_book_by_id,
    get_series_by_id,
    load_library,
    remove_book,
    remove_series,
    set_book_cover,
    update_book_series,
    update_book_status,
    upsert_book,
)
from src.models import Book, BookRecord, BookStatus, Chapter, Library, Series
from src.supabase_client import get_supabase_client

logger = logging.getLogger(__name__)


def _slugify(text: str) -> str:
    """Convert a title/name to a URL-safe slug."""
    slug = text.strip().lower()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"\s+", "-", slug)
    slug = re.sub(r"-+", "-", slug)
    return slug


# ---------------------------------------------------------------------------
# Auth Dependency
# ---------------------------------------------------------------------------


async def get_current_user(authorization: Optional[str] = Header(None)) -> str:
    """Dependency to get the current authenticated user ID.

    In development mode (no JWT), it can fall back to a dummy ID if configured.
    """
    if not authorization:
        return "00000000-0000-0000-0000-000000000000"

    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authorization header.")

    token = authorization.split(" ")[1]
    client = get_supabase_client()
    try:
        user_resp = client.auth.get_user(token)
        return user_resp.user.id
    except Exception as e:
        logger.warning("Auth verification failed: %s", e)
        raise HTTPException(status_code=401, detail="Invalid or expired token.")


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class UpdateBookStatusRequest(BaseModel):
    """Request body for updating a book's reading status and/or series metadata."""

    status: BookStatus
    current_chapter_index: Optional[int] = None
    series_name: Optional[str] = None
    position_in_series: Optional[float] = None


class UploadBookResponse(BaseModel):
    """Response returned after a successful book upload."""

    book_id: str
    series_id: str
    title: str
    chapter_count: int


class ExtractMetadataResponse(BaseModel):
    """Response returned after extracting metadata from an epub."""

    title: str
    author: Optional[str] = None
    book_name: Optional[str] = None
    series_name: Optional[str] = None
    series_position: Optional[float] = None
    is_series: bool = False


# ---------------------------------------------------------------------------
# App lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Initialise shared resources at startup."""
    yield


app = FastAPI(title="BookLens", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="src/static"), name="static")


@app.get("/", include_in_schema=False)
def root() -> FileResponse:
    """Serve the frontend."""
    return FileResponse("src/static/index.html")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.get("/config")
async def get_config():
    """Return public configuration for the frontend."""
    return {
        "supabase_url": settings.supabase_url,
        "supabase_anon_key": settings.supabase_anon_key or settings.supabase_key,
    }


@app.get("/library", response_model=Library)
async def get_library(user_id: str = Depends(get_current_user)) -> Library:
    """Return the full library state for the current user."""
    return await load_library(user_id)


@app.post("/books/extract-metadata", response_model=ExtractMetadataResponse)
async def extract_metadata_endpoint(
    request: Request, file: UploadFile = File(...)
) -> ExtractMetadataResponse:
    """Extract title, author, and series info from an epub.

    Reads epub metadata locally and returns basic information.
    """
    from ebooklib import epub

    if not file.filename or not file.filename.endswith(".epub"):
        raise HTTPException(status_code=400, detail="File must be an .epub.")

    book_bytes = await file.read()

    # Write to a temp file since ebooklib requires a file path.
    with tempfile.NamedTemporaryFile(suffix=".epub", delete=False) as tmp:
        tmp.write(book_bytes)
        tmp_path = tmp.name

    try:
        book = epub.read_epub(tmp_path)
        title_meta = book.get_metadata("DC", "title")
        author_meta = book.get_metadata("DC", "creator")
        title: str = title_meta[0][0] if title_meta else (file.filename or "Unknown")
        author: Optional[str] = author_meta[0][0] if author_meta else None
    finally:
        os.unlink(tmp_path)

    return ExtractMetadataResponse(
        title=title,
        author=author,
    )


@app.post("/library/books", response_model=UploadBookResponse)
async def upload_book(
    title: Annotated[str, Form()],
    file: UploadFile = File(...),
    user_id: str = Depends(get_current_user),
) -> UploadBookResponse:
    """Upload an epub and register it in the library."""
    if not file.filename or not file.filename.endswith(".epub"):
        raise HTTPException(status_code=400, detail="File must be an .epub.")

    # Generate IDs
    book_id = str(uuid.uuid4())
    series_id = _slugify(title)  # Use book title as series_id for standalone

    book_bytes = await file.read()
    client = get_supabase_client()

    # 1. Parse epub to get chapters
    parsed_chapters = parse_epub(BytesIO(book_bytes))
    chapters_for_db = [{"index": c.index, "label": c.label} for c in parsed_chapters]

    # 2. Store epub per-user
    epub_path = f"{user_id}/{book_id}/book.epub"
    try:
        client.storage.from_("books").upload(
            path=epub_path, file=book_bytes,
            file_options={"content-type": "application/epub+zip"}
        )
    except Exception as e:
        logger.warning("Failed to upload epub to Supabase: %s", e)

    # 3. Extract and save cover
    has_cover = False
    try:
        cover_result = extract_cover(book_bytes)
        if cover_result is not None:
            cover_bytes, _ = cover_result
            cover_path = f"{user_id}/{book_id}/cover.jpg"
            client.storage.from_("covers").upload(
                path=cover_path, file=cover_bytes,
                file_options={"content-type": "image/jpeg"}
            )
            has_cover = True
    except Exception:
        logger.warning("Cover extraction failed; continuing", exc_info=True)

    # 4. Upsert books row
    record = BookRecord(
        id=book_id,
        user_id=user_id,
        series_id=series_id,
        title=title,
        chapters=[Chapter(index=c["index"], label=c["label"]) for c in chapters_for_db],
        status=BookStatus.NOT_STARTED,
        epub_path=epub_path,
        has_cover=has_cover,
    )
    upsert_book(record)

    return UploadBookResponse(
        book_id=book_id,
        series_id=series_id,
        title=title,
        chapter_count=len(parsed_chapters),
    )


@app.get("/library/series/{series_id}/books/{book_index}/cover")
async def get_book_cover(
    series_id: str, book_index: int, user_id: str = Depends(get_current_user)
) -> RedirectResponse:
    """Redirect to the book cover image in Supabase Storage."""
    path = f"{user_id}/{series_id}/cover_{book_index}.jpg"
    url = get_supabase_client().storage.from_("covers").get_public_url(path)
    return RedirectResponse(url)


async def _get_series_id_for_book(book_id: str, user_id: str) -> str:
    """Look up the series_id for a given book_id."""
    client = get_supabase_client()
    resp = (
        client.table("books")
        .select("series_id")
        .filter("id", "eq", book_id)
        .filter("user_id", "eq", user_id)
        .execute()
    )
    if resp.data:
        return resp.data[0]["series_id"]
    return book_id


@app.delete("/library/series/{series_id}", response_model=Library)
async def delete_series_endpoint(
    series_id: str,
    user_id: str = Depends(get_current_user),
) -> Library:
    """Delete all of a user's books in a series."""
    series = await get_series_by_id(series_id, user_id)
    if series is None:
        raise HTTPException(status_code=404, detail=f"Series '{series_id}' not found.")

    client = get_supabase_client()

    for book in series.books:
        cid = book.id
        try:
            client.storage.from_("books").remove([f"{user_id}/{cid}/book.epub"])
            client.storage.from_("covers").remove([f"{user_id}/{cid}/cover.jpg"])
        except Exception as e:
            logger.warning("Storage cleanup failed: %s", e)

    await remove_series(series_id, user_id)
    return await load_library(user_id)


@app.delete("/library/books/{book_id}", response_model=Library)
async def delete_book_endpoint(
    book_id: str,
    user_id: str = Depends(get_current_user),
) -> Library:
    """Remove a book from the user's library."""
    book = await get_book_by_id(book_id, user_id)
    if book is None:
        raise HTTPException(status_code=404, detail=f"Book '{book_id}' not found.")

    series_id = await _get_series_id_for_book(book_id, user_id)

    client = get_supabase_client()
    try:
        client.storage.from_("books").remove([f"{user_id}/{book_id}/book.epub"])
        client.storage.from_("covers").remove([f"{user_id}/{book_id}/cover.jpg"])
    except Exception as e:
        logger.warning("Storage cleanup failed: %s", e)

    await remove_book(book_id, user_id)
    return await load_library(user_id)


@app.patch("/library/books/{book_id}", response_model=Library)
async def update_book_status_endpoint(
    book_id: str,
    body: UpdateBookStatusRequest,
    user_id: str = Depends(get_current_user),
) -> Library:
    """Update a book's reading status and optionally its series metadata."""
    book = await get_book_by_id(book_id, user_id)
    if book is None:
        raise HTTPException(status_code=404, detail=f"Book '{book_id}' not found.")

    await update_book_status(book_id, body.status, body.current_chapter_index, user_id)

    if body.series_name is not None or body.position_in_series is not None:
        update_book_series(book_id, user_id, body.series_name, body.position_in_series)

    return await load_library(user_id)
