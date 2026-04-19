"""BookLens FastAPI application."""

import logging
import shutil
from contextlib import asynccontextmanager
from typing import Annotated, AsyncGenerator, Optional

import anthropic
from fastapi import FastAPI, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from src.config import settings
from src.ingestion.chunker import chunk_chapter
from src.ingestion.embedder import get_embedder
from src.ingestion.cover_extractor import extract_cover, fetch_cover_open_library
from src.ingestion.epub_parser import parse_epub
from src.ingestion.indexer import index_book
from src.knowledge.models import KnowledgeBase
from src.knowledge.pipeline import extract_book_knowledge
from src.knowledge.store import (
    delete_book_knowledge,
    delete_series_knowledge,
    filter_to_progress,
    load_knowledge,
)
from src.library.manager import (
    create_series,
    get_series,
    load_library,
    remove_book,
    remove_series,
    save_library,
    update_book_status,
    upsert_book,
)
from src.models import Book, BookStatus, Chapter, Library
from src.query.classifier import classify_question, extract_entity_mentions
from src.query.context_builder import build_entity_context
from src.query.prompt_builder import QuestionType, build_prompt
from src.query.retriever import retrieve_chunks
from src.vector_store.qdrant_store import QdrantVectorStore

logger = logging.getLogger(__name__)


def _parse_chunk_position(chunk_id: str) -> Optional[int]:
    """Parse the chunk position from a chunk_id string.

    Chunk IDs follow the format "chapter_{chapter_index}_chunk_{position}",
    e.g. "chapter_3_chunk_2" → position 2.

    Args:
        chunk_id: Chunk identifier from ChunkRecord / SearchResult.

    Returns:
        0-based position integer, or None if the format is unexpected.
    """
    parts = chunk_id.split("_")
    # Expected: ['chapter', '<ch_idx>', 'chunk', '<position>']
    if len(parts) == 4 and parts[0] == "chapter" and parts[2] == "chunk":
        try:
            return int(parts[3])
        except ValueError:
            pass
    return None


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


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
    app.state.vector_store = QdrantVectorStore(
        url=str(settings.qdrant_url),
        api_key=settings.qdrant_api_key,
    )
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


@app.get("/library", response_model=Library)
def get_library() -> Library:
    """Return the full library state."""
    return load_library()


@app.post("/library/series", response_model=Library, status_code=201)
def add_series(body: CreateSeriesRequest) -> Library:
    """Create a new series.

    Returns:
        Updated library state.

    Raises:
        409: If a series with the given id already exists.
    """
    library = load_library()
    try:
        updated = create_series(library, body.id, body.name)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    save_library(updated)
    return updated


@app.post("/library/series/{series_id}/books", response_model=UploadBookResponse)
async def upload_book(
    series_id: str,
    request: Request,
    title: Annotated[str, Form()],
    book_index: Annotated[int, Form()],
    file: UploadFile,
) -> UploadBookResponse:
    """Upload an epub and run the full ingestion pipeline.

    Saves the file, parses chapters, chunks text, indexes vectors, and updates
    library.json. Re-uploading the same book_index replaces it cleanly.

    Args:
        series_id: Series to add the book to (must already exist).
        title: Human-readable book title.
        book_index: 0-based position of the book within the series.
        file: The epub file to upload.

    Returns:
        Summary of what was indexed.

    Raises:
        404: If the series does not exist.
        400: If the uploaded file is not an epub.
    """
    library = load_library()
    if get_series(library, series_id) is None:
        raise HTTPException(status_code=404, detail=f"Series '{series_id}' not found.")

    if not file.filename or not file.filename.endswith(".epub"):
        raise HTTPException(status_code=400, detail="File must be an .epub.")

    # Save uploaded file
    save_dir = settings.upload_dir / series_id
    save_dir.mkdir(parents=True, exist_ok=True)
    epub_path = save_dir / f"book_{book_index}.epub"
    epub_path.write_bytes(await file.read())

    # Parse → chunk
    parsed_chapters = parse_epub(epub_path)
    all_chunks = []
    for chapter in parsed_chapters:
        all_chunks.extend(chunk_chapter(chapter, settings.chunk_size, settings.chunk_overlap))

    # Index into vector store
    vector_store: QdrantVectorStore = request.app.state.vector_store
    chunks_indexed = index_book(all_chunks, series_id, book_index, vector_store)

    # Extract and save cover image (best-effort — failure does not abort upload)
    has_cover = False
    try:
        cover_result = extract_cover(epub_path) or fetch_cover_open_library(title, epub_path)
        if cover_result is not None:
            cover_bytes, cover_ext = cover_result
            cover_file = save_dir / f"cover_{book_index}{cover_ext}"
            cover_file.write_bytes(cover_bytes)
            has_cover = True
    except Exception:
        logger.warning(
            "Cover extraction failed for %s book %d; continuing without cover",
            series_id,
            book_index,
            exc_info=True,
        )

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

    return UploadBookResponse(
        series_id=series_id,
        book_index=book_index,
        title=title,
        chapter_count=len(chapters),
        chunks_indexed=chunks_indexed,
    )


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


@app.delete("/library/series/{series_id}", response_model=Library)
def delete_series(series_id: str, request: Request) -> Library:
    """Delete a series, all its books, their vectors, and uploaded epub files.

    Args:
        series_id: Series to delete.

    Returns:
        Updated library state.

    Raises:
        404: If the series does not exist.
    """
    library = load_library()
    if get_series(library, series_id) is None:
        raise HTTPException(status_code=404, detail=f"Series '{series_id}' not found.")

    # Delete Qdrant collection (contains all books in the series)
    vector_store: QdrantVectorStore = request.app.state.vector_store
    existing = {c.name for c in vector_store._client.get_collections().collections}
    if series_id in existing:
        vector_store._client.delete_collection(series_id)

    # Delete uploaded epub files
    series_upload_dir = settings.upload_dir / series_id
    if series_upload_dir.exists():
        shutil.rmtree(series_upload_dir)

    # Delete knowledge base
    delete_series_knowledge(series_id)

    updated = remove_series(library, series_id)
    save_library(updated)
    return updated


@app.delete("/library/series/{series_id}/books/{book_index}", response_model=Library)
def delete_book(series_id: str, book_index: int, request: Request) -> Library:
    """Delete a single book, its vectors, and its uploaded epub file.

    Args:
        series_id: Series containing the book.
        book_index: 0-based index of the book to delete.

    Returns:
        Updated library state.

    Raises:
        404: If the series or book does not exist.
    """
    library = load_library()
    try:
        updated = remove_book(library, series_id, book_index)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    # Delete vectors for this book
    vector_store: QdrantVectorStore = request.app.state.vector_store
    vector_store.delete_book(series_id, book_index)

    # Delete uploaded epub file
    epub_path = settings.upload_dir / series_id / f"book_{book_index}.epub"
    if epub_path.exists():
        epub_path.unlink()

    # Remove this book's entries from the knowledge base
    delete_book_knowledge(series_id, book_index)

    save_library(updated)
    return updated


@app.patch("/library/series/{series_id}/books/{book_index}/status", response_model=Library)
def patch_book_status(series_id: str, book_index: int, body: UpdateBookStatusRequest) -> Library:
    """Update a book's reading status and current chapter.

    Args:
        series_id: Series containing the book.
        book_index: 0-based book index to update.
        body: New status and optional current chapter index.

    Returns:
        Updated library state.

    Raises:
        404: If the series or book does not exist.
    """
    library = load_library()
    try:
        updated = update_book_status(
            library,
            series_id,
            book_index,
            body.status,
            body.current_chapter_index,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    save_library(updated)
    return updated


@app.post(
    "/library/series/{series_id}/books/{book_index}/extract",
    response_model=ExtractBookResponse,
)
def extract_book(series_id: str, book_index: int) -> ExtractBookResponse:
    """Trigger knowledge extraction for an already-uploaded book.

    Reads the epub from uploads/, parses its chapters, and runs the
    entity extraction pipeline to populate knowledge/{series_id}.json.
    Already-extracted chapters are skipped, making this endpoint idempotent.

    Knowledge extraction is intentionally separate from upload so that:
    - Upload stays fast (vector indexing only, ~30s)
    - Users control when to incur extraction cost (LLM API calls)
    - Re-running after a partial failure skips completed chapters

    Args:
        series_id: Series the book belongs to.
        book_index: 0-based book index to extract.

    Returns:
        Counts of entities found during extraction.

    Raises:
        404: If the series or epub file does not exist.
    """
    library = load_library()
    if get_series(library, series_id) is None:
        raise HTTPException(status_code=404, detail=f"Series '{series_id}' not found.")

    epub_path = settings.upload_dir / series_id / f"book_{book_index}.epub"
    if not epub_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"No epub found for book {book_index} in series '{series_id}'. Upload it first.",
        )

    parsed_chapters = parse_epub(epub_path)
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    logger.info("Starting knowledge extraction: series=%s book=%d", series_id, book_index)
    kb = extract_book_knowledge(
        chapters=parsed_chapters,
        series_id=series_id,
        book_index=book_index,
        client=client,
        extraction_model=settings.extraction_model,
    )
    logger.info(
        "Extraction complete: %d characters, %d summaries, %d relationships",
        len(kb.characters),
        len(kb.summaries),
        len(kb.relationships),
    )

    return ExtractBookResponse(
        series_id=series_id,
        book_index=book_index,
        characters_found=len(kb.characters),
        summaries_generated=len(kb.summaries),
        relationships_found=len(kb.relationships),
    )


@app.get("/library/series/{series_id}/knowledge", response_model=KnowledgeBase)
def get_knowledge(series_id: str) -> KnowledgeBase:
    """Return the knowledge base for a series, filtered to reading progress.

    The returned knowledge contains only entities, summaries, and facts
    within the reader's current progress — spoiler-safe by construction.

    Args:
        series_id: Series to retrieve knowledge for.

    Returns:
        Filtered KnowledgeBase. Empty if extraction has not been run.

    Raises:
        404: If the series does not exist.
    """
    library = load_library()
    series = get_series(library, series_id)
    if series is None:
        raise HTTPException(status_code=404, detail=f"Series '{series_id}' not found.")

    kb = load_knowledge(series_id)
    return filter_to_progress(kb, series)


@app.post("/query", response_model=QueryResponse)
def query(body: QueryRequest, request: Request) -> QueryResponse:
    """Ask a spoiler-safe question about a series.

    Enhanced flow when a knowledge base exists:
      1. Load KB filtered to reading progress
      2. Classify the question type
      3. Extract entity mentions via the alias registry
      4. Build entity context (characters, summaries, relationships)
      5. Retrieve RAG chunks if needed for this question type
      6. Build enriched prompt with conversation history
      7. Claude answers

    Falls back to pure RAG when the KB is empty.

    Args:
        body: series_id, question, optional top_k, optional conversation_history.

    Returns:
        Claude's answer, source chunks, question type, and entities used.

    Raises:
        404: If the series does not exist.
    """
    library = load_library()
    series = get_series(library, body.series_id)
    if series is None:
        raise HTTPException(status_code=404, detail=f"Series '{body.series_id}' not found.")

    # 1. Load knowledge base filtered to reading progress.
    raw_kb = load_knowledge(body.series_id)
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
    # For knowledge-heavy types where the KB is populated, skip RAG —
    # entity context + summaries are sufficient and more accurate.
    _kb_only_types = {QuestionType.CHARACTER, QuestionType.CHARACTER_ARC, QuestionType.RECAP}
    skip_rag = kb_populated and entity_context and question_type in _kb_only_types

    chunks = []
    if not skip_rag:
        vector_store: QdrantVectorStore = request.app.state.vector_store
        raw_chunks = retrieve_chunks(body.question, series, vector_store, body.top_k)

        # Neighbor expansion: include chunks at position ±1 in the same chapter
        # to improve local narrative coherence (the adjacent passage often has
        # the critical context around a relevant chunk).
        seen_keys: set[tuple[int, int, str]] = {
            (c.book_index, c.chapter_index, c.chunk_id) for c in raw_chunks
        }
        expanded = list(raw_chunks)
        for chunk in raw_chunks:
            position = _parse_chunk_position(chunk.chunk_id)
            if position is None:
                continue
            neighbor_positions = [p for p in (position - 1, position + 1) if p >= 0]
            neighbors = vector_store.fetch_by_positions(
                series_id=series.id,
                book_index=chunk.book_index,
                chapter_index=chunk.chapter_index,
                positions=neighbor_positions,
            )
            for nr in neighbors:
                key = (nr.book_index, nr.chapter_index, nr.chunk_id)
                if key not in seen_keys:
                    seen_keys.add(key)
                    expanded.append(nr)
        chunks = expanded

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
    )

    # Conversation history: cap at 6 turns (3 exchanges) to bound token usage.
    history = body.conversation_history[-6:] if body.conversation_history else []

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    message = client.messages.create(
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
