---
name: Supabase Migration
description: Backend migrated from Qdrant+JSON files to Supabase (Postgres + pgvector + Storage + Auth)
type: project
---

The entire persistence layer was replaced with Supabase.

**Vector store**: `src/vector_store/supabase_store.py` — pgvector via `vectors` table with `match_vectors` RPC for semantic search. Fully user-scoped (`user_id` on every row).

**Library state**: `src/library/manager.py` — was a single `library.json` file; now reads/writes `series` and `books` tables in Supabase Postgres. All functions are now `async`.

**Knowledge base**: `src/knowledge/store.py` — was `knowledge/{series_id}.json`; now a single `knowledge` table with `(series_id, user_id, data JSONB)`.

**File storage**: epub files → `books` bucket at `{user_id}/{series_id}/book_{book_index}.epub`; cover images → `covers` bucket at `{user_id}/{series_id}/cover_{book_index}{ext}`.

**Auth**: `get_current_user()` FastAPI dependency verifies Supabase JWT via `client.auth.get_user(token)`. Dev fallback: missing auth header returns dummy UUID `00000000-0000-0000-0000-000000000000`.

**New files**: `src/supabase_client.py`, `src/vector_store/supabase_store.py`, `supabase_setup.sql`.

**Config**: `settings` now requires `supabase_url`, `supabase_key` (service role), and optionally `supabase_anon_key` (public key for frontend). Qdrant keys are still in config but optional.

**Why:** Moving from local files + Qdrant Cloud to a single Supabase backend enables multi-user support, auth, and Vercel deployment.

**How to apply:** All library/knowledge/vector operations are now async and require `user_id`. The `SupabaseVectorStore` is initialized in the FastAPI lifespan and attached to `app.state.vector_store`.
