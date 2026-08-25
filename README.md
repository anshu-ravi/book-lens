# BookLens

A spoiler-free reading companion. Upload a series, say how far you've read, and ask it anything — the answer is built only from text at or before your reading position, across every book in the series.

Ask "why doesn't she trust him?" halfway through book two and you get an answer grounded in the two thousand paragraphs you have actually read, with citations you can click back to. Nothing from chapter forty leaks into an answer about chapter twelve.

## The one invariant

> No token above the reader's cutoff is ever placed in an answering model context, for any reason, at any stage.

This is a property of the retrieval layer, not a behaviour of the model. "Be careful not to spoil" is not an implementable instruction, and any design that relies on a model choosing to withhold something it can already see is a broken design.

So the cutoff lives in the `WHERE` clause. Every paragraph carries the `global_seq` at which it became knowable — a single ordering that runs across the whole series, not per book — and every query that feeds an answer is bounded by `WHERE global_seq <= :ceiling`. The ceiling comes from session state on the server and is never an argument the model can supply. A dedicated invariant test suite asserts the boundary directly against the corpus rather than trusting review.

When a request gets clamped, the tool layer returns `{"truncated_at": "...", "reason": "reading position"}` — enough for the model to know a boundary exists, never enough to learn what is past it. Counts of unknown things are never displayed: absence has to be invisible, because "2 of 5 aliases known" is itself a spoiler.

## How it answers

There is no vector database and no retrieval step. The answering context is the entire readable set, raw, oldest-first.

```
EPUB ──► batch ingest ──► index.db ──► bounded tools ──► context assembly ──► model ──► answer
                              ▲             ▲                    ▲
                        every row tagged  ceiling injected   the whole readable
                        with global_seq   server-side        set, raw, oldest-first
```

The compression argument for summarising a book into digests assumed context was the scarce resource. At a million tokens for cents, it isn't: a full novel is around 166k tokens, two are 366k, and a six-book series is roughly 1.05M — reachable only by someone who has finished it, at which point there is nothing left to bound. Handing the model the actual prose instead of a summary of it also removes a whole class of leak, since there is no derived artifact whose sequence tag could be subtly wrong.

The prompt is assembled oldest-first with an explicit cache breakpoint at the cutoff, so the stable prefix — the text you've read, plus the system instructions — is cached across turns and only the conversation tail is re-sent.

Citations resolve to raw paragraph IDs and render as footnotes beside the text, each one anchored to a position on the reading bar so you can see where in the book an answer came from.

## The app

A local web UI — SvelteKit built to a static SPA, served by the same FastAPI process that serves the API. One user, one machine, one process.

- **Library** — shelves by series, progress per book, covers pulled from the EPUB, optional read-only Goodreads shelf sync for ratings and dates.
- **Upload** — drop an EPUB, confirm what the library already worked out about it, set where you are.
- **Chat** — saved conversations grouped by book, with the reading bound drawn rather than described.
- **Stats** — a grid of small charts over your reading history.

There's a full CLI too, which is where everything gets built and debugged first:

```bash
booklens ingest book1.epub book2.epub --series my-series
booklens progress book1 --status reading --chapter 20
booklens chat --book book1 --chapter 20 --debug
booklens serve
```

Plus `books`, `chapters`, `positions`, `read`, `search`, `first-seen`, `context`, `status`, `credits`, and `goodreads sync`. Every bounded tool is exposed as a subcommand, so you can check what the model would have been allowed to see.

## Getting started

Requires Python 3.11+ and Node 20+ for the frontend build.

```bash
pip install -e ".[dev]"
export OPENROUTER_API_KEY=...        # or put it in .env

cd web/frontend && npm install && npm run build && cd -

booklens ingest ~/Books/first.epub ~/Books/second.epub --series my-series
booklens serve                        # http://127.0.0.1:8000
```

Ingest runs once per book, front-to-back, offline and resumable, and makes no model calls at all — it's pure parsing. EPUB extraction is a ladder of independent strategies tried in order, each with its own applicability check, and the tier that worked is recorded in the book's manifest. Extractors fail loudly: a tier that resolves zero documents raises rather than returning an empty result, so a parser bug can never masquerade as a structural quirk in the book.

Spine order is the only ground truth for sequence. Chapter numbers in titles routinely disagree with document order once prologues, interludes, and part headers are in play, so they're never parsed for ordering.

## Storage

| File | What it is |
|---|---|
| `data/progress.db` | Your reading positions and settings. **Precious** — the only thing worth backing up. |
| `data/index.db` | Parsed text and FTS5 index. A rebuildable cache: `booklens reindex`. |
| `data/goodreads.db` | Cached shelf data, kept separate so a reindex can't destroy it. |

SQLite throughout, FTS5 for lexical search, no separate services. `data/` and `uploads/` are gitignored — derived text is a derivative work of a copyrighted book, and it stays on the machine that made it. Your EPUB files are read-only input and are never moved or modified.

## Stack

Python 3.11, FastAPI, SQLite + FTS5. `zipfile` + `lxml` for EPUB parsing. SvelteKit 2 / Svelte 5 with `adapter-static` for the UI. OpenRouter (`openai/gpt-5.6-luna`) as the default provider behind a small `LLM` protocol, with a Claude Agent SDK adapter as an alternative. `OPENROUTER_API_KEY` is read from the environment, never from disk by tooling.

## Tests

```bash
pytest                    # 720 tests
pytest -m realmodel       # opt-in, makes real provider calls
```

The mechanical invariant tests — cutoff, causality, corpus, readable ranges — run on every commit and are not deferred. They're the part of spoiler safety that can be proven rather than eyeballed.

## Design notes

`DECISIONS.md` records what was decided and why, including the things that were built and then superseded: the digest pyramid, three-level spoiler strictness, and a budget-filled-backwards context assembly that was rejected before it was written. It's the useful document in this repo.

## Scope

**In:** one series at a time, multiple books, per-book progress, cross-book questions within a series.

**Out, deliberately:** cross-*series* knowledge, hosted multi-user, non-EPUB formats, DRM.
