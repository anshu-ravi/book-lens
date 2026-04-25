# The Reading Compass — Design Spec

**Date:** 2026-04-25  
**Status:** Approved

---

## Problem

Readers of long series (3+ books, 50+ chapters each) lose track of who characters are, how they relate, and what happened. BookLens already answers reactive questions. The Reading Compass is a proactive visual tool — a living map of the story world readers can explore on demand, always spoiler-safe.

---

## Concept

A dedicated **Explore** tab in the left-side nav. One canvas, one coherent experience:

- **Left**: Cytoscape.js character relationship web (the "map")
- **Right**: Contextual recap panel (responds to interactions on the map)
- **Bottom**: Preset chips + optional single-thumb time scrubber

The graph is the navigation UI for the recap. The reader points at what they care about; the recap follows.

---

## UI Layout

```
Left nav (vertical): [Library] [Upload] [Ask] [Explore]

┌─ Explore Tab ──────────────────────────────────────────────────┐
│  Series: [Red Rising Saga ▼]                                    │
├───────────────────────────┬────────────────────────────────────┤
│                           │                                     │
│   CHARACTER WEB           │   RECAP PANEL                      │
│   (Cytoscape.js)          │                                     │
│                           │   State 1: Full story digest        │
│   Nodes = characters      │   State 2: Character arc            │
│   Edges = relationships   │   State 3: Relationship history     │
│                           │                                     │
├───────────────────────────┴────────────────────────────────────┤
│  [Last 10 chapters]  [This book]  [Full series]  [Custom ↓]    │
│  Custom: [Book 1 ▼]  ══════●══════════════════  Ch 1 → Ch 40  │
│                        ◆        ◆    ◆                          │
│                     marker dots on track                        │
└────────────────────────────────────────────────────────────────┘
```

**Series auto-selection:** Defaults to whatever series is marked as currently reading in Library.  
**Book auto-selection:** Defaults to current reading book in that series.  
**Default window:** Ch 1 of current book → current reading chapter (full book digest).

---

## Character Graph (Cytoscape.js — CoSE-Bilkent layout)

### Nodes
- Circular, sized by story prominence (count of `key_events`)
- Color-coded by `character.faction`
- Label = canonical name beneath node
- Characters before window start → ghost (30% opacity), still rendered
- Characters not yet appeared in window → hidden entirely (true spoiler safety)

### Edges
- Color = relationship type: ally (green), rival/enemy (red), family (blue), romance (pink), mentor (purple)
- Thickness = relationship strength (count of `moments`)
- If type changed within window → current type color + small turning-point icon marker on edge

### Layout behavior
- CoSE-Bilkent runs once on load; positions are then fixed (same-faction chars cluster naturally)
- Nodes are draggable (reader can arrange their own mental map)
- Layout re-runs only when new characters enter (scrubbing forward past a first appearance)

### Time scrubbing animations (no re-layout)
- New character enters → fade in from 0 opacity over 400ms
- Scrubbing back → character fades to ghost (30% opacity), never disappears
- Relationship type changes → edge color crossfades over 300ms
- New relationship appears → stroke-dashoffset draw-in animation
- Scrubber snaps to chapter boundaries on mouseup — no continuous redraws mid-drag

---

## Time Scrubber

### Primary controls
```
[Last 10 chapters]  [This book]  [Full series]  [Custom ↓]
```
Covers 90% of use cases with one tap.

### Custom scrubber
- **Single-thumb** (not dual-range) — the "to" is permanently locked to the reader's current reading position
- Book selector dropdown sets the track's book context
- Track is segmented by book for cross-book ranges
- Marker dots on track (from `scrubber_markers`): relationship events (teal), turning points (orange), first appearances (white)
- Hover dot → tooltip ("Ch 12 — Darrow meets Cassius")
- API fires only on mouseup/touchend

---

## Recap Panel (3 States)

### State 1 — Full Recap (default)
- Triggered by: page load, preset chip tap, clicking empty canvas
- Content: 3-4 paragraph narrative digest (Claude call) + character roll-call chips
- Clicking a chip → State 2

### State 2 — Character Arc
- Triggered by: clicking a character node or roll-call chip
- Content: character header (name, faction, role) + chronological key events timeline + connections chips
- **No API call** — instant client-side render from graph payload
- Clicking a connection chip → State 3

### State 3 — Relationship History
- Triggered by: clicking an edge or a connection chip
- Content: relationship header (current type) + chronological moments timeline + turning point markers
- **No API call** — instant client-side render from graph payload

---

## Backend

### Two endpoints (split for performance)

**Endpoint A — Graph data (fast, no LLM):**
```
GET /library/series/{id}/graph
    ?from_book=0&from_chapter=0&to_book=1&to_chapter=39
```

Response:
```json
{
  "nodes": [{
    "id": "Darrow", "label": "Darrow", "faction": "Reds", "role": "protagonist",
    "first_appearance": {"book": 0, "chapter": 0},
    "key_events": [{"book": 0, "chapter": 3, "description": "Eo is executed"}],
    "ghost": false
  }],
  "edges": [{
    "source": "Darrow", "target": "Cassius",
    "type": "rival", "initial_type": "ally",
    "moments": [{"book": 0, "chapter": 5, "description": "Meet in institute"}],
    "has_turning_point": true
  }],
  "scrubber_markers": [
    {"book": 0, "chapter": 5, "label": "Darrow meets Cassius", "type": "relationship"},
    {"book": 0, "chapter": 22, "label": "Cassius betrays Darrow", "type": "turning_point"}
  ]
}
```

**Endpoint B — Digest (async, LLM call):**
```
GET /library/series/{id}/graph/digest
    ?from_book=0&from_chapter=0&to_book=1&to_chapter=39
```

Response: `{ "digest": "Narrative markdown..." }`

Frontend calls both in parallel. Graph renders immediately from A. Recap panel fills in when B resolves.

### New module: `src/graph/`
- `builder.py` — constructs nodes/edges/scrubber_markers from KB + window params
- `digest.py` — filters chapter summaries to window, calls Claude for narrative digest

No new Supabase tables. No new extraction. Everything sourced from existing KB.

---

## Files

**New:**
- `src/graph/__init__.py`
- `src/graph/builder.py`
- `src/graph/digest.py`

**Modified:**
- `src/main.py` — add two graph endpoints
- `src/static/index.html` — Explore tab, Cytoscape.js CDN, scrubber, recap panel

---

## Verification

1. Explore tab appears in left nav; auto-selects reading series and book
2. Preset chips fire correct window params; digest updates
3. Custom scrubber: drag → graph + digest update on mouseup
4. Scrubber markers show correct tooltips; clicking jumps to that chapter
5. Node click → character arc renders instantly (no API call)
6. Edge click → relationship history renders instantly
7. Time scrubbing: fade-in, ghost, crossfade animations correct
8. Spoiler safety: cannot scrub past current reading position; future characters never appear
