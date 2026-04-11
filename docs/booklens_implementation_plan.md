# BookLens — Full Implementation Plan

## Overview

A single-user, spoiler-safe reading companion web app. Users upload epubs, organize them into series or as standalones, track their reading progress by chapter, and ask natural language questions. The system answers using only content from chapters the user has already read.

---

## Tech Stack

| Layer | Choice | Reason |
|---|---|---|
| Backend | FastAPI (Python) | Async, lightweight, easy file handling |
| Epub parsing | `ebooklib` + `beautifulsoup4` | Standard epub parsing combo |
| Embeddings | `sentence-transformers` (`all-MiniLM-L6-v2`) | Free, runs on CPU, good quality |
| Vector DB | Qdrant Cloud free tier | Metadata filtering, free, managed |
| LLM | Claude API (`claude-haiku-4-5`) | Cheapest Claude model, swap to sonnet if needed |
| Frontend | Vanilla HTML/CSS/JS (single file, served by FastAPI) | No build step, mobile-friendly |
| State | JSON file on disk (`library.json`) | No database needed for single user |
| Hosting | Render.com free tier | Auto-deploy from GitHub |

---

## Project Structure

```
booklens/
├── main.py                  # FastAPI app entry point
├── config.py                # Env vars and constants
├── library.json             # Persisted library state (auto-created)
│
├── ingestion/
│   ├── __init__.py
│   ├── epub_parser.py       # epub → structured chapters
│   ├── chunker.py           # chapters → overlapping text chunks
│   └── indexer.py           # chunks → embeddings → Qdrant
│
├── query/
│   ├── __init__.py
│   ├── retriever.py         # semantic search with chapter filter
│   └── prompt_builder.py   # builds spoiler-safe Claude prompt
│
├── library/
│   ├── __init__.py
│   └── manager.py           # CRUD for series, books, progress
│
├── static/
│   └── index.html           # Entire frontend (single file)
│
├── requirements.txt
├── .env.example
└── render.yaml              # Render deployment config
```

---

## Environment Variables

```
# .env
ANTHROPIC_API_KEY=your_key_here
QDRANT_URL=your_qdrant_cloud_url
QDRANT_API_KEY=your_qdrant_api_key
LIBRARY_PATH=./library.json
UPLOAD_DIR=./uploads
```

---

## Data Models

Define these as Pydantic models used across the app.

```python
# In library/manager.py

class BookStatus(str, Enum):
    NOT_STARTED = "not_started"
    READING = "reading"
    COMPLETED = "completed"

class Chapter(BaseModel):
    index: int               # 0-based integer, used internally for filtering
    label: str               # Human-readable: "Chapter 4", "Prologue", "Part II - Interlude"

class Book(BaseModel):
    index: int               # 0-based position within its series
    title: str
    status: BookStatus
    chapters: List[Chapter]  # Ordered list populated at ingestion time
    current_chapter_index: Optional[int] = None  # Index into chapters list

class Series(BaseModel):
    id: str                  # slug, e.g. "mistborn", "name-of-the-wind"
    name: str                # Display name
    books: List[Book]        # Ordered by index

class Library(BaseModel):
    series: List[Series]
```

---

## Feature 1 — Epub Ingestion Pipeline

### 1.1 Epub Parser (`ingestion/epub_parser.py`)

**Goal:** Given an epub file path, return an ordered list of chapters, each with a label and full text.

```python
def parse_epub(filepath: str) -> List[ParsedChapter]:
    """
    Returns list of ParsedChapter(index, label, text) in reading order.
    """
```

**Implementation steps:**

1. Open epub with `ebooklib.epub.read_epub(filepath)`
2. Get the spine — `book.spine` gives ordered `(item_id, linear)` tuples
3. For each spine item, get the item via `book.get_item_with_id(item_id)`
4. Only process items of type `ebooklib.ITEM_DOCUMENT`
5. Parse HTML content with `BeautifulSoup(item.get_content(), 'html.parser')`
6. Extract a chapter label using this priority order:
   - Look for `<h1>`, `<h2>`, `<h3>` tag text
   - Look for an element with class containing "chapter", "title", "heading"
   - Fall back to: `f"Section {index + 1}"`
7. Extract body text: `soup.get_text(separator=' ', strip=True)`
8. Skip sections with fewer than 100 characters (likely navigation pages, copyright pages, etc.)
9. Assign a monotonically increasing `index` (0-based) to every kept section regardless of label

**Return type:**
```python
@dataclass
class ParsedChapter:
    index: int
    label: str
    text: str
```

**Edge cases to handle:**
- Empty spine items → skip
- Duplicate labels → append index to disambiguate: "Chapter 1 (2)"
- Single-document epubs (all text in one HTML file) → split by `<h1>`/`<h2>` tags instead of spine items

---

### 1.2 Chunker (`ingestion/chunker.py`)

**Goal:** Split each chapter's text into overlapping paragraph-based chunks with metadata.

```python
def chunk_chapter(
    chapter: ParsedChapter,
    series_id: str,
    book_index: int,
    chunk_size: int = 400,      # words
    overlap: int = 50           # words
) -> List[ChunkRecord]:
```

**Implementation steps:**

1. Split chapter text into paragraphs by splitting on `\n\n` or double newlines
2. Group paragraphs greedily until word count reaches `chunk_size`
3. Each chunk overlaps with the previous by `overlap` words (take the last N words of the previous chunk and prepend)
4. Assign each chunk a `chunk_index` (0-based within the chapter)

**Return type:**
```python
@dataclass
class ChunkRecord:
    series_id: str
    book_index: int
    chapter_index: int
    chapter_label: str
    chunk_index: int
    text: str
```

---

### 1.3 Indexer (`ingestion/indexer.py`)

**Goal:** Embed chunks and upsert into Qdrant.

```python
def index_book(
    chunks: List[ChunkRecord],
    series_id: str,
    book_index: int
) -> int:   # returns number of chunks indexed
```

**Implementation steps:**

1. Initialize `SentenceTransformer('all-MiniLM-L6-v2')` — load once at app startup, pass as dependency
2. Create Qdrant collection if it doesn't exist: collection name = `series_id`, vector size = 384 (MiniLM output dim)
3. Before indexing, delete all existing points for this `(series_id, book_index)` combo using a filter — this makes re-indexing safe
4. Batch embed chunks: `model.encode([c.text for c in chunks], batch_size=64)`
5. Build Qdrant `PointStruct` list:
   ```python
   PointStruct(
       id=uuid4().hex,
       vector=embedding.tolist(),
       payload={
           "series_id": c.series_id,
           "book_index": c.book_index,
           "chapter_index": c.chapter_index,
           "chapter_label": c.chapter_label,
           "chunk_index": c.chunk_index,
           "text": c.text
       }
   )
   ```
6. Upsert in batches of 100

**Qdrant collection config:**
```python
VectorsConfig(size=384, distance=Distance.COSINE)
```

---

## Feature 2 — Library Manager (`library/manager.py`)

**Goal:** Read/write `library.json`. All state lives here.

### Functions to implement:

```python
def load_library() -> Library
def save_library(library: Library) -> None

def create_series(library: Library, series_id: str, name: str) -> Series
def get_series(library: Library, series_id: str) -> Series

def add_book_to_series(
    library: Library,
    series_id: str,
    book_index: int,
    title: str,
    chapters: List[Chapter]   # populated from epub parser output
) -> Book

def update_progress(
    library: Library,
    series_id: str,
    book_index: int,
    current_chapter_index: int   # index into book.chapters list
) -> Book

def set_book_completed(library: Library, series_id: str, book_index: int) -> Book

def delete_book(library: Library, series_id: str, book_index: int) -> None
# Also deletes all Qdrant points for this book

def delete_series(library: Library, series_id: str) -> None
# Also deletes the entire Qdrant collection for this series
```

**library.json** is read on every request and written on every mutation. File is small (a few KB), this is fine.

---

## Feature 3 — Query Engine

### 3.1 Retriever (`query/retriever.py`)

```python
def retrieve_chunks(
    question: str,
    series_id: str,
    library: Library,
    top_k: int = 8
) -> List[ChunkRecord]:
```

**Implementation steps:**

1. Embed the question using the same `SentenceTransformer` model
2. Build a compound Qdrant filter from the library state:

```python
def build_qdrant_filter(series: Series) -> Filter:
    should_conditions = []
    for book in series.books:
        if book.status == BookStatus.COMPLETED:
            should_conditions.append(
                FieldCondition(key="book_index", match=MatchValue(value=book.index))
            )
        elif book.status == BookStatus.READING and book.current_chapter_index is not None:
            should_conditions.append(
                Filter(must=[
                    FieldCondition(key="book_index", match=MatchValue(value=book.index)),
                    FieldCondition(key="chapter_index", range=Range(lte=book.current_chapter_index))
                ])
            )
        # NOT_STARTED: excluded (no condition added)
    return Filter(should=should_conditions)
```

3. Query Qdrant:
```python
client.search(
    collection_name=series_id,
    query_vector=question_embedding,
    query_filter=qdrant_filter,
    limit=top_k
)
```

4. Return results as `ChunkRecord` list, sorted by score descending

---

### 3.2 Prompt Builder (`query/prompt_builder.py`)

```python
def build_prompt(
    question: str,
    series: Series,
    chunks: List[ChunkRecord]
) -> str:
```

**Implementation:**

```python
def build_prompt(question, series, chunks):
    progress_lines = []
    for book in series.books:
        if book.status == BookStatus.COMPLETED:
            progress_lines.append(f'- "{book.title}": fully read')
        elif book.status == BookStatus.READING and book.current_chapter_index is not None:
            label = book.chapters[book.current_chapter_index].label
            progress_lines.append(f'- "{book.title}": read up to and including {label}')

    progress_summary = "\n".join(progress_lines) if progress_lines else "- No books marked as read yet."
    context_blocks = "\n\n---\n\n".join([c.text for c in chunks])

    return f"""You are a spoiler-safe reading assistant for "{series.name}".

The user has read the following:
{progress_summary}

Answer the user's question using ONLY the context passages provided below.
Do not use any knowledge from your training data about this series.
If the answer cannot be found in the context, say: "I couldn't find that in what you've read so far."
Never reveal or hint at events beyond what the user has read.

[CONTEXT]
{context_blocks}

[QUESTION]
{question}"""
```

---

## Feature 4 — FastAPI Backend (`main.py`)

### Startup

```python
@app.on_event("startup")
async def startup():
    # Load sentence transformer model once
    app.state.embedder = SentenceTransformer('all-MiniLM-L6-v2')
    # Initialize Qdrant client
    app.state.qdrant = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY)
    # Ensure library.json exists
    if not Path(LIBRARY_PATH).exists():
        save_library(Library(series=[]))
```

### Endpoints

**Library management:**
```
GET    /library                          → full library state
POST   /library/series                   → create series {id, name}
DELETE /library/series/{series_id}       → delete series + vectors

POST   /library/series/{series_id}/books → upload epub + add book
  - multipart/form-data: file (epub), book_index (int), title (str)
  - triggers full ingestion pipeline
  - returns book with parsed chapters list

PATCH  /library/series/{series_id}/books/{book_index}/progress
  → {current_chapter_index: int}

PATCH  /library/series/{series_id}/books/{book_index}/complete
  → marks book as completed

DELETE /library/series/{series_id}/books/{book_index}
  → removes book + its vectors
```

**Query:**
```
POST /query
  body: { series_id: str, question: str }
  returns: { answer: str, chunks_used: int }
```

**Static frontend:**
```
GET / → serve static/index.html
```

### Upload + Ingestion Flow (inside the POST /books endpoint)

```python
async def add_book(series_id, book_index, title, file: UploadFile):
    # 1. Save epub to uploads/
    filepath = f"{UPLOAD_DIR}/{series_id}_{book_index}.epub"
    with open(filepath, "wb") as f:
        f.write(await file.read())

    # 2. Parse epub
    parsed_chapters = parse_epub(filepath)

    # 3. Chunk all chapters
    all_chunks = []
    for chapter in parsed_chapters:
        all_chunks.extend(chunk_chapter(chapter, series_id, book_index))

    # 4. Index into Qdrant
    index_book(all_chunks, series_id, book_index, app.state.embedder, app.state.qdrant)

    # 5. Add to library
    library = load_library()
    chapters = [Chapter(index=c.index, label=c.label) for c in parsed_chapters]
    add_book_to_series(library, series_id, book_index, title, chapters)
    save_library(library)

    return book
```

### Query Flow (inside POST /query endpoint)

```python
async def query(series_id: str, question: str):
    library = load_library()
    series = get_series(library, series_id)

    chunks = retrieve_chunks(question, series_id, series, app.state.embedder, app.state.qdrant)
    prompt = build_prompt(question, series, chunks)

    response = anthropic_client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}]
    )

    return {
        "answer": response.content[0].text,
        "chunks_used": len(chunks)
    }
```

---

## Feature 5 — Frontend (`static/index.html`)

Single HTML file with embedded CSS and JS. Three views rendered in-place (no routing):

### View 1: Library
- List all series with their books
- Each book shows: title, status badge, current chapter (if reading)
- Button per book: "Update Progress" → opens inline chapter selector (dropdown populated from book.chapters)
- Button per series: "Ask a Question" → switches to Ask view
- Button: "Add Book / Series" → switches to Upload view

### View 2: Upload
- Input: Series name (text) + Series ID (auto-slugified from name, editable)
- Dropdown: "Add to existing series" OR "Create new series"
- If adding to existing: dropdown of existing series + book index input
- Input: Book title
- File picker: epub only
- Submit button → POST to `/library/series/{id}/books`
- Show progress bar while uploading/indexing (can take 30–60 seconds for large books)

### View 3: Ask
- Series selector dropdown (pre-selected if coming from Library view)
- Shows current reading state summary beneath selector (e.g. "Book 1: complete · Book 2: Chapter 14")
- Large textarea for question
- Submit button → POST to `/query`
- Answer rendered below in a styled card

### Design direction
- Dark theme, book/library aesthetic — deep navy or near-black background, warm cream/parchment text
- Serif font for headings (e.g. Playfair Display via Google Fonts), clean sans-serif for body
- Minimal animations — subtle fade on view transitions
- Mobile-first: stacked layout, large tap targets, readable at 375px width

---

## Deployment (`render.yaml`)

```yaml
services:
  - type: web
    name: booklens
    env: python
    buildCommand: pip install -r requirements.txt
    startCommand: uvicorn main:app --host 0.0.0.0 --port $PORT
    envVars:
      - key: ANTHROPIC_API_KEY
        sync: false
      - key: QDRANT_URL
        sync: false
      - key: QDRANT_API_KEY
        sync: false
      - key: LIBRARY_PATH
        value: ./library.json
      - key: UPLOAD_DIR
        value: ./uploads
```

Note: Render's free tier has ephemeral storage — `library.json` and uploaded epubs will be wiped on redeploy. For V1 this is acceptable (you can re-upload). For V2, move `library.json` to a small persistent store (Render disk, or a free PlanetScale/Supabase instance).

---

## requirements.txt

```
fastapi
uvicorn[standard]
python-multipart
ebooklib
beautifulsoup4
lxml
sentence-transformers
qdrant-client
anthropic
pydantic
python-dotenv
```

---

## Build Order

1. `ingestion/epub_parser.py` — write + test standalone with a real epub
2. `ingestion/chunker.py` — write + test, verify chunk sizes and overlap
3. `ingestion/indexer.py` — write + test against a real Qdrant collection
4. `library/manager.py` — write + test load/save/CRUD
5. `query/retriever.py` — write + test filtering logic with dummy data
6. `query/prompt_builder.py` — write + verify output for single book, multi-book series, and standalone
7. `main.py` — wire all modules into FastAPI endpoints
8. `static/index.html` — build frontend against working local API
9. `render.yaml` — deploy and verify on mobile

---

## Testing Checklist (manual, per feature)

- [ ] Parser: upload a known epub, verify chapter count and labels are correct
- [ ] Parser: verify prologues/epilogues/interludes are captured and labeled
- [ ] Chunker: verify chunks don't split mid-sentence frequently
- [ ] Indexer: re-uploading same book doesn't create duplicate vectors
- [ ] Library: adding book, updating progress, marking complete all persist correctly
- [ ] Retriever: question about Book 2 content returns no results when only Book 1 is marked reading
- [ ] Retriever: chapter filter correctly excludes future chapters
- [ ] Prompt: verify prompt contains correct progress summary for each status combination
- [ ] Query: ask a question answerable from context — verify correct answer
- [ ] Query: ask a question about future events — verify "couldn't find that" response
- [ ] Frontend: upload flow works end-to-end on mobile
- [ ] Frontend: chapter selector updates and persists correctly
