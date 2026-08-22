# book-lens-v2

A spoiler-free reading companion. You upload a book (EPUB), set how far you've read, and ask questions about it. Answers are built **only** from text at or before your reading position, across every book in the series.

Read `DECISIONS.md` before doing any design work. It records what was decided, and — more importantly — *why*. Do not re-litigate settled decisions; if you think one is wrong, say so explicitly and wait.

## The one invariant

> No token above the reader's cutoff is ever placed in an answering model context, for any reason, at any stage.

Every derived artifact (digest, entity edge, attribute) must be tagged with the `global_seq` at which its content became knowable, and must have been generated from a context containing nothing above that seq.

This is a property of the **retrieval layer**, not a behavior of the model. "Be careful not to spoil" is not an implementable instruction. If a design ever relies on the model choosing to withhold something it can see, the design is wrong.

## The spoiler guard applies to conversations about the app, too

This was learned the hard way: during the design session that produced this project, the assistant spoiled a character reveal *while explaining the entity-graph design* — by describing what an edge in the graph would connect. The retrieval bound wasn't running, because it was "just architecture talk."

There is no meta mode. When working on this repo:

- Do not illustrate designs with real reveals from books the user has not finished.
- **The Stormlight Archive is off-limits as an example source.** The user has read through *Words of Radiance*; every volume after it is unread, and the series is not the dev corpus. Do not use it in fixtures, docstrings, eval cases, or design examples.
- Do not rely on parametric knowledge of any book for test data. Pull from the text via bounded tools, or invent.
- The audit pass must run on all assistant output, not just answers to book questions.

## Development corpus

Use books the user has **finished**, so that a leak during development costs nothing.

**Primary: Red Rising #1–3** — `Red rising _ Book I of The Red Rising Trilogy.epub`, `Golden Son_ Book 2 of the Red Rising Saga -- Pierce Brown.epub`, and `Morning Star -- Pierce Brown.epub`. All three are ingested under series `red-rising`, in that order.

**Secondary: Mistborn #1–2** — `The Final Empire (Mistborn, Book 1) ... .epub` and `The Well of Ascension _ book two of Mistborn -- Sanderson, Brandon.epub`.

Both live in `~/Documents/Books/Fiction:NonFiction/` and are read-only input.

Two books is the minimum that exercises the cross-book series logic — `global_seq` across volumes, per-book progress state, the union-of-ranges readable set, and book-level digest rollup. Use both. Mistborn additionally has chapter epigraphs, which is a useful second shape for the ingest parser.

Eval golden sets can quote these books freely, including post-cutoff material, because the point of a golden set is to assert that the app *doesn't* surface it.

## Architecture in one screen

```
EPUB ──► one-time batch ingest ──► index.db ──► bounded tool layer ──► context assembly ──► model ──► audit ──► answer
                                       ▲                 ▲                    ▲
                                 every row tagged   ceiling injected    the whole readable
                                 with global_seq    server-side         set, raw, oldest-first
```

- **Ingest** runs once per book, front-to-back, offline, resumable. Not lazy, not on-demand.
- **Tools** apply `WHERE global_seq <= :ceiling` in SQL. The ceiling comes from session state and is *never* a model-supplied argument.
- **Context assembly** puts the *entire* readable set in context, raw, oldest-first. No digests, no retrieval step. See `DECISIONS.md` section 7 — it supersedes the digest pyramid, and the digest and entity passes are dormant.
- **Audit** checks every factual claim against the assembled **raw text only**.

## How work gets done

> **Scope of this section: it governs the top-level agent only.**
> If you are a subagent, this section does not apply to you. You were dispatched to do the work — do it yourself, directly, with your own tools. Do not delegate onward, do not spawn further subagents, and do not treat "implementation is delegated" as an instruction to hand the task back. Write the code.

**Implementation is always delegated to a Sonnet 5 subagent.** The top-level agent owns reasoning, design, decomposition, review, and communication with the user. It does not write implementation code itself.

Before dispatching, the top-level agent must give the subagent a brief that stands on its own:

- The exact files to create or modify.
- The contract — signatures, schema, return shapes, error behaviour.
- Which invariants apply (almost always the cutoff filter; see below).
- How to verify — the tests to write or run, and what passing looks like.
- What is out of scope for that task.

A subagent should never have to infer the design. If the brief isn't specific enough to implement against without guessing, it isn't ready to dispatch.

**Use parallel subagents where the work genuinely splits.** Independent modules with no shared files — ingest parser, tool layer, eval harness — are good candidates. Do not manufacture parallelism: if tasks touch the same files, depend on each other's output, or need a shared decision that hasn't been made yet, run them sequentially. Two well-briefed sequential subagents beat four that conflict. Serial is the default; parallel is the exception you justify.

**After a subagent returns, the top-level agent reviews the work** against the invariants and the brief before moving on. Delegation is not abdication — a returned diff that violates the cutoff invariant is the top-level agent's error, not the subagent's.

**Feature development follows the `/git-workflow` skill, with one change: merge directly to the main branch instead of opening a PR.** Everything else in that skill — branching, commit discipline, checks before merge — applies as written.

## Non-negotiables when writing code here

- The cutoff filter goes in the `WHERE` clause. Not in post-processing, not in a helper the caller can skip, not behind a boolean flag.
- Tools return `{"truncated_at": "...", "reason": "reading position"}` when a request was clamped, so the model knows a boundary exists without learning what's past it.
- Citations resolve to raw paragraph IDs. A digest is never a citable source — it is model-generated and outside the trust boundary.
- Never display counts of unknown things ("2 of 5 aliases known"). Absence must be invisible.
- Spine order is the only ground truth for sequence. Never parse ordering out of chapter titles.
- Extraction is a **ladder of independent strategies tried in order**, not one universal parser. Each tier has its own applicability check and is separately testable; the tier used is recorded in `manifest.json`. See the Ingestion section of `DECISIONS.md` for the tiers and the measured evidence.
- Extractors fail loudly. A tier that resolves zero documents or matches zero chapters raises — it never returns an empty result, or a parser bug becomes indistinguishable from a real structural quirk.
- The user's EPUB files are read-only. Never move, modify, or write next to them.
- `progress.db` (user state) is precious. `index.db` and `digests/` are a rebuildable cache.

## Scope

**In:** one series at a time, multiple books, per-book progress, cross-book questions within the series.

**Out (deliberately deferred):** cross-*series* knowledge (the Cosmere problem), hosted multi-user, non-EPUB formats, DRM.

## Stack

Python. `zipfile` + `lxml` for EPUB (skip `ebooklib`, it's thin over the same thing). SQLite with FTS5 for storage and lexical search. **OpenRouter with `openai/gpt-5.6-luna` is the default provider**, behind the existing `LLM` protocol; the Claude Agent SDK adapter stays as an alternative. FastAPI + HTMX or a small React front end at Phase 4.

`OPENROUTER_API_KEY` comes from the environment. Never read `.env` contents — key names may be enumerated, values never.

Do not add a vector database. If semantic search is needed, use `sqlite-vec` in the same file, as a ranking aid inside `search` — never as a substitute for reading the text. See section 5 of `DECISIONS.md` for why.

## Build order

- **Phase 0** — ingest + schema + bounded tools + cutoff invariant tests. CLI only. Run against the dev corpus (Red Rising #1–2). *Done.*
- **Phase 1** — progress model, multi-book. *Done.* The digest and entity passes also shipped here and are now dormant; see `DECISIONS.md` Appendix A.
- **Phase 2 — the core feature.** Split into two shipping steps:
  - **V1** — `booklens chat --book red-rising --chapter N`. Multi-turn terminal REPL, ceiling fixed at launch. Context assembly over the full readable set, OpenRouter provider, citation-grounded answers in conversational prose, `--debug` for tokens/cost/citations, `booklens credits`. One new mechanical test: the assembler never emits above the ceiling. Red Rising book 1 only. **Auditor, golden sets, and cross-book are deliberately out** — V1 exists to be *used*, and on a finished book a leak costs nothing while teaching us how bad parametric leakage actually is.
  - **V1.1** — Golden Son and Morning Star, and multi-book sessions: a chat session is a lens on one series, with earlier volumes whole and later ones absent. See `DECISIONS.md` section 20. *Done.*
- **Phase 4 — local web UI.** Library with progress bars, Upload, Chat. SvelteKit static SPA served by the same FastAPI process; see `DECISIONS.md` section 21.
- **Phase 3** — Story So Far / cast screen, first-appearance index, session recaps. Deferred behind the UI. Reviving this is what un-dormants the digest and entity passes.
- **V3** — the entailment auditor and both semantic eval harnesses, designed against real transcripts from a multi-book library rather than speculatively. See the amendment to `DECISIONS.md` section 14 for why they moved.

The mechanical invariant tests are not deferred and never were — they run on every commit. It is the *semantic* harness that waits for real usage. Spoiler safety still cannot be eyeballed; the bet is that the structural guarantee holds while the parametric one is measured later.
