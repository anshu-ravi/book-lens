# Scripts

Dev-only scripts for ingestion, backfill, and ad-hoc queries. None of these run in production.

## Ongoing / Common

| Script | Purpose |
|--------|---------|
| `run_pipeline.py` | Full KG pipeline: BRONZE → SILVER → GOLD. Parses EPUB, extracts entities, dedupes, ingests into Neo4j. |
| `run_rag_ingest.py` | RAG vector ingestion: EPUB → hierarchical nodes → Supabase pgvector (`book_rag_*` tables). Run after `run_pipeline.py` to enable prose retrieval in chat. |
| `run_kg_ingest.py` | Re-ingest gold layer into **dev** Neo4j (port 7688), bypassing the async extraction gate. Useful when re-seeding local Neo4j. |
| `ask.py` | CLI: ask a question against the current knowledge graph + RAG index. Quick smoke-test for the full retrieval chain. |
| `query.py` | CLI: direct vector search against Supabase pgvector. Useful for tuning retrieval. |

## One-off / Backfill

| Script | Purpose |
|--------|---------|
| `backfill_chunks.py` | Backfills the legacy `book_chunks` table for books uploaded before RAG ingestion was set up. Safe to re-run. |
| `backfill_covers.py` | Scans `local/uploads/` for EPUBs without extracted cover images and runs extraction. |
| `clean_aliases.py` | Post-deduplication cleanup: remove malformed aliases from Neo4j character nodes. |
| `extract.py` | Ad-hoc extraction runner — runs entity extraction on a subset of chapters. |
| `extract_book.py` | Extract a full book's entities to disk (JSON). |
| `extract_chapters.py` | Extract individual chapters with a hardcoded EPUB path — edit before running. |
| `ingest.py` | Low-level: chunk and store a single book into the legacy `book_chunks` table. |

## Typical first-run workflow

```bash
# 1. Full knowledge graph pipeline
poetry run python scripts/run_pipeline.py \
    --epub local/uploads/red-rising/book_0.epub \
    --series the-red-rising-saga

# 2. RAG vector index
poetry run python scripts/run_rag_ingest.py \
    --epub local/uploads/red-rising/book_0.epub \
    --series the-red-rising-saga \
    --book-id <book_uuid> \
    --user-id <user_uuid> \
    --title "Red Rising"

# 3. Smoke-test
poetry run python scripts/ask.py \
    --series the-red-rising-saga \
    --question "Who is Eo?"
```
