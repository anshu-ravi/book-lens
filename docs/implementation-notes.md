# Implementation notes

Long-form explanation that would otherwise bloat the source files. `DECISIONS.md` records what was decided and why; this records how the code actually implements it, and where the implementation is knowingly narrower than the design.

## How the cutoff is enforced

The ceiling is captured once, in `Tools.__init__`, from session state via `progress.ceiling_for`. It is deliberately not a parameter of any public method, so a caller — or a model choosing tool arguments — has no way to raise it, disable it, or pass a different one in. `tests/test_cutoff_invariant.py` asserts this with `inspect.signature` over every public method.

Every query in `booklens/tools.py` carries its own `global_seq <= :ceiling` (or `start_seq`/`end_seq <= :ceiling`) predicate plus `kind != 'excerpt'`, both in the `WHERE` clause. No method pulls an unbounded result set into Python and filters it there. A reviewer should be able to confirm safety by reading the SQL alone.

The CLI routes every retrieval subcommand through `Tools` for the same reason. Ad-hoc SQL in the CLI would create a second, unbounded path to the text.

## Current position vs. spoiler ceiling

Two separate ideas, kept apart in `progress.py`:

- **Current position** (`status`, `position_chapter_idx`) is where the reader physically is right now. It can move backward freely — someone re-reading chapter 3 is "at" chapter 3.
- **Spoiler ceiling** (`ceiling_seq`) is a watermark of what the reader has been exposed to. It only moves forward, because knowledge doesn't un-happen. A reader who finished book 3 and flips back to re-read book 1 still knows book-3 material. Only `reset_ceiling` can lower it, and that is an explicit user action.

## Phase 0 simplification: `readable_ranges` is not yet wired in

The readable set is properly a union of per-book ranges, because a reader can skip a volume or read out of order. `readable_ranges` exists for that, but the tool layer does **not** consume it — it uses `ceiling_for`, a single scalar equal to the maximum ceiling across all books.

For a linear read-through this is strictly conservative and therefore safe: `global_seq` increases monotonically across the series, so "everything at or below the max ceiling" is a single contiguous window.

Two things a Phase 1 reader must not assume:

1. **The two are not equivalent in general.** The skip-then-read-ahead case — finished book 3, never read book 2 — is representable in `progress.db` but is not honoured by retrieval. Book 2 sits below book 3's ceiling and would be served.
2. **`readable_ranges` as currently written cannot express that case either.** It computes `[0, ceiling]` per book and merges, which always collapses to a single range. To be a real union it needs each book's range to start at that book's own `book_order * 1_000_000`. This is a known gap, deferred rather than solved.

## Context expansion is not chapter-scoped

`context()` runs separate backward and forward queries, each independently bounded by the ceiling. A wide window can legitimately reach backward across a chapter boundary into earlier content — safe, since all of it is already below the ceiling — while never reaching forward past the ceiling. Do not assume chapter-scoping when building UI on top of it.

## Error behaviour in the tool layer

`context()` raises `ValueError` on an unknown or malformed citation id, because silently returning a neighbouring paragraph would corrupt citations. Every other method returns a clean empty or error-shaped dict rather than raising, so that adversarial arguments produce no tracebacks.

## Where the invariant could still be reached

`Tools.__init__` trusts the `pconn` it is handed. A caller that can write arbitrary `ceiling_seq` values into `book_progress` before constructing `Tools` can set any ceiling it likes. Keeping write access to `progress.db` away from the model is session management's job, not the tool layer's. Whoever wires up the agent loop must ensure the model never gets direct SQL access to `progress.db`.

## Label ladder coverage thresholds

`labels.py` uses `L1_MIN_COVERAGE = 0.5`, `L2_MIN_COVERAGE = 0.3`, `L3_MIN_COVERAGE = 0.2`. Each cleanly separates the "tier works" cluster from the "tier collapses" cluster in the measured corpus data recorded in the Ingestion section of `DECISIONS.md`.

Hero of the Ages remains the ladder's hard case. Its NCX carries two overlapping navigation sets, including a malformed block with no separator between the part word and the title, which reproduces the non-monotonic structure `DECISIONS.md` describes. L1 fails its coverage check and chapters fall to L4 (one per document), but the well-formed part entries still compose on top, giving `L1+L4` — degraded chapter granularity with correct part-level orientation.

Part markers are spelled as words in the Mistborn conversions (`PART ONE`, not `PART 1` or `PART I`), which is why `parse_marker` carries a word-number map.
