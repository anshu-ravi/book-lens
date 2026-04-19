# Phase 7: Entity Knowledge Engine

**Date:** 2026-04-18  
**Status:** Proposed

---

## Why This Phase Exists

BookLens's current query engine is pure RAG: embed the question → retrieve 5 similar chunks → Claude answers. This fails for a reading companion because vector similarity answers the question "what text looks like this question?" not "what do I know that's relevant to this question?"

A companion who has read the same books as you doesn't work by scanning pages for similar sentences. They have structured knowledge — they know *who* Darrow is, *what* happened between him and Cassius, *why* the color system matters. That's relational, not similarity-based.

**The failure modes:**
- Question 20 chapters into Book 2 needs all of Book 1 as context, but RAG only finds chunks semantically close to the question wording
- "Who is Sevro?" returns random passages mentioning Sevro, not a coherent profile
- "Recap chapters 10-15" is unanswerable without chapter summaries
- "What's Darrow's journey so far?" requires synthesizing hundreds of pages, not 5 chunks

---

## The Companion Vision

A reading companion that behaves like a friend who has read exactly the same amount as you, remembers everything, and can answer:

| Question type | Example |
|---|---|
| Character profile | "Who is Sevro?" |
| Relationship history | "What's the history between Darrow and Cassius?" |
| Plot recap | "What happened in Book 1?", "Recap chapters 10-15" |
| Character arc | "Trace Darrow's journey through the series so far" |
| World-building | "How does the color system work?" |
| Causal reasoning | "Why did Darrow betray X?" |
| Conversational follow-up | "Tell me more about that" |

All spoiler-safe — the companion only knows what the reader has read.

---

## Architecture Overview

Three layers of knowledge, built during explicit extraction:

```
INGESTION (upload)              EXTRACTION (user-triggered, separate step)
─────────────────               ──────────────────────────────────────────
epub → chunks → Qdrant          epub → chapters → Claude (tool_use)
   (fast, ~30s)                    → entities + summaries → knowledge/{id}.json
                                   (2-10 min, ~$0.05-0.20 per book)

QUERY TIME
──────────
question
  → classify type
  → extract entity mentions (using alias registry)
  → load KB, filter to reading progress
  → build context:
       entity profiles  + chapter summaries  + RAG chunks
       (who/what/where)   (what happened)       (specific passages)
  → Claude answers with conversation history
```

**No graph database.** A structured JSON file per series is the right storage for this scale. The "graph" is implicit in the relationship entries — no traversal engine needed.

---

## Key Design Decisions

### D1: Decouple Extraction From Upload

**Old plan**: extraction runs inside `upload_book()`, adding 2-10 minutes to upload latency, non-fatally.

**New plan**: `upload_book()` only does what it does today (epub → chunks → vectors). Knowledge extraction is triggered by a separate `POST /library/series/{id}/books/{book_idx}/extract` endpoint, called explicitly by the user.

**Why**: The user gets a fast upload experience. They can ask questions via RAG immediately. They trigger extraction when they want the richer companion experience. They also see exactly what the extraction costs (time, API calls) before incurring it. Extraction on re-upload also shouldn't re-run automatically — the user controls it.

### D2: Structured Outputs via Claude Tool Use

**Old plan**: Ask Claude to return raw JSON in the response body. Parse it, strip markdown fences, handle malformed output.

**New plan**: Define an extraction tool (`record_chapter_knowledge`) with a full JSON schema. Call Claude with `tool_choice={"type": "tool", "name": "record_chapter_knowledge"}`. Claude's response is always a `tool_use` block — the `input` field is already a parsed Python dict. Zero JSON parsing needed.

```python
response = client.messages.create(
    model=settings.extraction_model,
    max_tokens=4096,
    tools=[EXTRACTION_TOOL_SCHEMA],
    tool_choice={"type": "tool", "name": "record_chapter_knowledge"},
    messages=[{"role": "user", "content": prompt}],
)
extraction_data = response.content[0].input  # Already a dict, schema-validated
```

This eliminates the single most fragile part of the pipeline.

### D3: Alias Registry as First-Class Concept

A compact lookup table stored inside `KnowledgeBase`:

```python
alias_registry: dict[str, str]
# e.g. {"the reaper": "Darrow", "darrow of lykos": "Darrow", "goblin": "Sevro"}
```

All keys are lowercased. Built and updated during extraction. Used for two purposes:
1. **During extraction**: passed as context to each chapter's extraction prompt so Claude uses canonical names consistently (coreference resolution without an NLP pipeline)
2. **During queries**: fast entity mention detection — scan the question for any known alias, return canonical names

### D4: Conversation History in the Query Engine

A companion without memory of the conversation is not a companion. This belongs in Phase 4, not deferred.

`QueryRequest` gains an optional field:
```python
conversation_history: list[dict] = []
# Each dict: {"role": "user"|"assistant", "content": str}
```

The Claude API call becomes:
```python
messages = [
    *body.conversation_history,           # Prior turns
    {"role": "user", "content": prompt},  # Current enriched prompt
]
```

The frontend accumulates history client-side and sends it with each request. The backend is stateless — no session storage needed.

### D5: RAG Improvements as a Baseline

Regardless of whether entity extraction has run, the retrieval quality improves in Phase 4:
- Increase `top_k` from 5 to 12
- Add neighbor chunk expansion: if chunk at position N scores highly, also include positions N-1 and N+1 (if they exist in the same chapter)
- This improves local narrative coherence for free — the chunk before and after a relevant passage often contains critical context

These apply even when the knowledge base is empty.

---

## Data Models (`src/knowledge/models.py`)

Following conventions in `src/models.py`: Pydantic `BaseModel` for persisted types, `@dataclass` for transient types.

```python
class ChapterRef(BaseModel):
    book_index: int
    chapter_index: int

class CharacterEvent(BaseModel):
    description: str
    book_index: int
    chapter_index: int

class CharacterEntity(BaseModel):
    name: str                              # Canonical: "Darrow"
    aliases: list[str]                     # ["Darrow of Lykos", "the Reaper"]
    faction: str | None
    role: str | None                       # "protagonist", "antagonist", "mentor"
    description: str                       # 2-3 sentence profile
    first_appearance: ChapterRef
    key_events: list[CharacterEvent]       # Ordered by chapter

class RelationshipMoment(BaseModel):
    description: str
    book_index: int
    chapter_index: int

class Relationship(BaseModel):
    character_a: str                       # Canonical names
    character_b: str
    type: str                              # "ally","rival","family","romance","mentor","enemy"
    description: str                       # Current state of relationship
    moments: list[RelationshipMoment]      # Key moments that changed it

class WorldFact(BaseModel):
    category: str                          # Free-form: "faction","location","concept","rule"
    name: str
    description: str
    book_index: int
    chapter_index: int

class ChapterSummary(BaseModel):
    book_index: int
    chapter_index: int
    chapter_label: str
    summary: str                           # 200-300 words
    characters_present: list[str]          # Canonical names
    key_events: list[str]                  # Brief event descriptions

class KnowledgeBase(BaseModel):
    series_id: str
    characters: list[CharacterEntity] = []
    relationships: list[Relationship] = []
    world_facts: list[WorldFact] = []
    summaries: list[ChapterSummary] = []
    alias_registry: dict[str, str] = {}    # lowercase alias → canonical name
    extracted_chapters: list[ChapterRef] = []  # Tracks what's been processed

# Transient — returned from extraction, never stored directly
@dataclass
class ChapterExtraction:
    characters: list[CharacterEntity]
    relationships: list[Relationship]
    world_facts: list[WorldFact]
    summary: ChapterSummary
```

**What was removed vs. the previous plan**: `PlotEvent` (redundant — events live in `CharacterEvent` and `ChapterSummary`). `ExtractionRecord` with timestamps (simplified to just `extracted_chapters: list[ChapterRef]`).

---

## Extraction Tool Schema (the core Claude prompt contract)

The tool schema passed to Claude's API for `record_chapter_knowledge`:

```python
{
    "name": "record_chapter_knowledge",
    "description": "Record all structured knowledge extracted from this chapter",
    "input_schema": {
        "type": "object",
        "required": ["characters", "relationships", "world_facts", "summary"],
        "properties": {
            "characters": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["name", "aliases", "description", "key_events"],
                    "properties": {
                        "name": {"type": "string"},
                        "aliases": {"type": "array", "items": {"type": "string"}},
                        "faction": {"type": "string"},
                        "role": {"type": "string"},
                        "description": {"type": "string"},
                        "key_events": {"type": "array", "items": {"type": "string"}}
                    }
                }
            },
            "relationships": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["character_a", "character_b", "type", "description", "moments"],
                    "properties": {
                        "character_a": {"type": "string"},
                        "character_b": {"type": "string"},
                        "type": {"type": "string"},
                        "description": {"type": "string"},
                        "moments": {"type": "array", "items": {"type": "string"}}
                    }
                }
            },
            "world_facts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["category", "name", "description"],
                    "properties": {
                        "category": {"type": "string"},
                        "name": {"type": "string"},
                        "description": {"type": "string"}
                    }
                }
            },
            "summary": {"type": "string"}
        }
    }
}
```

---

## Merger Logic (`src/knowledge/merger.py`)

`merge_extraction(kb, extraction, book_index, chapter_index) -> KnowledgeBase`

**Characters**: for each new character, check if `name.lower()` OR any alias (lowercased) exists in `kb.alias_registry`. If a match is found, merge into the existing character (append new key_events, merge new aliases). If no match, add as new. Update `alias_registry` with all aliases pointing to canonical name.

**Relationships**: match by unordered `frozenset({character_a, character_b})`. If exists, append new moments. If new, add.

**World facts**: match by `(category.lower(), name.lower())`. If exists, keep longer description. If new, add.

**Summaries**: always append (one per chapter — idempotent by `(book_index, chapter_index)`).

**`extracted_chapters`**: append `ChapterRef(book_index, chapter_index)`.

---

## `src/knowledge/store.py`

Pure functions, follows `src/library/manager.py` pattern:

- `load_knowledge(series_id) -> KnowledgeBase` — from `{settings.knowledge_dir}/{series_id}.json`, empty KB if missing
- `save_knowledge(kb) -> None`
- `is_chapter_extracted(kb, book_index, chapter_index) -> bool`
- `filter_to_progress(kb, series: Series) -> KnowledgeBase` — same spoiler boundary as `build_qdrant_filter()`: COMPLETED → all data, READING → data up to `current_chapter_index`, NOT_STARTED → excluded. Truncates `key_events`, `moments`, filters `summaries`/`world_facts` by chapter stamp.
- `delete_series_knowledge(series_id) -> None`
- `delete_book_knowledge(series_id, book_index) -> KnowledgeBase`

---

## Phase 1: Models + Store

**Goal**: Data layer only. No LLM calls, no network.

Files created:
- `src/knowledge/__init__.py`
- `src/knowledge/models.py`
- `src/knowledge/store.py`

Files modified:
- `src/config.py` — add `knowledge_dir: Path = Path("./knowledge")`, `extraction_model: str = "claude-haiku-4-5-20251001"`
- `.gitignore` — add `knowledge/`
- `.env.example` — add `EXTRACTION_MODEL=claude-haiku-4-5-20251001`

Test: `tests/manual/test_knowledge_store.py`
- Save + load roundtrip
- `filter_to_progress` with all three book statuses, verifying event truncation
- `is_chapter_extracted` correctness
- `delete_book_knowledge` removes only the right entries

---

## Phase 2: Extraction Pipeline

**Goal**: Claude-powered chapter extraction. Testable standalone.

Files created:
- `src/knowledge/extractor.py` — `extract_chapter(chapter, book_index, chapter_index, kb, client, settings) -> ChapterExtraction`
- `src/knowledge/merger.py` — `merge_extraction(kb, extraction, book_index, chapter_index) -> KnowledgeBase`
- `src/knowledge/pipeline.py` — `extract_book_knowledge(chapters, series_id, book_index, client) -> KnowledgeBase`

**`pipeline.py`** processes chapters sequentially (earlier chapters build the alias registry that later chapters use). Saves KB after each chapter for crash recovery. Skips already-extracted chapters.

Test: `tests/manual/test_extractor.py`
- Extraction with tool_use on a short hardcoded chapter text
- Merger: new character, existing character update, alias deduplication
- Merger: relationship deduplication by unordered pair
- Live: extract first 3 chapters of a real book, verify alias_registry is populated

---

## Phase 3: Extract Endpoint + Cleanup

**Goal**: Wire extraction into the API as an explicit user action. **Upload remains unchanged.**

### New endpoint

```
POST /library/series/{series_id}/books/{book_index}/extract
```

- Reads epub from `uploads/{series_id}/book_{book_index}.epub`
- Parses chapters (reuses `parse_epub()`)
- Calls `extract_book_knowledge()`
- Response: `{ series_id, book_index, characters_found, summaries_generated, relationships_found }`

If the epub file doesn't exist (book was deleted): 404. If the book has no chapters yet extracted: runs all. If some chapters already extracted: skips them (idempotent).

### Delete handler changes (`src/main.py`)

- `delete_series`: add `delete_series_knowledge(series_id)`
- `delete_book`: add `delete_book_knowledge(series_id, book_index)`

### Knowledge status in library response

`GET /library` response now includes a computed `knowledge_extracted: bool` per book, derived by checking `is_chapter_extracted` against the last chapter. This is computed at the API layer — `Book` model in `library.json` is unchanged.

Test: `tests/manual/test_extraction_pipeline.py`
- POST /extract for a real book, verify knowledge.json created
- Re-run POST /extract, verify chapters not re-extracted (idempotent)
- DELETE book, verify knowledge entries removed

---

## Phase 4: Enhanced Query Engine

**Goal**: Use all three knowledge layers at query time. Add conversation history.

### Question classifier (`src/query/classifier.py`)

```python
class QuestionType(str, Enum):
    CHARACTER = "character"           # "Who is X?"
    CHARACTER_ARC = "character_arc"   # "X's journey so far"
    RELATIONSHIP = "relationship"     # "History between X and Y"
    RECAP = "recap"                   # "What happened in..."
    WORLD_BUILDING = "world"          # "How does X work?"
    CAUSAL = "causal"                 # "Why did X do Y?"
    DETAIL = "detail"                 # Fallback
```

`classify_question(question) -> QuestionType`: heuristic patterns first (instant, free). If heuristics return DETAIL on a question that looks complex (> 10 words, no clear match), make a single lightweight LLM call to classify. This hybrid approach handles both clear and ambiguous questions correctly.

`extract_entity_mentions(question, alias_registry) -> list[str]`: scan question for known aliases (lowercased), return canonical names. Longest-match-first to handle "Darrow of Lykos" before "Darrow".

### Context builder (`src/query/context_builder.py`)

`build_entity_context(question_type, entity_mentions, kb, max_tokens) -> str`

Strategy per type:

| Type | Primary context | Secondary |
|---|---|---|
| CHARACTER | Full profile for mentioned chars | World facts about their faction |
| CHARACTER_ARC | Full key_events for char, chapter summaries they appear in | — |
| RELATIONSHIP | Relationship entry with all moments | Both character profiles |
| RECAP | Chapter summaries for parsed range | Characters present in those chapters |
| WORLD_BUILDING | Matching world_facts | Related character affiliations |
| CAUSAL | Character key_events + relationships for involved parties | Chapter summaries around the event |
| DETAIL | Minimal — just character names/descriptions | — |

**Token budget**: estimate tokens as `len(text.split()) * 1.4`. If entity context exceeds 2500 tokens, truncate in order: first drop minor world facts (< 50 words), then truncate `key_events` to most recent 10 per character, then truncate `moments` to most recent 5 per relationship.

`parse_recap_range(question, series) -> tuple[int, int, int, int] | None` — parse ranges like "Book 1", "chapters 10-15", "so far" from natural language.

### Enhanced prompt builder (`src/query/prompt_builder.py`)

Add optional params (backwards compatible — existing call sites unchanged):

```python
def build_prompt(
    question: str,
    chunks: list[SearchResult],
    series: Series,
    entity_context: str | None = None,
    question_type: QuestionType | None = None,
) -> str:
```

Prompt structure when entity_context is present:

```
You are a spoiler-safe reading companion for the "{series.name}" series.
Answer based ONLY on the knowledge and passages below. Never use outside knowledge.

Reading progress: {reading_summary}

Structured knowledge about the series so far:
{entity_context}

Supporting passages (for specific details):
{context_passages}  ← only included when relevant (see RAG strategy below)

{question_type_instruction}

Question: {question}
```

Question-type instructions:
- CHARACTER: "Provide a comprehensive character profile, drawing on the structured knowledge."
- CHARACTER_ARC: "Trace this character's journey chronologically from their first appearance to now."
- RECAP: "Give a detailed chronological recap of the events requested."
- RELATIONSHIP: "Describe the full history and evolution of this relationship."
- CAUSAL: "Explain the causal chain. Use the structured knowledge for context and the passages for specifics."
- WORLD_BUILDING / DETAIL: existing instruction (answer from context).

### RAG strategy changes

**Baseline improvement** (applies regardless of KB state):
- `top_k = 12` (was 5)
- Neighbor expansion: for each returned chunk, also fetch chunks at position ± 1 in the same chapter (deduplicated)

**KB-aware strategy**:
- CHARACTER / CHARACTER_ARC / RECAP: if KB is populated for these books, skip RAG retrieval (entity context + summaries are sufficient and more accurate)
- RELATIONSHIP: skip RAG if relationship entry exists
- CAUSAL / WORLD / DETAIL: always use RAG (chunks ground the answer in specific passages)

### Conversation history

`QueryRequest` gains:
```python
conversation_history: list[dict] = []
# Each dict: {"role": "user" | "assistant", "content": str}
```

The Claude API call changes from:
```python
messages=[{"role": "user", "content": prompt}]
```
to:
```python
messages=[*body.conversation_history, {"role": "user", "content": prompt}]
```

The frontend (Alpine.js in `src/static/index.html`) accumulates history in component state and sends it with each request. Max history depth: 6 turns (3 exchanges) to bound token usage. Backend is stateless.

### Modified query endpoint (`src/main.py`)

New flow:
1. Load KB → filter to reading progress
2. Classify question
3. Extract entity mentions from alias registry
4. Build entity context (with token budget)
5. Decide if RAG retrieval needed; if yes, `retrieve_chunks()` with new top_k + neighbor expansion
6. Build enriched prompt (with conversation history)
7. Claude answers

`QueryResponse` gains:
```python
question_type: str | None = None
entities_used: list[str] | None = None
```

Test: `tests/manual/test_enhanced_query.py`
- Classifier on 20+ example questions of each type
- Entity mention extraction against a populated KB
- Context builder output for each type
- `build_prompt` backwards compatibility
- Live: compare pure RAG vs enriched on "Who is [char]?", "Recap book 1", "[char]'s journey"
- Live: two-turn conversation ("Tell me about Darrow" → "What's his relationship with Sevro?")

---

## Phase 5: Frontend + Documentation

### Frontend updates (`src/static/index.html`)

- "Extract Knowledge" button per book, with progress indicator
- Knowledge status badge per book: "Knowledge ready" / "Not extracted"
- Show `question_type` as a subtle label on the answer
- Show `entities_used` as clickable name tags
- Conversation thread UI: show prior questions + answers in the session
- "Clear conversation" button

### Documentation

- ADR-005 in `docs/architecture/decisions.md`: Entity Knowledge Engine
- `docs/learnings/entity-extraction-notes.md`: prompt engineering learnings from extraction
- `docs/progress/phase-7-completion.md`: phase completion report

---

## Complete File Inventory

### New files (10)

| File | Phase | Purpose |
|---|---|---|
| `src/knowledge/__init__.py` | 1 | Package init |
| `src/knowledge/models.py` | 1 | Entity/knowledge Pydantic models |
| `src/knowledge/store.py` | 1 | JSON persistence + spoiler filtering |
| `src/knowledge/extractor.py` | 2 | Claude tool_use extraction per chapter |
| `src/knowledge/merger.py` | 2 | Merge extractions into KnowledgeBase |
| `src/knowledge/pipeline.py` | 3 | Book-level extraction orchestration |
| `src/query/classifier.py` | 4 | Question type + entity mention detection |
| `src/query/context_builder.py` | 4 | Entity context assembly with token budget |
| `tests/manual/test_knowledge_store.py` | 1 | Store tests |
| `tests/manual/test_extractor.py` | 2 | Extraction + merger tests |

### Modified files (5)

| File | Phases | Changes |
|---|---|---|
| `src/config.py` | 1 | Add `knowledge_dir`, `extraction_model` |
| `.gitignore` | 1 | Add `knowledge/` |
| `src/query/prompt_builder.py` | 4 | Add `entity_context`, `question_type` params |
| `src/main.py` | 3, 4 | Extract endpoint, delete cleanup, enhanced query flow |
| `src/static/index.html` | 5 | Extract button, knowledge status, conversation UI |

---

## Verification

**After Phase 1**: `poetry run python tests/manual/test_knowledge_store.py` — all assertions pass.

**After Phase 2**: `poetry run python tests/manual/test_extractor.py` — extraction produces structured output, merger deduplicates characters by alias.

**After Phase 3**:
1. Upload a book via `POST /library/series/{id}/books`
2. Confirm `knowledge/{id}.json` does NOT exist yet (decoupled)
3. POST `/library/series/{id}/books/0/extract` — confirm `knowledge/{id}.json` created with characters
4. Re-run extract — confirm no duplicate summaries (idempotent)
5. DELETE book — confirm knowledge entries removed

**After Phase 4** (the payoff):
1. Set status to READING at chapter 20 of Book 2
2. Ask "Who is Sevro?" — verify structured profile, not random chunks
3. Ask "Recap Book 1" — verify chronological summary from chapter summaries
4. Ask "What's the relationship between Darrow and Cassius?" — verify relationship arc
5. Ask "Trace Darrow's journey so far" — verify character arc with key events
6. Follow up with "How did that change him?" — verify conversation history is used
7. Advance to COMPLETED — ask same questions, verify more content is included
8. Compare answer quality against a fresh series with no knowledge extracted (pure RAG)
