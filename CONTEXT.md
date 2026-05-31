# BookLens

A spoiler-safe reading companion for book series. Readers upload EPUBs, set their chapter position, and ask questions — the system answers using only knowledge they've already encountered.

## Language

### Core reading model

**Reader Position**:
A per-book chapter number (integer) that marks how far the reader has progressed in a specific book. There is one Reader Position per book, not per series.
_Avoid_: reading progress, current chapter, bookmark

**Spoiler-safe**:
The constraint that the system only surfaces knowledge from: (a) all chapters of every Book whose Series Position is less than the reader's current Book, and (b) chapters up to and including the Reader Position in the current Book. Novellas (fractional Series Positions) follow the same rule — they are not special-cased.
_Avoid_: spoiler-free, spoiler-protected, safe mode

**Series**:
An ordered collection of Books that share a continuous narrative and knowledge graph. The series is the top-level unit of a reader's library.
_Avoid_: collection, library (library means something else — see below)

**Book**:
A single EPUB within a Series, with a known position (1st, 2nd, …) in the series order. A reader has one Reader Position per Book.
_Avoid_: novel, volume, title

**Chapter**:
The atomic unit of reading progress. Reader Position is always measured in chapters. Chapters are numbered sequentially within a Book starting from 0.
_Avoid_: section, part

### Knowledge Graph ingestion pipeline

**Extraction (Bronze Layer)**:
The first stage of Knowledge Graph ingestion. An LLM call processes each Chapter independently and extracts: characters, relationships, chapter summary, and identity reveals. The output is `chapters.json` — one raw extraction record per chapter.
_Avoid_: parsing, scraping, analysis

**Deduplication (Silver Layer)**:
The second stage. A rule-based pass over the Bronze output that merges character aliases into canonical names and produces the Canonical Registry. Example: "Reaper" and "Darrow" are resolved to a single character entry.
_Avoid_: merging, normalization, consolidation

**Ingestion (Gold Layer)**:
The third stage. The Canonical Registry is written into Neo4j as the live Knowledge Graph — Characters, Chapters, and Relationships nodes. This is the artifact that powers all reader-facing queries.
_Avoid_: indexing, loading, seeding

**Canonical Registry**:
The Silver Layer artifact (`canonical_registry.json`). A deduplicated, alias-resolved map of all entities extracted from a book's chapters. The authoritative input to Ingestion.
_Avoid_: entity registry, character list, canonical map

**Identity Reveal**:
A special extraction output where a character known by an alias is revealed to be an already-known character (e.g., "The Reaper" is revealed to be Darrow). The LLM tags the chapter where the reveal occurs during Extraction; this chapter index is stored on the `REVEALED_AS` edge in Neo4j and used at retrieval time to filter out the reveal until the Reader Position passes that chapter.
_Avoid_: alias reveal, identity twist, reveal

### Knowledge stores

**Knowledge Graph**:
The Neo4j store of structured series knowledge: character profiles, relationships between characters, world facts, and chapter summaries. Scoped per series, shared across all readers of that series.
_Avoid_: entity graph, graph database, KG

**Prose Index**:
The pgvector store of hierarchically-chunked text from the book prose. Scoped per reader and per book. Only Leaf Nodes are embedded; parent nodes are kept in the docstore for auto-merging during retrieval.
_Avoid_: vector index, RAG index, text index

**Node**:
The unit of storage in the Prose Index. Nodes are organized in a three-level token-size hierarchy (~2048 / ~512 / ~128 tokens). The levels are a useful proxy (chapter-ish / scene-ish / paragraph-ish) but the splits are purely token-based, not semantic. Only the smallest (leaf) nodes are embedded.
_Avoid_: chunk, passage, document, paragraph

**Query Router**:
The Gemini-powered classifier that inspects a question and conversation history, then selects the retrieval strategy: `graph` (Knowledge Graph only), `vector` (Prose Index only), or `hybrid` (both). Falls back to `hybrid` on error.
_Avoid_: classifier, intent detector, router

### Upload flow

**Book Metadata**:
The LLM-inferred, reader-confirmed information about a Book: canonical title, author, whether it belongs to a Series, the Series name, and the Book's Series Position. Sourced from the EPUB's DC metadata fields + a Gemini lookup, then confirmed by the reader before being persisted.
_Avoid_: book info, book details

**Series Position**:
A float that defines a Book's order within its Series (e.g., 1, 2, 2.5 for a novella). Set during upload via Book Metadata confirmation. Determines the "completed books" side of the Spoiler-safe boundary.
_Avoid_: book number, book order, index

### LLM roles

**Answer Model**:
The LLM used at query time to generate the reader's answer from retrieved context. Currently Gemini. Chosen for cost, speed, and rate limit headroom — not fixed; expected to change as models evolve.
_Avoid_: generation model, response model, chat model

**Extraction Model**:
The LLM used during ingestion to extract characters, relationships, summaries, and identity reveals from chapter text (Bronze Layer). Currently Gemini.
_Avoid_: ingestion model, parsing model

**Summary Fallback Model**:
Claude Haiku, used only during ingestion when no pre-extracted Gold Layer chapter summary exists. Not used at query time.
_Avoid_: fallback LLM, Claude model

**Embedding Model**:
Local sentence-transformers models run on CPU. Two variants: `BAAI/bge-small-en-v1.5` for prose Nodes, `all-MiniLM-L6-v2` for character descriptions. Local to avoid latency and cost of a hosted embedding API.
_Avoid_: encoder, vector model

### Actors

**Reader**:
An authenticated user of BookLens. Readers upload Books, set their Reader Position, and ask questions. The system currently serves a small, trusted circle (not the public). There is no formal Admin role — the owner operates admin-level tasks via CLI scripts.
_Avoid_: user, account, member

### Reader's library

**Library**:
The set of Series a specific reader has uploaded and is tracking. Library is reader-scoped, not global.
_Avoid_: bookshelf, collection
