"""Routes for library management: books, series, upload."""

import logging
import re
import uuid
from io import BytesIO
from typing import Annotated, Optional

from fastapi import (APIRouter, BackgroundTasks, Depends, File, Form, HTTPException,
                     UploadFile)
from pydantic import BaseModel

from backend.api.deps import get_current_user
from backend.config import settings
from backend.ingestion.cover_extractor import extract_cover
from backend.ingestion.epub_parser import parse_epub
from backend.knowledge.extraction_service import ExtractionService
from backend.library.manager import (
    get_book_by_id,
    get_series_by_id,
    load_library,
    remove_book,
    remove_series,
    update_book_status,
    update_book_series,
    upsert_book,
)
from backend.knowledge.query import KnowledgeQueryEngine
from backend.models import Book, BookRecord, BookStatus, Chapter, Library, Series
from backend.supabase_client import get_supabase_client

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/library", tags=["library"])


def _slugify(text: str) -> str:
    """Convert a title/name to a URL-safe slug."""
    slug = text.strip().lower()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"\s+", "-", slug)
    slug = re.sub(r"-+", "-", slug)
    return slug


async def _run_extraction_background(
    user_id: str,
    book_id: str,
    series_id: str,
    epub_bytes: bytes,
    chapters: list[Chapter],
) -> None:
    """Background task to run extraction for a book."""
    try:
        service = ExtractionService(user_id, book_id, series_id)
        await service.extract_book(
            epub_bytes, chapters, series_id=series_id, refresh_mode="skip"
        )
    except Exception as e:
        logger.error(f"Background extraction failed for {book_id}: {e}", exc_info=True)


class TimelineChapter(BaseModel):
    """A chapter entry in the timeline response."""

    chapter_index: int
    name: Optional[str] = None
    summary: Optional[str] = None
    book_id: Optional[str] = None


class TimelineReveal(BaseModel):
    """An identity reveal entry in the timeline response."""

    from_name: str
    to_name: str
    chapter_index: int
    context: Optional[str] = None


class TimelineResponse(BaseModel):
    """Response for the series timeline endpoint."""

    chapters: list[TimelineChapter]
    reveals: list[TimelineReveal]


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


@router.get("/series/{series_id}/timeline", response_model=TimelineResponse)
async def get_series_timeline(
    series_id: str,
    to_chapter: int = 0,
    user_id: str = Depends(get_current_user),
) -> TimelineResponse:
    """Return chapter and reveal data for the story timeline visualization."""
    try:
        engine = KnowledgeQueryEngine(series_id)
        data = engine.get_timeline(to_chapter)
        return TimelineResponse(
            chapters=[TimelineChapter(**c) for c in data["chapters"]],
            reveals=[TimelineReveal(**r) for r in data["reveals"]],
        )
    except Exception as e:
        logger.error("Timeline query failed for series %s: %s", series_id, e, exc_info=True)
        raise HTTPException(status_code=503, detail="Knowledge graph unavailable.")


@router.get("", response_model=Library)
async def get_library(user_id: str = Depends(get_current_user)) -> Library:
    """Return the full library state for the current user."""
    return await load_library(user_id)


@router.post("/books", response_model=UploadBookResponse)
async def upload_book(
    title: Annotated[str, Form()],
    file: UploadFile = File(...),
    user_id: str = Depends(get_current_user),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    series_name: Annotated[Optional[str], Form()] = None,
    series_position: Annotated[Optional[str], Form()] = None,
    is_series: Annotated[str, Form()] = "false",
) -> UploadBookResponse:
    """Upload an epub and register it in the library."""
    if not file.filename or not file.filename.endswith(".epub"):
        raise HTTPException(status_code=400, detail="File must be an .epub.")

    # Parse series metadata from form fields
    parsed_series_name = series_name.strip() if series_name and series_name.strip() else None
    parsed_position: Optional[float] = None
    if series_position:
        try:
            parsed_position = float(series_position)
        except ValueError:
            pass
    parsed_is_series = is_series.lower() == "true"

    # Generate IDs
    book_id = str(uuid.uuid4())
    series_id = _slugify(parsed_series_name or title)

    book_bytes = await file.read()
    client = get_supabase_client()

    # 1. Parse epub to get chapters
    parsed_chapters = parse_epub(BytesIO(book_bytes))
    chapters_for_db = [{"index": c.index, "label": c.label} for c in parsed_chapters]

    # 2. Store epub per-user
    epub_path = f"{user_id}/{book_id}/book.epub"
    try:
        client.storage.from_("books").upload(
            path=epub_path,
            file=book_bytes,
            file_options={"content-type": "application/epub+zip"},
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
                path=cover_path,
                file=cover_bytes,
                file_options={"content-type": "image/jpeg"},
            )
            has_cover = True
    except Exception:
        logger.warning("Cover extraction failed; continuing", exc_info=True)

    # 4. Upsert books row
    chapters_list = [Chapter(index=c["index"], label=c["label"]) for c in chapters_for_db]
    record = BookRecord(
        id=book_id,
        user_id=user_id,
        series_id=series_id,
        title=title,
        chapters=chapters_list,
        status=BookStatus.NOT_STARTED,
        epub_path=epub_path,
        has_cover=has_cover,
        series_name=parsed_series_name,
        position_in_series=parsed_position,
        is_series=parsed_is_series,
    )
    upsert_book(record)

    # 5. Trigger async extraction (if enabled)
    if settings.enable_extraction:
        background_tasks.add_task(
            _run_extraction_background,
            user_id=user_id,
            book_id=book_id,
            series_id=series_id,
            epub_bytes=book_bytes,
            chapters=chapters_list,
        )

    return UploadBookResponse(
        book_id=book_id,
        series_id=series_id,
        title=title,
        chapter_count=len(parsed_chapters),
    )


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


@router.delete("/series/{series_id}", response_model=Library)
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


@router.delete("/books/{book_id}", response_model=Library)
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


@router.patch("/books/{book_id}", response_model=Library)
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
