# BookLens Story Graph Visualization — Handoff Doc

**For:** Ideating on how to visualize the story knowledge graph in the "Explore" / "Reading Compass" tab  
**Context:** Phase 8 of BookLens (spoiler-safe reading companion)  
**Ready to paste into:** claude.ai for design/ideation session

---

## 1. Project Overview

**BookLens** is a single-user, spoiler-safe reading companion for epubs. It extracts a knowledge graph from book text, indexes it in Neo4j, and lets you ask questions about the story without spoilers.

**Three-stage pipeline:**
- **BRONZE (Extraction):** Gemini API reads each chapter, extracts structured JSON: characters, relationships, world facts, identity reveals
- **SILVER (Deduplication):** Canonical registry resolves character aliases ("Reaper" → "Darrow")
- **GOLD (Ingestion):** Write to Neo4j with embeddings for semantic search

The knowledge graph is **ready to be visualized** on the frontend — the Cytoscape.js graph UI is already built but needs API endpoints to serve the data.

---

## 2. Neo4j Graph Schema

### Nodes (all scoped by `series_id`)

#### Character
```
name:                 string  (canonical name)
aliases:              string[] (all known aliases)
faction:              string | null (e.g., "Red", "Gold", "Gray")
role:                 string | null (e.g., "Protagonist", "Antagonist", "Mentor")
description:          string  (250-500 words; physical description, personality, arc)
first_chapter_index:  int     (when character first appears)
embedding:            float[] (384-dimensional sentence-transformer embedding)
series_id:            string  (series identifier)
```

#### Chapter
```
name:                 string (chapter title, e.g., "Prologue", "1: Helldiver")
chapter_index:        int (0-indexed)
summary:              string (200-300 word LLM-generated summary)
book_id:              string (which book in the series)
series_id:            string
```

#### WorldFact
```
name:                 string (e.g., "The Color Caste System")
category:             string (open-ended; e.g., "Social Structure", "Ideology", "Magic System")
description:          string (500-1000 words; deep explanation)
first_chapter_index:  int
series_id:            string
```

### Edges (Character → Character only)

All relationships are directed edges between `Character` nodes.

**Typed relationships:** `ALLY | ENEMY | FAMILY | ROMANCE | MENTOR | RIVAL | OTHER`

Properties (per edge):
```
description:          string (prose description of the relationship)
moments:              string[] (specific scenes/moments showing the relationship)
introduced_in:        int (chapter where this edge first appears)
chapter_index:        int (chapter when last written)
```

**Special relationship:** `REVEALED_AS` (identity reveals)
```
reveal_chapter_index: int (chapter where the reveal happens)
context:              string (narrative context)
reveal_type:          string (SAME_PERSON | DISGUISE | CLONE | RESURRECTION)
                      ^ Note: enum currently dropped before Neo4j write
```

---

## 3. Real Sample Data — Red Rising (5 chapters)

### Sample Character (from Prologue extraction)
```json
{
  "name": "The Narrator",
  "aliases": ["Red"],
  "faction": "Red",
  "role": "Protagonist",
  "description": "A member of the 'Red' caste who feels forged by hardship, hate, and love. He harbors deep resentment against the Gold caste and plans to survive their system.",
  "key_events": [
    "Observing the Golden man's speech",
    "Vowing to defeat the Gold class"
  ],
  "first_chapter_index": 0
}
```

```json
{
  "name": "The Golden man",
  "aliases": ["the beast"],
  "faction": "Gold",
  "role": "Antagonist",
  "description": "Tall, imperious, eagle-like man with piercing eyes who commands the Gold students. He is a harsh proponent of elitist ideology.",
  "key_events": [
    "Giving an inaugural speech to twelve hundred students",
    "Declaring that the strong must dominate the weak"
  ],
  "first_chapter_index": 0
}
```

### Sample Relationship (Prologue)
```json
{
  "character_a": "The Narrator",
  "character_b": "The Golden man",
  "type": "ENEMY",
  "description": "The Golden man views the Narrator's kind as subhuman, while the Narrator harbors a burning desire for revenge against the Golden man.",
  "moments": [
    "The Narrator listens to the Golden man's speech",
    "The Narrator internally vows that none of the Golds will survive"
  ],
  "introduced_in": 0
}
```

### Sample World Facts (Prologue)
```json
{
  "category": "Social Structure",
  "name": "The Color Caste System",
  "description": "A hierarchical society where 'Gold' represents the ruling elite and 'Red' represents the lower class forged in harsh labor."
}
```

```json
{
  "category": "Ideology",
  "name": "Noble Lie of Demokracy",
  "description": "A philosophy rejected by the Golds, which claimed that all men are created equal and the meek should inherit the Earth."
}
```

### Sample Chapter Summary (Prologue)
```
The prologue introduces a world defined by a rigid, color-coded hierarchy, where the ruling 'Gold' class views itself as the pinnacle of evolution and the rightful shepherds of humanity. The story opens with a powerful and imperious Golden man addressing twelve hundred students in a grand hall, delivering a cold, survival-of-the-fittest ideology. He explicitly rejects democratic ideals, labeling them a 'Noble Lie' and a cancer that has poisoned mankind. He informs the privileged students that their power must be earned through blood, pain, and ruthless competition, warning that only the strongest among them will survive the lessons ahead.

Watching this scene from the shadows is an unnamed protagonist who identifies as a 'Red'—the lowest caste in this societal structure. Unlike the pampered Golds raised in luxury, the narrator has been hardened by a life of suffering in the 'bowels' of the world. While the Golden man dehumanizes the narrator and his people, regarding them as weak and feeble, the narrator harbors a secret, burning resolve. He stands as a silent witness, fueled by a mixture of hate and love, and vows that he will ultimately bring about the downfall of his oppressors...
```

### Canonical Registry (after SILVER deduplication)
```json
{
  "the golden man": "The Golden man",
  "the beast": "The Golden man",
  "the narrator": "The Narrator",
  "red": "The Narrator",
  "darrow": "Darrow",
  "helldiver": "Darrow",
  "mad helldiver of lykos": "Darrow",
  "dago": "Darrow",
  "young pup": "Darrow",
  "golden boy": "Darrow",
  "eo": "Eo",
  "little eo": "Eo",
  "uncle narol": "Uncle Narol",
  "ugly dan": "Ugly Dan"
}
```

### Ingestion Results (Red Rising, 5 chapters)
```
Total characters extracted: 13
  - Ingested with no duplicates (deduplication worked)
  
Relationships: 6 edges total
  - ENEMY:    2
  - FAMILY:   1
  - RIVAL:    2
  - ROMANCE:  1

Embeddings: All 13 characters have 384-dim embeddings
```

### Semantic Search Example
```
Query: "protagonist rebel against authority"
Results (top 5):
  1. The Narrator       (score: 0.683)  ← highest relevance
  2. The Golden man     (score: 0.673)
  3. Ugly Dan           (score: 0.656)
  4. Nero au Augustus   (score: 0.641)
  5. Barlow             (score: 0.618)
```

---

## 4. Frontend: Already Built Explore Tab

**Location:** `src/static/index.html`, Alpine.js component `exploreTab()`

### Current UI Structure
- **Left panel:** Cytoscape.js graph canvas
  - Node sizing: proportional to `key_events.length`
  - Node color: hashed from `faction` (deterministic per faction name)
  - Edge color: mapped from relationship type (ALLY=green, ENEMY=red, ROMANCE=pink, etc.)
  - Ghost nodes: 0.3 opacity for characters mentioned but not in the current window
  
- **Right panel (300px):** Three states
  - `recap`: "Story so far" markdown digest + roll-call character chips
  - `character`: Character arc with timeline
    - Faction/role badges
    - Key events as `Book N · Ch N` + description
    - Relationship chips (clickable)
  - `relationship`: Relationship history timeline
    - Events ordered by chapter
    - Turning-point markers
    
- **Scrubber bar (bottom):** Windowing controls
  - Presets: "Last 10 chapters", "This book", "Full series"
  - Custom: book selector + draggable chapter range track

### Frontend Makes These API Calls
```
GET /library/series/{seriesId}/graph
    ?from_book=0&from_chapter=0&to_book=1&to_chapter=5

GET /library/series/{seriesId}/graph/digest
    ?from_book=0&from_chapter=0&to_book=1&to_chapter=5
```

Both routes are **currently missing** in the FastAPI backend. They need to be added to `src/api/library.py` (or new `src/api/explore.py`) and registered in `src/main.py`.

---

## 5. Expected API Response Shapes

### `GET /library/series/{seriesId}/graph`

```json
{
  "nodes": [
    {
      "id": "darrow",           // lowercase, unique in graph
      "label": "Darrow",        // display name
      "faction": "Red",
      "role": "Protagonist",
      "ghost": false,           // true if not first-appeared in window but referenced
      "key_events": [
        {
          "book": 0,
          "chapter": 1,
          "description": "Enters the mines as a Helldiver"
        },
        {
          "book": 0,
          "chapter": 3,
          "description": "Receives the Laurel for productivity"
        }
      ]
    },
    {
      "id": "eo",
      "label": "Eo",
      "faction": "Red",
      "role": null,
      "ghost": false,
      "key_events": [
        {
          "book": 0,
          "chapter": 1,
          "description": "Darrow's wife; sings forbidden rebel songs"
        }
      ]
    }
  ],
  "edges": [
    {
      "source": "darrow",
      "target": "eo",
      "type": "romance",
      "has_turning_point": true,  // true if relationship changes in window
      "moments": [
        {
          "book": 0,
          "chapter": 1,
          "description": "Darrow and Eo dance together before her execution"
        }
      ]
    },
    {
      "source": "darrow",
      "target": "ugly_dan",
      "type": "enemy",
      "has_turning_point": false,
      "moments": [
        {
          "book": 0,
          "chapter": 2,
          "description": "Ugly Dan whips Darrow for not meeting quota"
        }
      ]
    }
  ],
  "scrubber_markers": [
    {
      "book": 0,
      "chapter": 1,
      "type": "turning_point",
      "label": "Eo's Execution"
    }
  ]
}
```

### `GET /library/series/{seriesId}/graph/digest`

```json
{
  "digest": "# Story So Far\n\nThe world is divided into color-coded castes. Darrow, a Red (lowest caste), works in the mines along with Eo, his wife. Eo harbors dreams of rebellion and has taught Darrow forbidden songs. When Eo is caught singing, she is executed by the Society. Darrow's world is torn apart...\n\nKey locations introduced: The Mines, The Township, The Gold Academy (distant, feared).\n\nFactions: Red (laborers), Gold (rulers), Gray (enforcers)."
}
```

---

## 6. Data Not Yet in Neo4j (But Extracted & Available)

### `key_events[]` — Character Timelines
Currently extracted by Gemini but **never written to Neo4j**. Example:
```json
"key_events": [
  "Observing the Golden man's speech",
  "Vowing to defeat the Gold class",
  "Receives the Laurel for productivity",
  "Witnesses Eo's execution"
]
```

**Impact:** Frontend graph node sizing is hardcoded to `key_events.length`, but since Neo4j doesn't have these, the API response currently can't populate them. **Decision needed:** Should we add `key_events` to Character nodes in Neo4j?

### `reveal_type` — Identity Reveal Classification
Extracted as an enum (`SAME_PERSON | DISGUISE | CLONE | RESURRECTION`) but **dropped before Neo4j write**. The `REVEALED_AS` edge only stores `reveal_chapter_index` and `context`.

**Impact:** Visualization can show "Character A is revealed to be Character B" but can't distinguish the reveal type (was it a clone? secret identity? fake death?).

---

## 7. Design Tensions / Open Questions

### 1. No Chapter → Character Edges
The schema has Character, Chapter, and WorldFact nodes, but **no edges between them**. A query like "which characters appear in chapter 3?" requires:
- Filtering Character nodes where `first_chapter_index <= 3`
- Checking relationship `introduced_in` dates
- No direct graph traversal

**Question:** Should we add `APPEARS_IN` edges for a cleaner query model?

### 2. Spoiler Safety for Visualization
How should ghosts + redacted edges work?
- **Ghost nodes:** Characters who haven't appeared yet but are mentioned (0.3 opacity)
- **Redacted edges:** Relationships that form after the window cutoff
- **Redacted reveals:** Identity reveals that haven't happened yet

**Question:** Should ghost nodes be fully visible or slightly desaturated? What about ghost edges?

### 3. Key Events Timeline
The frontend expects `key_events[]` on nodes to size them. Currently it's extracted but not in Neo4j.

**Question:** Add to Neo4j or derive from the raw extraction JSON files in Supabase Storage?

### 4. World Facts Integration
WorldFact nodes exist in the graph but aren't easily connected to characters/chapters. How should they appear in the visualization?

**Question:** Show as a separate sidebar? Integrate as context cards next to relevant characters?

### 5. Relationship Turning Points
The scrubber shows `turning_point` markers. How are these detected?
- Explicit extraction? (e.g., "reveal_type": "SAME_PERSON" triggers a turning point)
- Relationship type change? (ALLY becomes ENEMY)
- Sentiment shift in description?

**Question:** What's the canonical definition of a "turning point"?

---

## 8. Critical Files & Entrypoints

| File | Role |
|---|---|
| `src/knowledge/extractor.py` | EXTRACTION_SCHEMA def + Gemini extraction |
| `src/knowledge/ingestor.py` | All Cypher MERGE/CREATE queries (source of truth for schema) |
| `src/knowledge/query.py` | All Cypher READ queries + spoiler-safe filtering |
| `src/knowledge/neo4j_client.py` | Schema init: constraints, vector index |
| `src/api/library.py` | Where `/library/series/{id}/graph` endpoints should live |
| `src/static/index.html` | Frontend Cytoscape + Alpine.js (fully built, waiting for data) |
| `docs/KNOWLEDGE-GRAPH-SETUP.md` | Architecture overview + test results |
| `data/extractions/red-rising/` | Example extraction JSONs (13 characters, 6 edges, 5 chapters) |

---

## 9. Feature Flags & Configuration

The frontend reads `enable_graph: true/false` from `GET /config` to show/hide the Explore tab.

**Current status:** Explore tab is built and ready but feature-flagged off (no API endpoints).

---

## 10. Key Decisions Already Made

1. **Vector search:** 384-dim embeddings via `sentence-transformers` (all-MiniLM-L6-v2)
2. **LLM:** Gemini 3.1 Flash-Lite for extraction (cost-effective)
3. **Graph DB:** Neo4j (vector index + Cypher queries for rich retrieval)
4. **Frontend:** Cytoscape.js (WebGL, handles 100s of nodes efficiently)
5. **Deduplication:** Canonical registry (lowercase alias → canonical name)
6. **Spoiler safety:** Chapter index on every node/edge, filtered at query time

---

## 11. Ready to Ideate On

Given the schema, sample data, and frontend structure, you can now ideate on:

- **Visual encoding:** How to represent factions, roles, relationship types?
- **Layout:** Force-directed (current), hierarchy, timeline, custom algorithm?
- **Interactions:** Pan/zoom, node details, edge highlighting, search?
- **Responsiveness:** Mobile vs. desktop layouts for the graph?
- **Performance:** How many nodes/edges before rendering lags?
- **Accessibility:** Colorblind-safe palette, keyboard navigation?
- **Animation:** Transitions when scrubbing chapters, revealing new nodes?

**Paste this document into claude.ai to get started.** Refer to specific sections (sample data, schema, existing UI) and ask for design recommendations.

