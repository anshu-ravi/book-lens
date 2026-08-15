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

- Do not illustrate designs with real reveals from books the user is mid-way through.
- **The Stormlight Archive is off-limits as an example source.** The user is mid-way through *Words of Radiance* and it is not the dev corpus. Do not use it in fixtures, docstrings, eval cases, or design examples.
- Do not rely on parametric knowledge of any book for test data. Pull from the text via bounded tools, or invent.
- The audit pass must run on all assistant output, not just answers to book questions.

## Development corpus

Use books the user has **finished**, so that a leak during development costs nothing.

**Primary: Red Rising #1–2** — `Red rising _ Book I of The Red Rising Trilogy.epub` and `Golden Son_ Book 2 of the Red Rising Saga -- Pierce Brown.epub`.

**Secondary: Mistborn #1–2** — `The Final Empire (Mistborn, Book 1) ... .epub` and `The Well of Ascension _ book two of Mistborn -- Sanderson, Brandon.epub`.

Both live in `~/Documents/Books/Fiction:NonFiction/` and are read-only input.

Two books is the minimum that exercises the cross-book series logic — `global_seq` across volumes, per-book progress state, the union-of-ranges readable set, and book-level digest rollup. Use both. Mistborn additionally has chapter epigraphs, which is a useful second shape for the ingest parser.

Eval golden sets can quote these books freely, including post-cutoff material, because the point of a golden set is to assert that the app *doesn't* surface it.

## Architecture in one screen

```
EPUB ──► one-time batch ingest ──► index.db + digests/ ──► bounded tool layer ──► agent ──► audit ──► answer
                                          ▲                        ▲
                                    every row tagged          ceiling injected
                                    with global_seq           server-side
```

- **Ingest** runs once per book, front-to-back, offline, resumable. Not lazy, not on-demand.
- **Tools** apply `WHERE global_seq <= :ceiling` in SQL. The ceiling comes from session state and is *never* a model-supplied argument.
- **Agent** reads digests to orient, then drills into raw paragraphs to answer.
- **Audit** checks every factual claim against retrieved **raw text only** — never against digests.

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

Python. `zipfile` + `lxml` for EPUB (skip `ebooklib`, it's thin over the same thing). SQLite with FTS5 for storage and lexical search. Claude Agent SDK for the agent loop, behind a provider abstraction so OpenRouter can be swapped in. FastAPI + HTMX or a small React front end at Phase 4.

Do not add a vector database. If semantic search is needed, use `sqlite-vec` in the same file, as a ranking aid inside `search` — never as a substitute for reading the text. See section 5 of `DECISIONS.md` for why.

## Build order

- **Phase 0** — ingest + schema + bounded tools + cutoff invariant tests. CLI only. Run against the dev corpus (Red Rising #1–2).
- **Phase 1** — progress model, multi-book, the progressive digest + entity pass.
- **Phase 2** — citation-grounded generation, entailment auditor, strictness settings, both eval harnesses.
- **Phase 3** — first-appearance index, cast screen, hybrid retrieval, session recaps.
- **Phase 4** — local web UI.

Build the eval harnesses in Phase 2, not last. Spoiler safety cannot be eyeballed.
