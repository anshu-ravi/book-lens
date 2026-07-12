# BookLens — SvelteKit Frontend (Phase 1 Skeleton)

A fully wired SvelteKit SPA that talks to the existing FastAPI backend.
All 5 routes work end-to-end. No styling — that's Phase 2.

## Running in development

Requires both the FastAPI backend and the Vite dev server:

```bash
# Terminal 1 — FastAPI backend
cd .. && poetry run uvicorn backend.app:app --reload

# Terminal 2 — SvelteKit dev server
cd frontend-svelte && npm run dev
```

Open `http://localhost:5173`. The Vite proxy forwards `/config`, `/library`, `/books`, and `/query` to `http://localhost:8000`, so no CORS configuration is needed.

The existing Alpine.js app at `http://localhost:8000/` remains untouched.

## Building

```bash
npm run build
```

Outputs a fully static SPA to `frontend-svelte/build/`. Production wiring (having FastAPI serve the build) is out of scope for Phase 1.

## Type checking

```bash
npm run check
```

## Notes

- `POST /library/series` is wired on the frontend but the backend endpoint does not exist yet. Creating a series currently goes through the upload flow (series is created implicitly when a book is uploaded with a series name).
- Extraction polling (`isExtracting`) is stubbed — always false. Real polling deferred to Phase 2.
- The Explore tab is gated on `features.enable_graph` from `/config`.
