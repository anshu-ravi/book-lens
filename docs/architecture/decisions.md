# Architecture Decision Records

---

## ADR-001: Vector Database — Qdrant Cloud

**Date:** 2026-04-12
**Phase:** 3

### Context
Phase 3 requires a vector database to store chunk embeddings for semantic search. The app needs to be deployable (accessible from mobile), so a cloud-hosted solution is required.

### Options Considered

| Option | Free Tier | Setup | Filtering | Notes |
|--------|-----------|-------|-----------|-------|
| Qdrant Cloud | 1 cluster, 1 GB | Simple | Excellent | Purpose-built, same API local/cloud |
| Pinecone | Serverless, limited | Simple | Good | Restrictive free tier |
| Supabase + pgvector | 500 MB Postgres | Medium | SQL-native | Full-stack but less specialised |
| ChromaDB | N/A (no cloud) | Zero | Good | No managed offering |

### Decision
**Qdrant Cloud** on the free tier.

### Rationale
- Generous free tier (1 GB / ~1M vectors) — enough for a personal reading library
- Identical Python client API for both local (`localhost:6333`) and cloud (URL + API key) — zero code changes between environments
- First-class payload filtering needed for Phase 5 spoiler-safe retrieval (filter by `book_index`, `chapter_index`)
- Purpose-built for vector search; more capable than pgvector for this use case

### Consequences
- If we later need auth, file storage, or a relational DB, Supabase is a natural complement (not a replacement)
- Migrating to pgvector later is low effort due to the `VectorStore` abstraction (see ADR-002)

---

## ADR-002: VectorStore Abstraction Layer

**Date:** 2026-04-12
**Phase:** 3

### Context
We chose Qdrant now, but requirements may change. Without an abstraction, swapping backends touches every call site in the codebase.

### Decision
Introduce a `VectorStore` abstract base class (`src/vector_store/base.py`) with three methods:
- `upsert(chunks, embeddings, series_id, book_index) → int`
- `search(embedding, series_id, filters, top_k) → list[SearchResult]`
- `delete_book(series_id, book_index) → None`

`QdrantVectorStore` in `src/vector_store/qdrant_store.py` implements this interface.

### Rationale
- All application code depends on `VectorStore`, never on `QdrantVectorStore` directly
- Swapping to pgvector (or any other backend) requires only a new implementation file + config change
- The abstraction adds ~30 lines now and saves a painful refactor later

### Consequences
- New backends must implement all three methods
- The `filters` dict in `search()` is currently backend-specific (Qdrant Filter objects passed under key `"qdrant_filter"`); this will be standardised if a second backend is added

---

## ADR-003: Embedding Model — all-MiniLM-L6-v2

**Date:** 2026-04-12
**Phase:** 3

### Context
Chunks need to be embedded for semantic search. Options range from local open-source models to OpenAI's API.

### Decision
**`sentence-transformers/all-MiniLM-L6-v2`** running locally via the `sentence-transformers` library.

### Rationale
- Already a project dependency (pinned in `pyproject.toml`)
- 384-dimensional vectors — small enough for fast search, large enough for good semantics
- Runs entirely locally — no API cost, no rate limits, no latency for batch indexing
- Standard benchmark performer for retrieval tasks
- Model is cached after first download (~90 MB)

### Consequences
- Embedding quality is lower than larger models (e.g. OpenAI `text-embedding-3-large`)
- All queries must use the same model as indexing — changing models requires re-indexing all books
- Model loading takes ~1 second; handled via singleton in `src/ingestion/embedder.py`
