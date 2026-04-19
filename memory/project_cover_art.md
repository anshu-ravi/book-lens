---
name: Cover Art Feature
description: Epub cover extraction with 4-strategy fallback (OPF, meta tag, spine image, Open Library API)
type: project
---

Cover extraction runs during book upload as a best-effort, try/except-guarded step.

**`src/ingestion/cover_extractor.py`**: 4 strategies in order:
1. OPF manifest item with `properties="cover-image"`
2. `<meta name="cover">` item referencing an image in the manifest (EPUB2)
3. First image in spine order
4. `fetch_cover_open_library(title, epub_path)` — queries Open Library API by title

**API**: `GET /library/series/{series_id}/books/{book_index}/cover` — tries `.jpg`, `.jpeg`, `.png`, `.webp` extensions in Supabase Storage and redirects to the first public URL found.

**`has_cover: bool`** field on `Book` model. Preserved on status updates (read via existing book state before patching). Frontend uses `x-if` (not `x-show`) on the cover img element.

**`scripts/backfill_covers.py`**: One-shot script to retroactively extract and upload covers for already-indexed books.

**Why:** Cover art makes the library view more recognizable and improves the reading companion experience.
