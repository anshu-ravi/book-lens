# BookLens Backlog

Items added during development sessions. Format: `- [ ] <item> _(area)_`

## Retrieval

- [ ] Investigate whether `route_query()` in `backend/knowledge/router.py` is performing well — it's already wired up but may not have been validated _(retrieval)_

## Knowledge Graph

## Ingestion

- [ ] Wire the full ingestion pipeline to trigger automatically on book upload — currently only Bronze (extraction) runs as a background task; Silver (deduplication), Gold (Neo4j ingestion), and Prose Index (RAG) ingestion still require manual scripts; all four stages should run end-to-end after a user confirms their upload _(ingestion)_

## Frontend

- [ ] Evaluate migrating from Alpine.js single-file SPA to a proper frontend framework (Next.js or SvelteKit) — current setup was not a deliberate choice and will become hard to maintain as the UI grows; assess scope and plan migration in a dedicated session _(frontend)_

## Infrastructure / Ops

- [ ] Evaluate moving character description embeddings from Neo4j vector index to Supabase pgvector — currently there are two vector stores (Neo4j for character semantic search, pgvector for prose retrieval); consolidating may reduce operational surface area but needs evaluation _(infra)_

## Admin & Scripts

- [ ] Replace one-off ingestion scripts with a lightweight admin interface or CLI tool — current scripts in `scripts/` are temporary scaffolding; once the UI handles end-to-end ingestion, consolidate the remaining manual ops (re-run ingestion, backfill, force re-extract) into a single admin tool rather than deleting everything _(admin)_

## Docs & Housekeeping
