# Qdrant Integration Notes

Learnings and gotchas from Phase 3 integration.

---

## Collection Strategy

- **One collection per `series_id`** — keeps book filtering simple and collections small
- Collection name = series_id (e.g. `"red-rising"`, `"standalone"`)
- Created automatically on first upsert via `_ensure_collection()`
- Vector size must be **384** for `all-MiniLM-L6-v2`; wrong size causes a silent mismatch

## Re-indexing (Idempotency)

Two-layer safety for safe re-uploads:

1. **Filter-delete before upsert** — removes all points where `book_index == N`
2. **Deterministic point IDs** — `uuid5(NAMESPACE_DNS, "{series_id}:{book_index}:{chunk_id}")` — same chunk always gets the same UUID, so an upsert is truly an update if the delete somehow missed a point

## Filter Syntax (Qdrant v1.x)

Qdrant filters are `qdrant_client.http.models.Filter` objects, not plain dicts.

```python
from qdrant_client.http.models import Filter, FieldCondition, MatchValue, Range

# Match exact value
Filter(must=[FieldCondition(key="book_index", match=MatchValue(value=0))])

# Numeric range (used in Phase 5 for chapter filtering)
Filter(must=[FieldCondition(key="chapter_index", range=Range(lte=5))])

# OR logic — use `should` instead of `must`
Filter(should=[
    FieldCondition(key="book_index", match=MatchValue(value=0)),
    FieldCondition(key="book_index", match=MatchValue(value=1)),
])
```

## Payload Schema

Every point stored with this payload:

```json
{
  "series_id": "red-rising",
  "book_index": 0,
  "chunk_id": "chapter_3_chunk_2",
  "chapter_index": 3,
  "chapter_label": "Chapter 4",
  "text": "...",
  "word_count": 412,
  "position": 2
}
```

**Important:** Qdrant Cloud does NOT auto-index payload fields. Any field used in a filter must have an explicit payload index or Qdrant returns a 400 error. Create indexes immediately after `create_collection`:

```python
client.create_payload_index(collection_name, field_name="book_index", field_schema=PayloadSchemaType.INTEGER)
client.create_payload_index(collection_name, field_name="chapter_index", field_schema=PayloadSchemaType.INTEGER)
```

## Batching

- **Embed:** batch_size=64 (SentenceTransformer default; tune down if OOM)
- **Upsert:** batch_size=100 (Qdrant recommended for stable throughput)

## API Version Notes (qdrant-client >= 1.7)

`client.search()` was removed. Use `client.query_points()` instead:

```python
response = client.query_points(
    collection_name=series_id,
    query=embedding,          # list[float]
    query_filter=qdrant_filter,
    limit=top_k,
    with_payload=True,
)
hits = response.points       # list[ScoredPoint]
```

## Connection

```python
from qdrant_client import QdrantClient

# Local dev
client = QdrantClient(url="http://localhost:6333")

# Qdrant Cloud
client = QdrantClient(url="https://xyz.qdrant.io:6333", api_key="your-key")
```

Both use identical method calls — only the constructor differs. The `QdrantVectorStore` reads URL and API key from `settings` (`.env`).

## Free Tier Limits (as of 2026)

- 1 free cluster
- 1 GB storage
- ~1M 384-dim vectors fit comfortably within this limit for a personal library
