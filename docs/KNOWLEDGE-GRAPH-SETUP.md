# Neo4j Knowledge Graph Setup & Testing

## Overview

Successfully implemented and tested the BRONZE → SILVER → GOLD knowledge extraction pipeline using Neo4j, Gemini 3.1 Flash-Lite, and sentence-transformers.

## Architecture

### Three-Stage Pipeline

**BRONZE (Extraction):** `scripts/extract.py`
- Extracts structured knowledge from EPUB chapters using Gemini API
- Outputs JSON files to `data/extractions/{series_id}/{index}_{label}.json`
- Uses Neo4j for coreference resolution (known characters)
- Handles skip-if-exists to avoid re-extraction

**SILVER (Deduplication):** Part of `scripts/ingest.py`
- Walks chapters 0→N in order
- Maintains canonical registry: `alias_lower → canonical_name`
- Resolves character aliases and merges entries
- Tracks identity reveals for later processing
- Outputs: `canonical_registry.json`, `pending_reveals.json`

**GOLD (Ingestion):** Part of `scripts/ingest.py`
- Non-destructive MERGE pattern (no overwrites on re-run)
- Embeds character descriptions using sentence-transformers (384-dims)
- Creates nodes: Character, Chapter, WorldFact
- Creates relationships: ALLY, ENEMY, FAMILY, ROMANCE, MENTOR, RIVAL, OTHER, REVEALED_AS
- Stores embeddings for vector search

### Vector Search

**Query Interface:** `src/knowledge/query.py` + `scripts/query.py`
- Semantic search via embedding similarity
- Spoiler-safe filtering by chapter cutoff
- Filters out characters with future REVEALED_AS edges

## Test Results (Red Rising Book 0)

### Extraction (BRONZE)
```
Extracted:  5 chapters
Characters: 13 unique characters extracted
Example:   "The Narrator" (aliases: ["Red"]), first seen ch 0
           "Darrow" (aliases: ["Helldiver", "mad Helldiver of Lykos"]), first seen ch 1
```

### Ingestion (GOLD)
```
Characters:  13 ingested (no duplicates on re-run)
Relationships: 6 edges across 4 types
  - ENEMY:    2
  - FAMILY:   1
  - RIVAL:    2
  - ROMANCE:  1
Embeddings: All 13 characters embedded (384-dims)
```

### Semantic Search Test
```bash
$ python scripts/query.py --series red-rising --chapter 4 --search "protagonist rebel against authority" --top-k 5

Results:
  1. The Narrator       (0.683) - Protagonist rebel
  2. The Golden man     (0.673) - Authority antagonist
  3. Ugly Dan           (0.656) - Authority supervisor
  4. Nero au Augustus   (0.641) - Authority figure
  5. Barlow             (0.618) - Elder/conservative
```

### Idempotency Verification
✅ Re-running extraction: Skips existing files
✅ Re-running ingestion: No duplicate characters (MERGE works)
✅ Character count: Remained at 13 after re-ingest

## Configuration

### Environment Variables
```bash
# Neo4j
NEO4J_URI=neo4j://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASS=password

# Google Gemini
GOOGLE_API_KEY=your-key-here
```

### Neo4j Setup
Docker Compose already configured in `docker-compose.neo4j.yml`:
```bash
docker-compose -f docker-compose.neo4j.yml up -d
# Accesses at: neo4j://localhost:7687 (bolt protocol)
# UI at: http://localhost:7474
```

## Model Details

### Gemini 3.1 Flash-Lite
- **Cost:** $0.25/M input tokens, $1.50/M output tokens (half of Gemini 3 Flash)
- **Context:** 1,048,576 tokens
- **Max Output:** 65,536 tokens
- **Free Tier:** Available through Google AI Studio with rate limits
- **Use Case:** Cost-effective structured extraction with JSON schema mode

### Sentence-Transformers
- **Model:** all-MiniLM-L6-v2
- **Dimensions:** 384
- **Speed:** Fast inference, suitable for batch embedding
- **Quality:** Good balance of quality vs. performance for semantic search

## File Structure

```
src/knowledge/
├── __init__.py              # Package exports
├── neo4j_client.py          # Driver singleton + schema setup
├── embedder.py              # Sentence-transformers wrapper
├── extractor.py             # BRONZE stage (Gemini extraction)
├── deduplicator.py          # SILVER stage (deduplication)
├── ingestor.py              # GOLD stage (Neo4j ingestion)
├── query.py                 # Query interface (spoiler-safe)
└── pipeline.py              # Orchestrator

scripts/
├── extract.py               # BRONZE CLI
├── ingest.py                # SILVER + GOLD CLI
├── run_pipeline.py          # Full pipeline CLI
└── query.py                 # Semantic search CLI

data/
└── extractions/
    └── red-rising/          # Series output directory
        ├── 000_Prologue.json
        ├── 001_1:_Helldiver.json
        ├── ...
        ├── canonical_registry.json
        └── pending_reveals.json
```

## Usage Examples

### Extract from EPUB
```bash
python scripts/extract.py --epub uploads/red-rising/book_0.epub --series red-rising --limit 10
```

### Deduplicate & Ingest
```bash
python scripts/ingest.py --series red-rising --limit 10
```

### Full Pipeline
```bash
python scripts/run_pipeline.py --epub uploads/red-rising/book_0.epub --series red-rising --limit 10
```

### Semantic Search
```bash
python scripts/query.py --series red-rising --chapter 5 --search "protagonist" --top-k 10
```

### Programmatic Usage
```python
from src.knowledge import KnowledgePipeline, KnowledgeQueryEngine

# Full pipeline
pipeline = KnowledgePipeline("red-rising")
with open("uploads/red-rising/book_0.epub", "rb") as f:
    pipeline.run_all(f.read(), limit=10)

# Query
engine = KnowledgeQueryEngine("red-rising")
results = engine.semantic_search("protagonist", up_to_chapter=5, top_k=10)
```

## Known Issues & Limitations

1. **Vector Index Deprecation:** Neo4j 5.27 shows deprecation warning for `db.index.vector.queryNodes`. Replace with `SEARCH` in future versions.

2. **Identity Reveals:** Currently tracks via REVEALED_AS edges but requires explicit mention in extraction. No speculative merges.

3. **Coreference Resolution:** Uses Neo4j-known characters to guide Gemini extraction. May miss subtle references.

4. **First Ingestion:** Chapters with no new characters still create Chapter nodes (by design).

## Next Steps

1. **Full Extraction:** Run extraction on all chapters of Red Rising trilogy
2. **Scale Testing:** Test with longer books (Project Hail Mary, Licanius Trilogy)
3. **Identity Resolution:** Implement identity reveal detection in later chapters
4. **API Integration:** Connect query engine to FastAPI endpoints
5. **UI Integration:** Add knowledge graph visualization to frontend

## Performance Notes

- **Extraction (BRONZE):** ~30-60s per chapter (depends on Gemini latency)
- **Deduplication (SILVER):** Fast, O(n) single pass
- **Ingestion (GOLD):** ~1-2s per chapter (Neo4j writes)
- **Semantic Search:** <100ms per query (vector index)

## Testing Checklist

- [x] Directory structure cleaned
- [x] Cruft removed (97 files)
- [x] BRONZE extraction works (idempotent)
- [x] SILVER deduplication works (canonical registry)
- [x] GOLD ingestion works (non-destructive MERGE)
- [x] Character embeddings created
- [x] Relationships extracted
- [x] Semantic search functional
- [x] Re-run idempotency verified
- [x] No duplicate characters on re-ingest

