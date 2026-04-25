"""BookLens FastAPI application."""

import logging
import re
from contextlib import asynccontextmanager
from io import BytesIO
from typing import Annotated, AsyncGenerator, Optional

import anthropic
from fastapi import (BackgroundTasks, Depends, FastAPI, Form, Header,
                     HTTPException, Request, UploadFile)
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

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
from src.library.manager import (create_series, get_series, load_library,
                                 remove_book, remove_series,
                                 update_book_status, upsert_book)
from src.models import Book, BookStatus, Chapter, Library
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
# Request / Response models
# -----------------------------------------------------------------------


class CreateSeriesRequest(BaseModel):
    """Request body for creating a new series."""

    id: str
    name: str


class UpdateBookStatusRequest(BaseModel):
    """Request body for updating a book's reading status."""

    status: BookStatus
    current_chapter_index: Optional[int] = None


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

    series_id: str
    book_index: int
    title: str
    chapter_count: int
    chunks_indexed: int


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
    app.state.anthropic_client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
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
    }


@app.get("/library", response_model=Library)
async def get_library(user_id: str = Depends(get_current_user)) -> Library:
    """Return the full library state for the current user."""
    return await load_library(user_id)


@app.post("/library/series", response_model=Library, status_code=201)
async def add_series(
    body: CreateSeriesRequest, user_id: str = Depends(get_current_user)
) -> Library:
    """Create a new series."""
    try:
        await create_series(body.id, body.name, user_id)
    except Exception as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return await load_library(user_id)


async def _run_extraction_background(
    series_id: str,
    book_index: int,
    user_id: str,
    parsed_chapters: list,
    anthropic_client: anthropic.AsyncAnthropic,
    extracting_books: set,
) -> None:
    """Background task: extract knowledge for a book after upload."""
    key = (series_id, book_index, user_id)
    if key in extracting_books:
        logger.info("Extraction already in progress for %s, skipping.", key)
        return
    
    extracting_books.add(key)
    try:
        logger.info("Background extraction started: series=%s book=%d", series_id, book_index)
        await extract_book_knowledge(
            chapters=parsed_chapters,
            series_id=series_id,
            book_index=book_index,
            user_id=user_id,
            client=anthropic_client,
            extraction_model=settings.extraction_model,
        )
        logger.info("Background extraction complete: series=%s book=%d", series_id, book_index)
    except Exception:
        logger.error("Background extraction failed: series=%s book=%d", series_id, book_index, exc_info=True)
    finally:
        extracting_books.remove(key)


@app.post("/library/series/{series_id}/books", response_model=UploadBookResponse)
async def upload_book(
    series_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    title: Annotated[str, Form()],
    book_index: Annotated[int, Form()],
    file: UploadFile,
    user_id: str = Depends(get_current_user),
) -> UploadBookResponse:
    """Upload an epub and run the full ingestion pipeline using Supabase."""
    if await get_series(series_id, user_id) is None:
        raise HTTPException(status_code=404, detail=f"Series '{series_id}' not found.")

    if not file.filename or not file.filename.endswith(".epub"):
        raise HTTPException(status_code=400, detail="File must be an .epub.")

    book_bytes = await file.read()
    
    # Save book file to Supabase Storage - path: {user_id}/{series_id}/book_{book_index}.epub
    client = get_supabase_client()
    book_path = f"{user_id}/{series_id}/book_{book_index}.epub"
    try:
        client.storage.from_("books").upload(
            path=book_path,
            file=book_bytes,
            file_options={"upsert": "true"}
        )
    except Exception as e:
        logger.warning("Failed to upload epub to Supabase: %s", e)

    # Parse → chunk
    parsed_chapters = parse_epub(BytesIO(book_bytes))
    all_chunks = []
    for chapter in parsed_chapters:
        all_chunks.extend(chunk_chapter(chapter, settings.chunk_size, settings.chunk_overlap))

    # Index into vector store
    vector_store: SupabaseVectorStore = request.app.state.vector_store
    chunks_indexed = index_book(all_chunks, series_id, book_index, vector_store, user_id)

    # Extract and save cover image to Supabase Storage
    has_cover = False
    try:
        cover_result = extract_cover(book_bytes) or fetch_cover_open_library(title, book_bytes)
        if cover_result is not None:
            cover_bytes, _ = cover_result
            cover_path = f"{user_id}/{series_id}/cover_{book_index}.jpg"
            client.storage.from_("covers").upload(
                path=cover_path,
                file=cover_bytes,
                file_options={"contentType": "image/jpeg", "upsert": "true"}
            )
            has_cover = True
    except Exception:
        logger.warning("Cover extraction failed; continuing", exc_info=True)

    # Update library state
    chapters = [Chapter(index=c.index, label=c.label) for c in parsed_chapters]
    book = Book(
        index=book_index,
        title=title,
        status=BookStatus.NOT_STARTED,
        chapters=chapters,
        has_cover=has_cover,
    )
    await upsert_book(series_id, book, user_id)

    # Kick off knowledge extraction in the background.
    background_tasks.add_task(
        _run_extraction_background,
        series_id,
        book_index,
        user_id,
        parsed_chapters,
        request.app.state.anthropic_client,
        request.app.state.extracting_books,
    )

    return UploadBookResponse(
        series_id=series_id,
        book_index=book_index,
        title=title,
        chapter_count=len(chapters),
        chunks_indexed=chunks_indexed,
    )


@app.get("/library/series/{series_id}/books/{book_index}/cover")
async def get_book_cover(
    series_id: str, book_index: int, user_id: str = Depends(get_current_user)
) -> RedirectResponse:
    """Redirect to the book cover image in Supabase Storage."""
    path = f"{user_id}/{series_id}/cover_{book_index}.jpg"
    url = get_supabase_client().storage.from_("covers").get_public_url(path)
    return RedirectResponse(url)


@app.delete("/library/series/{series_id}", response_model=Library)
async def delete_series_endpoint(
    series_id: str, request: Request, user_id: str = Depends(get_current_user)
) -> Library:
    """Delete a series, all its books, vectors, and storage files."""
    if await get_series(series_id, user_id) is None:
        raise HTTPException(status_code=404, detail=f"Series '{series_id}' not found.")

    # Delete Supabase Vectors
    vector_store: SupabaseVectorStore = request.app.state.vector_store
    vector_store.delete_series(series_id, user_id)

    # Delete Supabase Storage files
    client = get_supabase_client()
    try:
        book_files = client.storage.from_("books").list(f"{user_id}/{series_id}")
        if book_files:
            client.storage.from_("books").remove([f"{user_id}/{series_id}/{b['name']}" for b in book_files])
        covers = client.storage.from_("covers").list(f"{user_id}/{series_id}")
        if covers:
            client.storage.from_("covers").remove([f"{user_id}/{series_id}/{c['name']}" for c in covers])
    except Exception as e:
        logger.warning("Storage cleanup failed: %s", e)

    # Delete knowledge base
    await delete_series_knowledge(series_id, user_id)

    # Delete from Postgres
    await remove_series(series_id, user_id)
    
    return await load_library(user_id)


@app.delete("/library/series/{series_id}/books/{book_index}", response_model=Library)
async def delete_book_endpoint(
    series_id: str,
    book_index: int,
    request: Request,
    user_id: str = Depends(get_current_user),
) -> Library:
    """Delete a single book and its associated vectors/storage."""
    if await get_series(series_id, user_id) is None:
        raise HTTPException(status_code=404, detail=f"Series '{series_id}' not found.")

    # Delete Supabase Vectors
    vector_store: SupabaseVectorStore = request.app.state.vector_store
    vector_store.delete_book(series_id, book_index, user_id)

    # Delete Supabase Storage files
    client = get_supabase_client()
    try:
        book_path = f"{user_id}/{series_id}/book_{book_index}.epub"
        client.storage.from_("books").remove([book_path])
        # Covers might have different extensions
        for ext in [".jpg", ".jpeg", ".png", ".webp"]:
            client.storage.from_("covers").remove([f"{user_id}/{series_id}/cover_{book_index}{ext}"])
    except Exception as e:
        logger.warning("Storage cleanup failed: %s", e)

    # Delete knowledge base
    await delete_book_knowledge(series_id, book_index, user_id)

    # Delete from Postgres
    await remove_book(series_id, book_index, user_id)
    
    return await load_library(user_id)


@app.patch("/library/series/{series_id}/books/{book_index}", response_model=Library)
async def update_book_status_endpoint(
    series_id: str,
    book_index: int,
    body: UpdateBookStatusRequest,
    user_id: str = Depends(get_current_user),
) -> Library:
    """Update a book's reading status."""
    if await get_series(series_id, user_id) is None:
        raise HTTPException(status_code=404, detail=f"Series '{series_id}' not found.")

    await update_book_status(
        series_id, book_index, body.status, body.current_chapter_index, user_id
    )
    return await load_library(user_id)


@app.post(
    "/library/series/{series_id}/books/{book_index}/extract",
)
async def extract_book_endpoint(
    series_id: str,
    book_index: int,
    request: Request,
    background_tasks: BackgroundTasks,
    user_id: str = Depends(get_current_user),
):
    """Trigger knowledge extraction for a book in Supabase Storage."""
    series = await get_series(series_id, user_id)
    if series is None:
        raise HTTPException(status_code=404, detail=f"Series '{series_id}' not found.")

    book_path = f"{user_id}/{series_id}/book_{book_index}.epub"
    try:
        book_data = get_supabase_client().storage.from_("books").download(book_path)
    except Exception:
        raise HTTPException(
            status_code=404,
            detail=f"No book file found for book {book_index} in Supabase Storage.",
        )

    parsed_chapters = parse_epub(BytesIO(book_data))

    key = (series_id, book_index, user_id)
    if key in request.app.state.extracting_books:
        return {"message": "Extraction already in progress"}

    logger.info("Enqueuing knowledge extraction: series=%s book=%d", series_id, book_index)
    background_tasks.add_task(
        _run_extraction_background,
        series_id,
        book_index,
        user_id,
        parsed_chapters,
        request.app.state.anthropic_client,
        request.app.state.extracting_books,
    )

    return {"message": "Extraction started"}



@app.get("/library/series/{series_id}/knowledge", response_model=KnowledgeBase)
async def get_knowledge_endpoint(
    series_id: str, user_id: str = Depends(get_current_user)
) -> KnowledgeBase:
    """Return filtered knowledge base from Supabase for the current user."""
    series = await get_series(series_id, user_id)
    if series is None:
        raise HTTPException(status_code=404, detail=f"Series '{series_id}' not found.")

    kb = await load_knowledge(series_id, user_id)
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
    series = await get_series(series_id, user_id)
    if series is None:
        raise HTTPException(status_code=404, detail=f"Series '{series_id}' not found.")

    kb = await load_knowledge(series_id, user_id)

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
    series = await get_series(series_id, user_id)
    if series is None:
        raise HTTPException(status_code=404, detail=f"Series '{series_id}' not found.")

    ceiling = _get_reading_ceiling(series)
    if ceiling is None:
        return {"nodes": [], "edges": [], "scrubber_markers": []}

    # Cap the requested window at the reading ceiling.
    to_book = min(to_book, ceiling[0])
    if to_book == ceiling[0]:
        to_chapter = min(to_chapter, ceiling[1])

    raw_kb = await load_knowledge(series_id, user_id)
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
    series = await get_series(series_id, user_id)
    if series is None:
        raise HTTPException(status_code=404, detail=f"Series '{series_id}' not found.")

    ceiling = _get_reading_ceiling(series)
    if ceiling is None:
        return {"digest": "No reading progress found."}

    # Cap to reading ceiling.
    to_book = min(to_book, ceiling[0])
    if to_book == ceiling[0]:
        to_chapter = min(to_chapter, ceiling[1])

    raw_kb = await load_knowledge(series_id, user_id)
    kb = filter_to_progress(raw_kb, series)

    anthropic_client: anthropic.AsyncAnthropic = request.app.state.anthropic_client
    digest = await generate_digest(
        kb, from_book, from_chapter, to_book, to_chapter,
        client=anthropic_client,
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
    series = await get_series(body.series_id, user_id)
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

    anthropic_client: anthropic.AsyncAnthropic = request.app.state.anthropic_client
    message = await anthropic_client.messages.create(
        model=settings.llm_model,
        max_tokens=150,
        messages=[{"role": "user", "content": prompt}],
    )
    return ProactivePromptResponse(question=message.content[0].text)


@app.post("/query", response_model=QueryResponse)
async def query_endpoint(
    body: QueryRequest,
    request: Request,
    user_id: str = Depends(get_current_user),
) -> QueryResponse:
    """Ask a spoiler-safe question about a series."""
    series = await get_series(body.series_id, user_id)
    if series is None:
        raise HTTPException(status_code=404, detail=f"Series '{body.series_id}' not found.")

    # 1. Load knowledge base filtered to reading progress.
    raw_kb = await load_knowledge(body.series_id, user_id)
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

    anthropic_client: anthropic.AsyncAnthropic = request.app.state.anthropic_client
    message = await anthropic_client.messages.create(
        model=settings.llm_model,
        max_tokens=1024,
        messages=[
            *history,
            {"role": "user", "content": prompt},
        ],
    )
    answer = message.content[0].text

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
