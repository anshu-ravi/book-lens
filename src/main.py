"""BookLens FastAPI application."""

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
from src.ingestion.epub_parser import parse_epub
from src.ingestion.indexer import index_book
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
from src.query.prompt_builder import build_prompt
from src.query.retriever import retrieve_chunks
from src.vector_store.qdrant_store import QdrantVectorStore


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
    top_k: int = 5


class SourceChunk(BaseModel):
    """A single source chunk returned alongside a query answer."""

    book_index: int
    chapter_label: str
    score: float


class QueryResponse(BaseModel):
    """Response returned from the query endpoint."""

    answer: str
    sources: list[SourceChunk]


class UploadBookResponse(BaseModel):
    """Response returned after a successful book upload."""

    series_id: str
    book_index: int
    title: str
    chapter_count: int
    chunks_indexed: int


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

    # Update library state
    chapters = [Chapter(index=c.index, label=c.label) for c in parsed_chapters]
    book = Book(
        index=book_index,
        title=title,
        status=BookStatus.NOT_STARTED,
        chapters=chapters,
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


@app.post("/query", response_model=QueryResponse)
def query(body: QueryRequest, request: Request) -> QueryResponse:
    """Ask a spoiler-safe question about a series.

    Retrieves relevant chunks filtered to the user's reading progress,
    builds a prompt, and returns Claude's answer with source attribution.

    Args:
        body: series_id, question, and optional top_k.

    Returns:
        Claude's answer and the source chunks it was based on.

    Raises:
        404: If the series does not exist.
    """
    library = load_library()
    series = get_series(library, body.series_id)
    if series is None:
        raise HTTPException(status_code=404, detail=f"Series '{body.series_id}' not found.")

    vector_store: QdrantVectorStore = request.app.state.vector_store
    chunks = retrieve_chunks(body.question, series, vector_store, body.top_k)

    if not chunks:
        return QueryResponse(
            answer="I don't have access to that information based on your current reading progress.",
            sources=[],
        )

    prompt = build_prompt(body.question, chunks, series)
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    message = client.messages.create(
        model=settings.llm_model,
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
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
    return QueryResponse(answer=answer, sources=sources)
