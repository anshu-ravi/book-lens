# BookLens Backlog

Items added during development sessions. Format: `- [ ] <item> _(area)_`

## Retrieval

- [ ] Investigate whether `route_query()` in `backend/knowledge/router.py` is performing well — it's already wired up but may not have been validated _(retrieval)_

## Knowledge Graph

## Ingestion

- [ ] Wire the full ingestion pipeline to trigger automatically on book upload — currently only Bronze (extraction) runs as a background task; Silver (deduplication), Gold (Neo4j ingestion), and Prose Index (RAG) ingestion still require manual scripts; all four stages should run end-to-end after a user confirms their upload _(ingestion)_

## Frontend

- [x] Evaluate migrating from Alpine.js single-file SPA to a proper frontend framework — **decided: SvelteKit + `adapter-static`**, Vite proxy in dev, FastAPI serves the static build in prod. Phase 1 skeleton (wired but unstyled, lives at `frontend-svelte/`) is complete; Alpine app at `frontend/index.html` still runs in parallel _(frontend)_

### Phase 2 prerequisites (blocking the redesign)

- [ ] Lock ONE design direction — pick between the Lovable and Claude mockups, commit to one palette + typography pairing, output a single reference screenshot of the Library screen as the north star; no Phase 2 work starts until this is done _(frontend / design)_
- [ ] Write design tokens as CSS custom properties in `frontend-svelte/src/lib/styles/tokens.css` (colors, typography, spacing scale, radii, shadows) once the direction is picked _(frontend)_
- [ ] Decide graph rendering approach for the Explore screen — Cytoscape.js vs D3 force layout vs hand-positioned SVG; prototype the visual on a single screen with hardcoded data before committing; current lean is hand-positioned SVG for the "intentional, illustrated" feel _(frontend / explore)_

### Phase 2 deferred from Phase 1 skeleton

- [ ] Restore the fake upload progress ticker (15% → 85% with status text: "Parsing chapters…" → "Generating embeddings…" → "Indexing vectors…") — dropped in Phase 1 as styling polish, belongs with the redesigned Upload screen _(frontend / upload)_
- [ ] Implement real extraction-status polling — current Alpine app has `isExtracting()` as a stub that always returns false; Phase 2 should either (a) poll `GET /library` every N seconds while any book has `status='in_progress'`, or (b) add a dedicated status endpoint to the backend. Decide and implement when the Library carousel is built _(frontend / library)_
- [ ] Auto-trigger the proactive-prompt toast — currently a manual button; the Alpine app triggers it when the reader advances chapter in the progress modal. Wire the auto-trigger in Phase 2 when the modal is redesigned _(frontend / ask)_

### Phase 2 cutover (end of phase)

- [ ] Write ADR 0004 documenting the SvelteKit migration + design system choices once they've survived one screen's worth of real use — covers framework choice, adapter-static, Vite proxy, styling approach, graph library _(docs)_
- [ ] Production deployment cutover — multi-stage Dockerfile (Node build stage → Python runtime), swap `backend/main.py` static mount from `frontend/` to `frontend-svelte-build/` with `html=True` fallback, delete the Alpine `frontend/index.html` only after the cutover is green on HF Spaces _(infra / frontend)_

## Infrastructure / Ops

- [ ] Evaluate moving character description embeddings from Neo4j vector index to Supabase pgvector — currently there are two vector stores (Neo4j for character semantic search, pgvector for prose retrieval); consolidating may reduce operational surface area but needs evaluation _(infra)_

## Admin & Scripts

- [ ] Replace one-off ingestion scripts with a lightweight admin interface or CLI tool — current scripts in `scripts/` are temporary scaffolding; once the UI handles end-to-end ingestion, consolidate the remaining manual ops (re-run ingestion, backfill, force re-extract) into a single admin tool rather than deleting everything _(admin)_

### Frontend Phase 2 redesign — backend stubs (logged per implementation plan)

- [ ] `QueryResponse.elapsed_ms` — Ask timing line "COMPILED IN 1.4 S"; stubbed client-side via `performance.now()` around the fetch _(frontend / ask)_
- [ ] `QueryResponse.source_count` — Ask "XI PASSAGES CONSULTED"; stubbed via `sources.length` _(frontend / ask)_
- [ ] `QueryResponse.chapter_range` — Ask citation chip "DRAWN FROM CH. 1–N OF VOL. X"; stubbed from active book's current chapter _(frontend / ask)_
- [ ] `GET /library/series/{id}/recap?to_chapter=N` — Explore recap endpoint; currently stubbed by concatenating `TimelineChapter.summary` values _(frontend / explore)_
- [ ] Literary Explore title — one-sentence diagram-state caption per `(series_id, chapter_index)`; currently stubbed via `titleFromState(nodeCount)` client-side _(frontend / explore)_
- [ ] `Series.color` (per-series cover background color) — currently stubbed via deterministic `seriesColor(seriesId)` hashing _(frontend / library)_
- [ ] Edge-type classification (bond / kin / rivalry / passing) on timeline reveals — currently all edges default to `bond`; needs backend classification _(frontend / explore / graph)_
- [ ] Explore graph implementation (Phase 7) — prototype gate between phases 6 and 7; hand-positioned SVG vs D3 force; current GraphPanel is a deliberate placeholder _(frontend / explore)_
- [ ] Help page copy — current prose is placeholder; ~200 words italic muted per the spec _(frontend / help)_

## Docs & Housekeeping
