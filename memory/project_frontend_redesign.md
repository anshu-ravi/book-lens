---
name: Frontend Literary Redesign
description: Full frontend redesign with literary design system, desktop sidebar, Supabase Auth, and chat thread UI
type: project
---

The Alpine.js SPA was fully redesigned with a literary/book-aesthetic design system.

**Design tokens** (`--bone`, `--bone-2/3`, `--ink`, `--ink-2/3/4`, `--forest`, `--moss`, `--brass`, `--ribbon`, `--green`, `--amber`, `--red` + dim variants). Fonts: Cormorant Garamond (display), Source Serif 4 (body), JetBrains Mono.

**Layout**: Desktop sidebar + main content area. Mobile: bottom-tab nav.

**Library view**: Cover strips for each book, continue-reading section for in-progress books. Real epub cover art shown via `x-if` (not `x-show`) to prevent spurious 404 requests. Open Library fallback for missing covers.

**Ask view**: Redesigned as a chat thread with scope banners showing current series/chapter context. Conversation history sent to backend. Error messages filtered from history before re-sending. Sources panel collapsed by default with a toggle.

**Auth**: Supabase JS SDK (`@supabase/supabase-js@2`) handles sign-in/out. JWT passed as `Authorization: Bearer <token>` on all API calls. `GET /config` endpoint returns `supabase_url` and `supabase_anon_key` for frontend initialization.

**Series selector in Ask**: Defaults to the currently-reading series; falls back to the first series.

**Why:** Phase 6 frontend was functional but unstyled. This brings it to a production-quality literary aesthetic matching the book-companion use case.
