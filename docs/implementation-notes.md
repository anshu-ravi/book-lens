# Implementation notes

Long-form explanation that would otherwise bloat the source files. `DECISIONS.md` records what was decided and why; this records how the code actually implements it, and where the implementation is knowingly narrower than the design.

## How the cutoff is enforced

Retrieval filters on **readable ranges**, not a single ceiling. `Tools.__init__` computes `progress.readable_ranges(pconn, iconn)` and loads it into a uniquely-named temp table, `readable_range_<uuid4().hex>(lo, hi)`, on the index connection (see "The temp table is owned by the instance, not the connection" below for why the name is per-instance). Every query in `booklens/tools.py` that reads `para` or `chapter` carries `AND EXISTS (SELECT 1 FROM <that table> r WHERE <seq column> BETWEEN r.lo AND r.hi)` plus `kind != 'excerpt'`, both in the `WHERE` clause. No method pulls an unbounded result set into Python and filters it there. A reviewer should be able to confirm safety by reading the SQL alone. An empty readable-range table (nothing read yet) makes every `EXISTS` false everywhere — there is no fallback that opens the corpus when it's empty.

`self._ceiling` (from `progress.ceiling_for`) is still captured, for things that legitimately need a single series-wide scalar rather than a range. It is **not** what any query filters on anymore, and it is the wrong value to use for naming a chapter in one specific book (see below).

No method takes the ceiling, or a range, as a parameter — a caller (or a model choosing tool arguments) has no way to raise, disable, or replace it. `tests/test_cutoff_invariant.py` asserts this with `inspect.signature` over every public method.

The CLI routes every retrieval subcommand through `Tools` for the same reason. Ad-hoc SQL in the CLI would create a second, unbounded path to the text.

### The temp table is owned by the instance, not the connection

Each `Tools.__init__` generates its own table name, `readable_range_<uuid4().hex>`, stored as `self._table` and validated against `_TABLE_NAME_RE` before being interpolated into SQL. Every query that used to reference the shared `readable_range` table now references `self._table` instead. This means two `Tools` instances built over the same `iconn` — at different times, or alive simultaneously — each get their own bounds and cannot interfere with each other, no matter what order they're constructed, queried, or closed in.

This matters because the safety property has to hold **by construction**, not by a caller remembering a rule. A single connection shared across two requests is exactly what happens at Phase 4 behind a web server, and "construct one `Tools` per request and never hold an older instance across a progress-state change" is not something a caller can be trusted to always get right — especially under concurrency, where two readers' requests can genuinely interleave on one connection. Making the table per-instance turns a caller discipline into an invariant: nothing the caller does with one `Tools` object can affect another's bounds.

`close()` drops the instance's own table (`DROP TABLE IF EXISTS temp.<name>`) and is idempotent. `Tools` also works as a context manager (`__enter__`/`__exit__` calls `close()`). Calling `close()` is optional — an un-closed `Tools` remains fully correct, since sqlite temp tables just live for the life of the connection; `close()` only matters for tidiness in a long-lived connection that constructs many `Tools` over its life (e.g. a server process). `booklens/cli.py` uses the context-manager form since each subcommand's `Tools` has an obvious, short lifetime scoped to a single `with` block.

### Naming a chapter the reader has actually reached

Truncation markers (`truncated_at`) must name a chapter *in the same book* the reader has reached — not the highest chapter readable anywhere in the series. `Tools._book_ceiling(book_id)` reads that one book's own `ceiling_seq` from `progress.get_progress` for this purpose. Using the old series-wide `self._ceiling` here would have been a real leak under the union model: a reader who skipped book 2 but finished book 3 would see book 2's last chapter title surface as a `truncated_at` marker, because book 2's chapters all sit below book 3's (much higher) ceiling.

## Current position vs. spoiler ceiling

Two separate ideas, kept apart in `progress.py`:

- **Current position** (`status`, `position_chapter_idx`) is where the reader physically is right now. It can move backward freely — someone re-reading chapter 3 is "at" chapter 3.
- **Spoiler ceiling** (`ceiling_seq`) is a watermark of what the reader has been exposed to. It only moves forward, because knowledge doesn't un-happen. A reader who finished book 3 and flips back to re-read book 1 still knows book-3 material. Only `reset_ceiling` can lower it, and that is an explicit user action.

## `readable_ranges` is a true union

Each book with progress contributes `[book_order * 1_000_000, ceiling_seq]` — its own floor, not zero — so a reader who finished book 3 but skipped book 2 gets two disjoint ranges, and book 2's paragraphs sit in the gap between them, unreachable by any tool. Unread books, and any book whose `ceiling_seq` hasn't reached its own floor, contribute nothing. Adjacent or overlapping per-book ranges still merge (this basically never happens between two different books in practice, since a book's real content ends far short of the next book's `1_000_000`-wide floor, but the merge step is still correct if it did).

`ceiling_for` (the single max-across-books scalar) still exists and is still useful for "how far has this reader got" display purposes, but it is no longer what retrieval filters on — see "How the cutoff is enforced" above.

## Context expansion is not chapter-scoped, but is book-scoped

`context()` runs separate backward and forward queries, each independently bounded by readable-range membership and by `book_id = :book_id`. A wide window can legitimately reach backward across a chapter boundary into earlier content in the *same* book — safe, since all of it is already readable — while never reaching forward past the reader's position in that book, and never crossing into a different book at all (readable or not). The `book_id` scoping is what actually prevents tunnelling into an earlier skipped book; the range-membership check is what prevents tunnelling past an in-book gap. Do not assume chapter-scoping when building UI on top of it.

## Error behaviour in the tool layer

`context()` raises `ValueError` on an unknown or malformed citation id, because silently returning a neighbouring paragraph would corrupt citations. Every other method returns a clean empty or error-shaped dict rather than raising, so that adversarial arguments produce no tracebacks.

## Where the invariant could still be reached

`Tools.__init__` trusts the `pconn` it is handed. A caller that can write arbitrary `ceiling_seq` values into `book_progress` before constructing `Tools` can set any ceiling it likes. Keeping write access to `progress.db` away from the model is session management's job, not the tool layer's. Whoever wires up the agent loop must ensure the model never gets direct SQL access to `progress.db`.

## Label ladder coverage thresholds

`labels.py` uses `L1_MIN_COVERAGE = 0.5`, `L2_MIN_COVERAGE = 0.3`, `L3_MIN_COVERAGE = 0.2`. Each cleanly separates the "tier works" cluster from the "tier collapses" cluster in the measured corpus data recorded in the Ingestion section of `DECISIONS.md`.

Hero of the Ages remains the ladder's hard case. Its NCX carries two overlapping navigation sets, including a malformed block with no separator between the part word and the title, which reproduces the non-monotonic structure `DECISIONS.md` describes. L1 fails its coverage check and chapters fall to L4 (one per document), but the well-formed part entries still compose on top, giving `L1+L4` — degraded chapter granularity with correct part-level orientation.

Part markers are spelled as words in the Mistborn conversions (`PART ONE`, not `PART 1` or `PART I`), which is why `parse_marker` carries a word-number map.

## The LLM provider layer

`booklens/llm/` is a thin, provider-agnostic completion boundary. `get_provider()` reads `BOOKLENS_LLM_PROVIDER` and defaults to `fake` — an unconfigured environment can never accidentally spend real quota, since a real provider must be opted into explicitly by name or env var.

`BudgetedLLM` wraps any `LLM` and enforces a hard `max_calls` ceiling, raising `BudgetExceeded` rather than silently truncating output — a half-built digest set that looks complete is worse than a crash. It also owns bounded retry: `TransientLLMError` (network, rate limit, overload) retries with exponential backoff up to `max_retries`, while `FatalLLMError` (bad auth, malformed request) never retries, since those never succeed on a second attempt. Every retry attempt still increments `calls_made`, so a flaky provider cannot bypass the budget by failing and retrying indefinitely.

`ClaudeSDKProvider` imports `claude_agent_sdk` lazily, inside its constructor, so `import booklens.llm` and the whole test suite work without the package installed — it is an optional `llm` extra in `pyproject.toml`, not a hard dependency. Before every call it strips `ANTHROPIC_API_KEY` from the environment it hands to the SDK and logs a one-line warning if the key was present: if left set, the key silently wins over subscription OAuth and the user pays API rates while believing they're on their Claude plan (see `DECISIONS.md` section 12). This is tested by injecting a dummy key via `monkeypatch.setenv` and asserting it never appears on the `ClaudeAgentOptions.env` a mocked SDK call receives.

The real `claude-agent-sdk` surface has no synchronous `complete()` call — it exposes an async `query(prompt, options)` that yields a stream of messages, driven here with `asyncio.run` around an internal collector. Assistant text arrives as `TextBlock`s inside `AssistantMessage.content` and is concatenated in order; token usage is read defensively off whichever message (`AssistantMessage` or the trailing `ResultMessage`) actually carries a `usage` dict, falling back to `None` rather than inventing a count. `query()` takes one prompt string, not a message list, so multi-turn input is flattened into a single role-labelled string — fine for Phase 1's single-shot digest use, not a general chat transport.

Every call sets `allowed_tools=[]`, `max_turns=1`, `setting_sources=[]`, and `skills=[]` on `ClaudeAgentOptions`, so this adapter can never let the model run tools, take a second turn, or pick up the user's own Claude Code settings/CLAUDE.md files — ambient context would make a generated digest unreproducible even though `manifest.json` records a prompt hash on the assumption the prompt is the whole input. `setting_sources=[]` is what actually means isolation here; per the SDK's own docstring, `None` means "load everything" (`~/.claude/settings.json`, project `.claude/settings.json` and `.claude/settings.local.json`, and CLAUDE.md files) and matches the CLI's own defaults — the naive reading of `None` as "nothing" is backwards, so the construction site carries a comment recording this. `max_tokens` and `temperature` are accepted for protocol compatibility but are not exposed by `query()`; passing a non-default value logs a warning rather than being silently dropped. `tests/test_llm_claude_sdk.py` mocks the whole `claude_agent_sdk` module tree (including `.types`) with classes matching the real field names, and carries one `pytest.importorskip("claude_agent_sdk")` conformance test that asserts, via `inspect.signature`, that `query` and `ClaudeAgentOptions` still match what the adapter assumes — it skips in this venv (the SDK isn't installed) but fails loudly the moment someone installs the extra against a drifted API.
