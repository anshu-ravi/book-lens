"""BookLens FastAPI application."""

import logging
import re
from contextlib import asynccontextmanager
from io import BytesIO
from typing import Annotated, AsyncGenerator, Optional

from src.llm import LLMClient, create_llm_client
from fastapi import (BackgroundTasks, Depends, FastAPI, File, Form, Header,
                     HTTPException, Request, UploadFile)
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from src.books.open_library import search_books, OLBookResult
from src.config import settings
from src.graph.builder import build_graph_payload
from src.graph.digest import generate_digest
from src.ingestion.chunker import chunk_chapter
from src.ingestion.cover_extractor import (extract_cover,
                                           fetch_cover_open_library)
from src.ingestion.embedder import get_embedder
from src.ingestion.epub_parser import parse_epub
from src.ingestion.indexer import index_book
from src.knowledge.models import KnowledgeBase
from src.knowledge.pipeline import extract_book_knowledge
from src.knowledge.store import (delete_book_knowledge,
                                 delete_series_knowledge, filter_to_progress,
                                 load_knowledge)
from src.library.manager import (
    get_book_by_canonical_id,
    get_series_by_canonical_id,
    load_library,
    other_users_have_book,
    other_users_have_series,
    remove_user_book,
    remove_user_series,
    set_user_book_cover,
    update_canonical_book_series,
    update_user_book_status,
    upsert_canonical_book,
    upsert_user_book,
)
from src.models import Book, BookStatus, CanonicalBook, Chapter, Library, UserBook
from src.query.classifier import classify_question, extract_entity_mentions
from src.query.context_builder import build_entity_context
from src.query.prompt_builder import QuestionType, build_prompt
from src.query.retriever import retrieve_chunks
from src.supabase_client import get_supabase_client
from src.vector_store.supabase_store import SupabaseVectorStore

logger = logging.getLogger(__name__)

_KB_ONLY_QUESTION_TYPES = {QuestionType.CHARACTER, QuestionType.CHARACTER_ARC}

_CHAPTER_NUM_RE = re.compile(r'\bchapter\s+(\d+)\b', re.IGNORECASE)


def _get_chapters_in_scope(series: "Series") -> list[tuple[int, int]]:
    """Return (book_index, chapter_index) pairs for all chapters within reading progress."""
    result: list[tuple[int, int]] = []
    for book in series.books:
        if book.status == BookStatus.NOT_STARTED:
            continue
        for chapter in book.chapters:
            if book.status == BookStatus.COMPLETED:
                result.append((book.index, chapter.index))
            elif book.status == BookStatus.READING:
                max_ch = book.current_chapter_index if book.current_chapter_index is not None else 0
                if chapter.index <= max_ch:
                    result.append((book.index, chapter.index))
    return result


def _resolve_chapter_reference(question: str, series: "Series") -> tuple[int, int] | None:
    """Parse a chapter number from the question and resolve it to (book_index, chapter_index).

    Only returns a result if the referenced chapter is within the user's reading
    progress. Returns None if no chapter number is found or the chapter is out
    of scope.
    """
    match = _CHAPTER_NUM_RE.search(question)
    if not match:
        return None

    chapter_num = int(match.group(1))

    for book in series.books:
        if book.status == BookStatus.NOT_STARTED:
            continue
        for chapter in book.chapters:
            label_match = re.match(r'chapter\s+(\d+)', chapter.label, re.IGNORECASE)
            if label_match and int(label_match.group(1)) == chapter_num:
                if book.status == BookStatus.COMPLETED:
                    return (book.index, chapter.index)
                # READING: only chapters up to current progress
                max_ch = book.current_chapter_index if book.current_chapter_index is not None else 0
                if chapter.index <= max_ch:
                    return (book.index, chapter.index)

    return None

# ---------------------------------------------------------------------------
# Auth Dependency
# ---------------------------------------------------------------------------


async def get_current_user(authorization: Optional[str] = Header(None)) -> str:
    """Dependency to get the current authenticated user ID.

    In development mode (no JWT), it can fall back to a dummy ID if configured.
    """
    # For local testing, if no auth header is provided, use a dummy ID.
    if not authorization:
        # Check if we are in a testing/local context
        return "00000000-0000-0000-0000-000000000000"

    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authorization header.")

    token = authorization.split(" ")[1]
    client = get_supabase_client()
    try:
        # Note: This verifies the token with Supabase Auth
        user_resp = client.auth.get_user(token)
        return user_resp.user.id
    except Exception as e:
        logger.warning("Auth verification failed: %s", e)
        raise HTTPException(status_code=401, detail="Invalid or expired token.")


# ---------------------------------------------------------------------------
# Admin and utility functions
# ---------------------------------------------------------------------------


def _is_admin(user_id: str) -> bool:
    """Return True if the user is the configured admin."""
    return bool(settings.admin_user_id and user_id == settings.admin_user_id)


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class UpdateBookStatusRequest(BaseModel):
    """Request body for updating a book's reading status and/or series metadata."""

    status: BookStatus
    current_chapter_index: Optional[int] = None
    series_name: Optional[str] = None
    series_position: Optional[float] = None


class QueryRequest(BaseModel):
    """Request body for the query endpoint."""

    series_id: str
    question: str
    top_k: int = 12
    conversation_history: list[dict] = []
    mode: str = "default"


class ProactivePromptRequest(BaseModel):
    """Request body for proactive check-in prompt."""
    series_id: str
    book_index: int
    chapter_index: int


class ProactivePromptResponse(BaseModel):
    """Response containing the check-in question."""
    question: str


class SourceChunk(BaseModel):
    """A single source chunk returned alongside a query answer."""

    book_index: int
    chapter_label: str
    score: float


class QueryResponse(BaseModel):
    """Response returned from the query endpoint."""

    answer: str
    sources: list[SourceChunk]
    question_type: Optional[str] = None
    entities_used: Optional[list[str]] = None


class UploadBookResponse(BaseModel):
    """Response returned after a successful book upload."""

    canonical_book_id: str
    canonical_series_id: str
    title: str
    chapter_count: int
    knowledge_already_extracted: bool = False


class ExtractBookResponse(BaseModel):
    """Response returned after knowledge extraction completes."""

    series_id: str
    book_index: int
    characters_found: int
    summaries_generated: int
    relationships_found: int


# ---------------------------------------------------------------------------
# App lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Initialise shared resources at startup."""
    app.state.vector_store = SupabaseVectorStore(
        url=settings.supabase_url,
        key=settings.supabase_key,
    )
    app.state.llm_client = create_llm_client()
    # Track which books are currently being extracted to prevent duplicates.
    app.state.extracting_books = set()
    # Warm up the embedding model so the first upload isn't slow
    get_embedder()
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
        "enable_extraction": settings.enable_extraction,
        "enable_graph": settings.enable_graph,
    }


@app.get("/library", response_model=Library)
async def get_library(user_id: str = Depends(get_current_user)) -> Library:
    """Return the full library state for the current user."""
    return await load_library(user_id)


@app.get("/books/search", response_model=list[OLBookResult])
async def search_books_endpoint(q: str) -> list[OLBookResult]:
    """Search Open Library for books matching the query.

    Returns up to 10 results with title, author, series, cover URL.
    Used by the frontend upload modal to look up book metadata.
    """
    if not q or len(q.strip()) < 2:
        return []
    return search_books(q.strip(), limit=10)


def _is_book_fully_extracted(kb: KnowledgeBase, book_index: int, total_chapters: int) -> bool:
    """Return True if all chapters of this book_index are already in the KB."""
    extracted = {ref.chapter_index for ref in kb.extracted_chapters if ref.book_index == book_index}
    return len(extracted) >= total_chapters


async def _run_extraction_background(
    canonical_series_id: str,
    canonical_book_id: str,
    book_index: int,
    parsed_chapters: list,
    llm_client: LLMClient,
    extracting_books: set,
) -> None:
    """Background task: extract knowledge for a book after upload."""
    if canonical_book_id in extracting_books:
        logger.info("Extraction already in progress for %s, skipping.", canonical_book_id)
        return
    extracting_books.add(canonical_book_id)
    try:
        logger.info(
            "Background extraction started: %s (series=%s book_index=%d)",
            canonical_book_id, canonical_series_id, book_index,
        )
        await extract_book_knowledge(
            chapters=parsed_chapters,
            canonical_series_id=canonical_series_id,
            book_index=book_index,
            client=llm_client,
            extraction_model=settings.extraction_model,
        )
        logger.info("Background extraction complete: %s", canonical_book_id)
    except Exception:
        logger.error("Background extraction failed: %s", canonical_book_id, exc_info=True)
    finally:
        extracting_books.discard(canonical_book_id)


@app.post("/library/books", response_model=UploadBookResponse)
async def upload_book_canonical(
    request: Request,
    background_tasks: BackgroundTasks,
    canonical_book_id: Annotated[str, Form()],
    title: Annotated[str, Form()],
    canonical_series_id: Annotated[str, Form()],
    ol_id: Annotated[str | None, Form()] = None,
    author: Annotated[str | None, Form()] = None,
    series_name: Annotated[str | None, Form()] = None,
    series_position: Annotated[float | None, Form()] = None,
    cover_url: Annotated[str | None, Form()] = None,
    file: UploadFile = File(...),
    user_id: str = Depends(get_current_user),
) -> UploadBookResponse:
    """Upload an epub and register it against a canonical book."""
    if not file.filename or not file.filename.endswith(".epub"):
        raise HTTPException(status_code=400, detail="File must be an .epub.")

    book_bytes = await file.read()
    client = get_supabase_client()

    # 1. Parse epub to get chapters
    parsed_chapters = parse_epub(BytesIO(book_bytes))
    chapters_for_db = [{"index": c.index, "label": c.label} for c in parsed_chapters]

    # 2. Upsert canonical_books row (idempotent)
    cb = CanonicalBook(
        id=canonical_book_id,
        ol_id=ol_id,
        title=title,
        author=author,
        series_name=series_name,
        series_position=series_position,
        canonical_series_id=canonical_series_id,
        cover_url=cover_url,
        chapters=[Chapter(index=c["index"], label=c["label"]) for c in chapters_for_db],
    )
    upsert_canonical_book(cb)

    # 3. Store epub per-user
    epub_path = f"{user_id}/{canonical_book_id}/book.epub"
    try:
        client.storage.from_("books").upload(
            path=epub_path, file=book_bytes,
            file_options={"content-type": "application/epub+zip"}
        )
    except Exception as e:
        logger.warning("Failed to upload epub to Supabase: %s", e)

    # 4. Compute book_index matching the sort order used by _group_into_series.
    # Include ALL existing books (not just those with a series_position) so that
    # multiple position-less books don't collide at index 0.
    series = await get_series_by_canonical_id(canonical_series_id, user_id)
    new_sort_key = series_position if series_position is not None else float("inf")
    if series and series.books:
        other_books = [
            (b.series_position if b.series_position is not None else float("inf"), b.canonical_book_id)
            for b in series.books
            if b.canonical_book_id != canonical_book_id
        ]
        all_books_sorted = sorted(other_books + [(new_sort_key, canonical_book_id)], key=lambda x: x[0])
        book_index = next(i for i, (_, bid) in enumerate(all_books_sorted) if bid == canonical_book_id)
    else:
        book_index = 0

    # 5. Index vectors (per-user)
    vector_store: SupabaseVectorStore = request.app.state.vector_store
    all_chunks = []
    for chapter in parsed_chapters:
        all_chunks.extend(chunk_chapter(chapter, settings.chunk_size, settings.chunk_overlap))
    index_book(all_chunks, canonical_series_id, book_index, vector_store, user_id)

    # 6. Extract and save cover
    has_cover = False
    try:
        cover_result = extract_cover(book_bytes) or fetch_cover_open_library(title, book_bytes)
        if cover_result is not None:
            cover_bytes, _ = cover_result
            cover_path = f"{user_id}/{canonical_book_id}/cover.jpg"
            client.storage.from_("covers").upload(
                path=cover_path, file=cover_bytes,
                file_options={"content-type": "image/jpeg"}
            )
            has_cover = True
    except Exception:
        logger.warning("Cover extraction failed; continuing", exc_info=True)

    # 7. Upsert user_books row
    ub = UserBook(
        canonical_book_id=canonical_book_id,
        user_id=user_id,
        status=BookStatus.NOT_STARTED,
        epub_path=epub_path,
        has_cover=has_cover,
    )
    upsert_user_book(ub)
    if has_cover:
        await set_user_book_cover(canonical_book_id, user_id, True)

    # 8. Trigger extraction only if enabled and knowledge doesn't already exist
    knowledge_already_extracted = False
    if settings.enable_extraction:
        kb = await load_knowledge(canonical_series_id)
        knowledge_already_extracted = _is_book_fully_extracted(kb, book_index, len(parsed_chapters))
        if not knowledge_already_extracted:
            background_tasks.add_task(
                _run_extraction_background,
                canonical_series_id,
                canonical_book_id,
                book_index,
                parsed_chapters,
                request.app.state.llm_client,
                request.app.state.extracting_books,
            )

    return UploadBookResponse(
        canonical_book_id=canonical_book_id,
        canonical_series_id=canonical_series_id,
        title=title,
        chapter_count=len(parsed_chapters),
        knowledge_already_extracted=knowledge_already_extracted,
    )


@app.get("/library/series/{series_id}/books/{book_index}/cover")
async def get_book_cover(
    series_id: str, book_index: int, user_id: str = Depends(get_current_user)
) -> RedirectResponse:
    """Redirect to the book cover image in Supabase Storage."""
    path = f"{user_id}/{series_id}/cover_{book_index}.jpg"
    url = get_supabase_client().storage.from_("covers").get_public_url(path)
    return RedirectResponse(url)


async def _get_canonical_series_id_for_book(canonical_book_id: str) -> str:
    """Look up the canonical_series_id for a given canonical_book_id."""
    client = get_supabase_client()
    resp = (
        client.table("canonical_books")
        .select("canonical_series_id")
        .filter("id", "eq", canonical_book_id)
        .execute()
    )
    if resp.data:
        return resp.data[0]["canonical_series_id"]
    return canonical_book_id


@app.delete("/library/series/{canonical_series_id}", response_model=Library)
async def delete_series_endpoint(
    canonical_series_id: str,
    request: Request,
    user_id: str = Depends(get_current_user),
) -> Library:
    """Delete all of a user's books in a series."""
    series = await get_series_by_canonical_id(canonical_series_id, user_id)
    if series is None:
        raise HTTPException(status_code=404, detail=f"Series '{canonical_series_id}' not found.")

    vector_store: SupabaseVectorStore = request.app.state.vector_store
    client = get_supabase_client()

    for book in series.books:
        cid = book.canonical_book_id
        vector_store.delete_book(canonical_series_id, book.index, user_id)
        try:
            client.storage.from_("books").remove([f"{user_id}/{cid}/book.epub"])
            client.storage.from_("covers").remove([f"{user_id}/{cid}/cover.jpg"])
        except Exception as e:
            logger.warning("Storage cleanup failed: %s", e)

    if not await other_users_have_series(canonical_series_id, user_id):
        await delete_series_knowledge(canonical_series_id)

    await remove_user_series(canonical_series_id, user_id)
    return await load_library(user_id)


@app.delete("/library/books/{canonical_book_id}", response_model=Library)
async def delete_book_endpoint(
    canonical_book_id: str,
    request: Request,
    user_id: str = Depends(get_current_user),
) -> Library:
    """Remove a book from the user's library."""
    book = await get_book_by_canonical_id(canonical_book_id, user_id)
    if book is None:
        raise HTTPException(status_code=404, detail=f"Book '{canonical_book_id}' not found.")

    canonical_series_id = await _get_canonical_series_id_for_book(canonical_book_id)
    book_index = book.index

    vector_store: SupabaseVectorStore = request.app.state.vector_store
    vector_store.delete_book(canonical_series_id, book_index, user_id)

    client = get_supabase_client()
    try:
        client.storage.from_("books").remove([f"{user_id}/{canonical_book_id}/book.epub"])
        client.storage.from_("covers").remove([f"{user_id}/{canonical_book_id}/cover.jpg"])
    except Exception as e:
        logger.warning("Storage cleanup failed: %s", e)

    if not await other_users_have_book(canonical_book_id, user_id):
        await delete_book_knowledge(canonical_series_id, book_index)

    await remove_user_book(canonical_book_id, user_id)
    return await load_library(user_id)


@app.patch("/library/books/{canonical_book_id}", response_model=Library)
async def update_book_status_endpoint(
    canonical_book_id: str,
    body: UpdateBookStatusRequest,
    user_id: str = Depends(get_current_user),
) -> Library:
    """Update a book's reading status and optionally its series metadata."""
    if not _is_admin(user_id):
        book = await get_book_by_canonical_id(canonical_book_id, user_id)
        if book is None:
            raise HTTPException(status_code=404, detail=f"Book '{canonical_book_id}' not found.")
    else:
        client = get_supabase_client()
        resp = client.table("canonical_books").select("id").eq("id", canonical_book_id).execute()
        if not resp.data:
            raise HTTPException(status_code=404, detail=f"Book '{canonical_book_id}' not found.")

    await update_user_book_status(canonical_book_id, body.status, body.current_chapter_index, user_id)

    if body.series_name is not None or body.series_position is not None:
        update_canonical_book_series(canonical_book_id, body.series_name, body.series_position)

    return await load_library(user_id)


@app.post("/library/books/{canonical_book_id}/extract")
async def extract_book_endpoint(
    canonical_book_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    user_id: str = Depends(get_current_user),
):
    """Trigger knowledge extraction for a book (manual re-trigger)."""
    if not settings.enable_extraction:
        raise HTTPException(status_code=404, detail="Extraction feature is disabled.")
    book = await get_book_by_canonical_id(canonical_book_id, user_id)
    if book is None:
        raise HTTPException(status_code=404, detail=f"Book '{canonical_book_id}' not found.")

    canonical_series_id = await _get_canonical_series_id_for_book(canonical_book_id)

    epub_path = f"{user_id}/{canonical_book_id}/book.epub"
    try:
        book_data = get_supabase_client().storage.from_("books").download(epub_path)
    except Exception:
        raise HTTPException(status_code=404, detail="Epub not found in storage.")

    parsed_chapters = parse_epub(BytesIO(book_data))

    if canonical_book_id in request.app.state.extracting_books:
        return {"message": "Extraction already in progress"}

    background_tasks.add_task(
        _run_extraction_background,
        canonical_series_id,
        canonical_book_id,
        book.index,
        parsed_chapters,
        request.app.state.llm_client,
        request.app.state.extracting_books,
    )
    return {"message": "Extraction started"}


@app.get("/library/series/{canonical_series_id}/knowledge", response_model=KnowledgeBase)
async def get_knowledge_endpoint(
    canonical_series_id: str, user_id: str = Depends(get_current_user)
) -> KnowledgeBase:
    """Return filtered knowledge base from Supabase for the current user."""
    if not settings.enable_extraction:
        raise HTTPException(status_code=404, detail="Extraction feature is disabled.")
    series = await get_series_by_canonical_id(canonical_series_id, user_id)
    if series is None:
        raise HTTPException(status_code=404, detail=f"Series '{canonical_series_id}' not found.")
    kb = await load_knowledge(canonical_series_id)
    return filter_to_progress(kb, series)


def _get_reading_ceiling(series: "Series") -> tuple[int, int] | None:
    """Return (book_index, chapter_index) ceiling for the series reading position."""
    ceiling: tuple[int, int] | None = None
    for book in series.books:
        if book.status == BookStatus.NOT_STARTED:
            continue
        if book.status == BookStatus.COMPLETED:
            last_chapter = max((c.index for c in book.chapters), default=0)
            candidate = (book.index, last_chapter)
        else:  # READING
            ch = book.current_chapter_index if book.current_chapter_index is not None else 0
            candidate = (book.index, ch)
        if ceiling is None or candidate > ceiling:
            ceiling = candidate
    return ceiling


@app.get("/library/series/{series_id}/knowledge-summary")
async def get_knowledge_summary_endpoint(
    series_id: str, user_id: str = Depends(get_current_user)
) -> dict:
    """Return extraction progress per book: how many chapters have been extracted vs total.

    Used by the frontend to show the extraction badge on book covers without
    loading the full knowledge base.
    """
    if not settings.enable_extraction:
        raise HTTPException(status_code=404, detail="Extraction feature is disabled.")
    series = await get_series_by_canonical_id(series_id, user_id)
    if series is None:
        raise HTTPException(status_code=404, detail=f"Series '{series_id}' not found.")

    kb = await load_knowledge(series_id)

    # Count extracted chapters per book_index.
    extracted_per_book: dict[int, int] = {}
    for ref in kb.extracted_chapters:
        extracted_per_book[ref.book_index] = extracted_per_book.get(ref.book_index, 0) + 1

    books_summary = [
        {
            "index": book.index,
            "extracted": extracted_per_book.get(book.index, 0),
            "total": len(book.chapters),
        }
        for book in series.books
    ]
    return {"books": books_summary}


@app.get("/library/series/{series_id}/graph")
async def get_graph_endpoint(
    series_id: str,
    from_book: int = 0,
    from_chapter: int = 0,
    to_book: int = 0,
    to_chapter: int = 0,
    user_id: str = Depends(get_current_user),
) -> dict:
    """Return graph-ready nodes, edges, and scrubber markers for the Reading Compass.

    The window (from_book/from_chapter → to_book/to_chapter) is capped at the
    user's actual reading position to enforce spoiler safety.
    """
    if not settings.enable_graph:
        raise HTTPException(status_code=404, detail="Graph feature is disabled.")
    series = await get_series_by_canonical_id(series_id, user_id)
    if series is None:
        raise HTTPException(status_code=404, detail=f"Series '{series_id}' not found.")

    ceiling = _get_reading_ceiling(series)
    if ceiling is None:
        return {"nodes": [], "edges": [], "scrubber_markers": []}

    # Cap the requested window at the reading ceiling.
    to_book = min(to_book, ceiling[0])
    if to_book == ceiling[0]:
        to_chapter = min(to_chapter, ceiling[1])

    raw_kb = await load_knowledge(series_id)
    kb = filter_to_progress(raw_kb, series)

    return build_graph_payload(kb, from_book, from_chapter, to_book, to_chapter)


@app.get("/library/series/{series_id}/graph/digest")
async def get_graph_digest_endpoint(
    series_id: str,
    request: Request,
    from_book: int = 0,
    from_chapter: int = 0,
    to_book: int = 0,
    to_chapter: int = 0,
    user_id: str = Depends(get_current_user),
) -> dict:
    """Generate a narrative story digest for the given reading window.

    This endpoint makes a Claude API call; call it in parallel with /graph
    so the graph renders immediately while the digest loads.
    """
    if not settings.enable_graph:
        raise HTTPException(status_code=404, detail="Graph feature is disabled.")
    series = await get_series_by_canonical_id(series_id, user_id)
    if series is None:
        raise HTTPException(status_code=404, detail=f"Series '{series_id}' not found.")

    ceiling = _get_reading_ceiling(series)
    if ceiling is None:
        return {"digest": "No reading progress found."}

    # Cap to reading ceiling.
    to_book = min(to_book, ceiling[0])
    if to_book == ceiling[0]:
        to_chapter = min(to_chapter, ceiling[1])

    raw_kb = await load_knowledge(series_id)
    kb = filter_to_progress(raw_kb, series)

    llm_client: LLMClient = request.app.state.llm_client
    digest = await generate_digest(
        kb, from_book, from_chapter, to_book, to_chapter,
        client=llm_client,
        model=settings.llm_model,
    )
    return {"digest": digest}


@app.post("/query/prompts", response_model=ProactivePromptResponse)
async def generate_proactive_prompt_endpoint(
    body: ProactivePromptRequest,
    request: Request,
    user_id: str = Depends(get_current_user),
) -> ProactivePromptResponse:
    """Generate a proactive check-in question."""
    series = await get_series_by_canonical_id(body.series_id, user_id)
    if series is None:
        raise HTTPException(status_code=404, detail="Series not found")

    vector_store: SupabaseVectorStore = request.app.state.vector_store
    chunks = vector_store.fetch_chapter_chunks(
        series_id=body.series_id,
        book_index=body.book_index,
        chapter_index=body.chapter_index,
        user_id=user_id,
        limit=5,
    )

    if not chunks:
        return ProactivePromptResponse(question="What did you think of the chapter you just finished?")

    chapter_label = chunks[0].chapter_label
    context_text = "\n\n".join(c.text for c in chunks)

    prompt = (
        f"You are a reading companion. The user just finished reading {chapter_label}.\n"
        f"Here is a summary of the events in this chapter:\n{context_text}\n\n"
        "Generate a short, engaging 1-sentence question asking the reader for their thoughts or theories on what just happened. "
        "Make it sound natural, conversational, and tailored to the events. Do not answer the question."
    )

    llm_client: LLMClient = request.app.state.llm_client
    answer = await llm_client.generate(
        messages=[{"role": "user", "content": prompt}],
        max_tokens=150,
    )
    return ProactivePromptResponse(question=answer)


@app.post("/query", response_model=QueryResponse)
async def query_endpoint(
    body: QueryRequest,
    request: Request,
    user_id: str = Depends(get_current_user),
) -> QueryResponse:
    """Ask a spoiler-safe question about a series."""
    series = await get_series_by_canonical_id(body.series_id, user_id)
    if series is None:
        raise HTTPException(status_code=404, detail=f"Series '{body.series_id}' not found.")

    # 1. Load knowledge base filtered to reading progress.
    raw_kb = await load_knowledge(body.series_id)
    kb = filter_to_progress(raw_kb, series)
    kb_populated = bool(kb.characters or kb.summaries)

    # 2. Classify the question.
    question_type = classify_question(body.question)

    # 3. Extract entity mentions using the alias registry.
    entity_mentions = extract_entity_mentions(body.question, kb.alias_registry)

    # 4. Build entity context when the KB has data.
    entity_context: Optional[str] = None
    if kb_populated:
        ctx = build_entity_context(question_type, entity_mentions, kb)
        entity_context = ctx if ctx else None

    # 5. Decide whether to run RAG retrieval.
    skip_rag = kb_populated and entity_context and question_type in _KB_ONLY_QUESTION_TYPES

    chunks = []
    vector_store: SupabaseVectorStore = request.app.state.vector_store
    if question_type == QuestionType.RECAP:
        # For recap questions, try to resolve a specific chapter reference and
        # fetch its chunks directly — semantic search is unreliable for "recap
        # of chapter N" because the query text has no content to match against.
        chapter_ref = _resolve_chapter_reference(body.question, series)
        if chapter_ref is not None:
            book_idx, chapter_idx = chapter_ref
            chunks = vector_store.fetch_chapter_chunks(
                series_id=body.series_id,
                book_index=book_idx,
                chapter_index=chapter_idx,
                user_id=user_id,
                limit=30,
            )
        else:
            # General recap ("what happened so far") — fetch the opening chunks
            # from every in-scope chapter so we have full chronological coverage.
            # Semantic search is useless here: "what happened so far" has no
            # content to match against specific passages.
            chunks = []
            for book_idx, chapter_idx in _get_chapters_in_scope(series):
                chapter_chunks = vector_store.fetch_by_positions(
                    series_id=body.series_id,
                    book_index=book_idx,
                    chapter_index=chapter_idx,
                    user_id=user_id,
                    positions=[0, 1, 2],
                )
                chunks.extend(chapter_chunks)
    elif not skip_rag:
        chunks = retrieve_chunks(body.question, series, vector_store, user_id, body.top_k)

    if not chunks and not entity_context:
        return QueryResponse(
            answer="I don't have access to that information based on your current reading progress.",
            sources=[],
            question_type=question_type.value,
            entities_used=entity_mentions or None,
        )

    # 6. Build the prompt.
    prompt = build_prompt(
        body.question,
        chunks,
        series,
        entity_context=entity_context,
        question_type=question_type,
        mode=body.mode,
    )

    history = body.conversation_history[-6:] if body.conversation_history else []

    llm_client: LLMClient = request.app.state.llm_client
    answer = await llm_client.generate(
        messages=[
            *history,
            {"role": "user", "content": prompt},
        ],
        max_tokens=1024,
    )

    sources = [
        SourceChunk(
            book_index=chunk.book_index,
            chapter_label=chunk.chapter_label,
            score=round(chunk.score, 3),
        )
        for chunk in chunks
    ]
    return QueryResponse(
        answer=answer,
        sources=sources,
        question_type=question_type.value,
        entities_used=entity_mentions if entity_mentions else None,
    )
