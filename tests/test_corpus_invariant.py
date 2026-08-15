"""End-to-end proof of the spoiler cutoff and the excerpt quarantine against
REAL books -- every earlier invariant test (test_cutoff_invariant.py) used a
small synthetic lorem-ipsum fixture. This file is the first to prove the
guarantee holds against real publisher structure: real chapter counts, real
paragraph text, and -- the point of this file -- Red Rising's real "Excerpt
from Golden Son" back matter, which sits numerically inside Red Rising's own
global_seq range and would otherwise leak Golden Son's opening the moment a
reader marks Red Rising finished.

Ingest is slow (a few seconds per book), so the two-book series is built
once in a session-scoped fixture and reused by every test below.
"""

from __future__ import annotations

import random
import re

import pytest

from booklens import db, ingest, progress, tools

_CITATION_RE = re.compile(r"\b([a-zA-Z0-9_-]+):(\d+):p(\d+)\b")

QUERIES = ["the", "and", "was", "chapter", "said"]


# -- fixture: ingest the real two-book series once -------------------------


@pytest.fixture(scope="session")
def rr_series(tmp_path_factory, corpus):
    if "red-rising" not in corpus or "golden-son" not in corpus:
        pytest.skip("red-rising / golden-son not present in uploads/")

    d = tmp_path_factory.mktemp("corpus-invariant")
    iconn = db.connect_index(d / "index.db")
    pconn = db.connect_progress(d / "progress.db")

    r1 = ingest.ingest_book(corpus["red-rising"], series_id="red-rising-series", book_order=1, iconn=iconn)
    r2 = ingest.ingest_book(corpus["golden-son"], series_id="red-rising-series", book_order=2, iconn=iconn)

    assert r1.skipped is False
    assert r2.skipped is False
    assert r1.excerpt_paragraphs > 0, "fixture assumption: Red Rising has excerpt back matter"

    book1, book2 = r1.book_id, r2.book_id

    def _sample_citations(book_id: str) -> list[str]:
        rows = iconn.execute(
            "SELECT spine_idx, para_idx, global_seq FROM para WHERE book_id = ? AND kind != 'excerpt' "
            "ORDER BY global_seq",
            (book_id,),
        ).fetchall()
        picks = [rows[0], rows[len(rows) // 2], rows[-1]]
        return [tools.format_citation_id(book_id, r["spine_idx"], r["para_idx"]) for r in picks]

    excerpt_strings = _distinctive_excerpt_strings(iconn, book1)

    max_any_seq = iconn.execute(
        "SELECT MAX(global_seq) AS m FROM para WHERE book_id = ? OR book_id = ?", (book1, book2)
    ).fetchone()["m"]

    return {
        "iconn": iconn,
        "pconn": pconn,
        "book1": book1,
        "book2": book2,
        "result1": r1,
        "result2": r2,
        "excerpt_strings": excerpt_strings,
        "sample_citations": {book1: _sample_citations(book1), book2: _sample_citations(book2)},
        "max_any_seq": max_any_seq,
        "unique_text_index": _build_unique_text_index(iconn, book1, book2),
    }


def _finished_ceiling(iconn, book_id: str) -> int:
    """The ceiling 'status=finished' would resolve to for book_id: the max
    end_seq over its non-excerpt chapters. Computed directly (rather than
    via progress.set_position) so tests can force an exact, deterministic
    ceiling regardless of what any earlier test in this session-scoped
    fixture left behind -- set_position's watermark never lowers, so it is
    NOT safe for tests sharing a progress.db to assume it resets state."""
    row = iconn.execute(
        "SELECT MAX(end_seq) AS m FROM chapter WHERE book_id = ? AND kind != 'excerpt'", (book_id,)
    ).fetchone()
    assert row["m"] is not None
    return row["m"]


def _distinctive_excerpt_strings(iconn, book_id: str) -> list[str]:
    """Pull real substrings out of book_id's kind='excerpt' rows, so the leak
    test proves something about THIS ingest rather than a hardcoded guess at
    book text (which the project explicitly wants to avoid depending on)."""
    rows = iconn.execute(
        "SELECT text FROM para WHERE book_id = ? AND kind = 'excerpt' ORDER BY global_seq",
        (book_id,),
    ).fetchall()
    assert rows, f"expected excerpt rows for {book_id!r} -- fixture assumption broken"
    strings = []
    for r in rows:
        words = r["text"].split()
        # A run of 5 consecutive words is specific enough to be a reliable,
        # non-coincidental match without hardcoding actual book prose here.
        if len(words) >= 5:
            strings.append(" ".join(words[:5]))
        if len(strings) >= 8:
            break
    assert strings, "could not derive distinctive excerpt strings from real rows"
    return strings


def _build_unique_text_index(iconn, book1: str, book2: str) -> dict[str, int]:
    """text -> global_seq, restricted to paragraph texts that are globally
    unique across the two ingested books. Used to catch a text-level leak (a
    tool returning the literal paragraph text of an above-ceiling row) with
    no risk of a false positive from duplicate lines ('Yes.', etc.)."""
    rows = iconn.execute(
        "SELECT text, global_seq FROM para WHERE book_id = ? OR book_id = ?", (book1, book2)
    ).fetchall()
    counts: dict[str, int] = {}
    seqs: dict[str, int] = {}
    for r in rows:
        counts[r["text"]] = counts.get(r["text"], 0) + 1
        seqs[r["text"]] = r["global_seq"]
    return {t: s for t, s in seqs.items() if counts[t] == 1}


# -- generic structural helpers ---------------------------------------------


def _all_strings(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield from _all_strings(k)
            yield from _all_strings(v)
    elif isinstance(obj, (list, tuple)):
        for item in obj:
            yield from _all_strings(item)


def _extract_citation_ids(obj, known_book_ids):
    for s in _all_strings(obj):
        for m in _CITATION_RE.finditer(s):
            if m.group(1) in known_book_ids:
                yield m.group(1), int(m.group(2)), int(m.group(3))


def _assert_no_citation_above_ceiling(result, ceiling, book_order):
    for book_id, spine_idx, para_idx in _extract_citation_ids(result, book_order.keys()):
        gseq = db.global_seq(book_order[book_id], spine_idx, para_idx)
        assert gseq <= ceiling, (
            f"leak: citation {book_id}:{spine_idx}:p{para_idx} (global_seq={gseq}) "
            f"exceeds ceiling={ceiling} in {result!r}"
        )


def _assert_no_excerpt_citation_ever(result, iconn, book_order):
    """Stronger than the ceiling check: an excerpt row must never be
    returned regardless of ceiling, because kind='excerpt' is excluded
    unconditionally in every tool query."""
    for book_id, spine_idx, para_idx in _extract_citation_ids(result, book_order.keys()):
        row = iconn.execute(
            "SELECT kind FROM para WHERE book_id = ? AND spine_idx = ? AND para_idx = ?",
            (book_id, spine_idx, para_idx),
        ).fetchone()
        assert row is not None
        assert row["kind"] != "excerpt", (
            f"leak: excerpt-quarantined row {book_id}:{spine_idx}:p{para_idx} was returned: {result!r}"
        )


def _text_field_values(obj):
    """Yield values specifically under a "text" key -- the exact verbatim
    paragraph text field used by read_raw/context. Deliberately narrower
    than _all_strings: titles, chapter labels, and snippets are expected to
    coincidentally match unrelated paragraph text (e.g. a book's own title
    appearing as a line of running text elsewhere) and would otherwise be
    false positives here."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "text" and isinstance(v, str):
                yield v
            else:
                yield from _text_field_values(v)
    elif isinstance(obj, (list, tuple)):
        for item in obj:
            yield from _text_field_values(item)


def _assert_no_unique_text_leak(result, ceiling, unique_text_index):
    for s in _text_field_values(result):
        seq = unique_text_index.get(s)
        if seq is not None:
            assert seq <= ceiling, f"leak: exact paragraph text above ceiling={ceiling} returned: {s[:80]!r}..."


def _all_tool_calls(t: tools.Tools, book1: str, book2: str, sample_citations: dict, query: str):
    """Exercise every public Tools method at least once. Used by the small,
    fixed-count tests (run a handful of times, not per-combo)."""
    calls = []
    calls.append(("list_books", t.list_books()))
    for book in (book1, book2, "nonexistent-book"):
        calls.append((f"list_chapters:{book}", t.list_chapters(book)))
        calls.append((f"read_raw:{book}", t.read_raw(book, 0, 500)))
        calls.append((f"read_digest:{book}", t.read_digest(book, chapter=500)))
    calls.append(("search", t.search(query)))
    calls.append(("search_regex", t.search(query, regex=True)))
    calls.append(("search_book1", t.search(query, book=book1)))
    calls.append(("search_book2", t.search(query, book=book2)))
    calls.append(("first_seen", t.first_seen(query)))
    calls.append(("cast", t.cast()))

    for book in (book1, book2):
        for cid in sample_citations.get(book, []):
            try:
                calls.append((f"context:{cid}", t.context(cid, window=5)))
            except ValueError:
                calls.append((f"context:{cid}", {}))
    return calls


def _lean_tool_calls(t: tools.Tools, book1: str, book2: str, sample_citations: dict, query: str):
    """A cheaper subset of _all_tool_calls, for the property test that
    repeats this hundreds of times across ceilings x queries -- still
    exercises every method family (list/read/search/first_seen/context),
    just without the redundant per-book/regex variants of search."""
    calls = [
        ("list_books", t.list_books()),
        (f"list_chapters:{book1}", t.list_chapters(book1)),
        (f"list_chapters:{book2}", t.list_chapters(book2)),
        (f"read_raw:{book1}", t.read_raw(book1, 0, 500)),
        (f"read_raw:{book2}", t.read_raw(book2, 0, 500)),
        ("search", t.search(query)),
        ("first_seen", t.first_seen(query)),
    ]
    for book in (book1, book2):
        cid = (sample_citations.get(book) or [None])[0]
        if cid is None:
            continue
        try:
            calls.append((f"context:{cid}", t.context(cid, window=5)))
        except ValueError:
            pass
    return calls


# -- test 1: the excerpt leak is closed -------------------------------------


def test_excerpt_leak_is_closed_at_finished_ceiling(rr_series):
    iconn, pconn = rr_series["iconn"], rr_series["pconn"]
    book1, book2 = rr_series["book1"], rr_series["book2"]

    progress.reset_ceiling(pconn, book1, _finished_ceiling(iconn, book1))
    progress.reset_ceiling(pconn, book2, 0)
    t = tools.Tools(iconn, pconn)

    # Scoped to book1: the excerpt text is a real, verbatim quote of Golden
    # Son's own opening, so an unscoped search would also (correctly) match
    # it in Golden Son's own legitimate body chapters once that book is
    # readable. Scoping to book1 isolates the claim that actually matters:
    # Red Rising's own excerpt chapter never surfaces it.
    for s in rr_series["excerpt_strings"]:
        result = t.search(s, book=book1)
        assert result["results"] == [], f"excerpt string leaked via search: {s!r} -> {result}"

    book_order = {book1: rr_series["result1"].book_order, book2: rr_series["result2"].book_order}
    for name, result in _all_tool_calls(t, book1, book2, rr_series["sample_citations"], "the"):
        _assert_no_excerpt_citation_ever(result, iconn, book_order)


def test_excerpt_never_reachable_even_at_max_possible_ceiling(rr_series):
    """The stronger claim: even if the ceiling is set to the single highest
    global_seq in the whole series (which sits *inside* Red Rising's own
    excerpt back matter, numerically above every real Red Rising chapter),
    no tool call ever surfaces a kind='excerpt' row. The exclusion is
    unconditional in SQL, not merely 'below the usual ceiling'."""
    iconn, pconn = rr_series["iconn"], rr_series["pconn"]
    book1, book2 = rr_series["book1"], rr_series["book2"]

    progress.reset_ceiling(pconn, book1, rr_series["max_any_seq"])
    progress.reset_ceiling(pconn, book2, rr_series["max_any_seq"])
    t = tools.Tools(iconn, pconn)

    book_order = {book1: rr_series["result1"].book_order, book2: rr_series["result2"].book_order}
    for s in rr_series["excerpt_strings"]:
        result = t.search(s, book=book1)
        assert result["results"] == [], f"excerpt string leaked at max ceiling: {s!r} -> {result}"

    for name, result in _all_tool_calls(t, book1, book2, rr_series["sample_citations"], "the"):
        _assert_no_excerpt_citation_ever(result, iconn, book_order)


# -- test 2: property test across ~200 real ceilings -------------------------


def test_property_no_leaks_across_real_ceilings_and_queries(rr_series):
    iconn, pconn = rr_series["iconn"], rr_series["pconn"]
    book1, book2 = rr_series["book1"], rr_series["book2"]
    book_order = {book1: rr_series["result1"].book_order, book2: rr_series["result2"].book_order}
    unique_text_index = rr_series["unique_text_index"]

    rng = random.Random(20260815)

    boundary_seqs = set()
    for book in (book1, book2):
        for r in iconn.execute("SELECT start_seq, end_seq FROM chapter WHERE book_id = ?", (book,)):
            boundary_seqs.add(r["start_seq"])
            boundary_seqs.add(r["end_seq"])
            boundary_seqs.add(r["start_seq"] - 1)
            boundary_seqs.add(r["end_seq"] + 1)
    # Real books have far more chapters than the synthetic fixture this
    # pattern was borrowed from (~120 combined here) -- sample down so the
    # ceiling count stays proportionate to what a property test needs
    # rather than exhaustively covering every chapter boundary.
    boundary_sample = rng.sample(sorted(boundary_seqs), min(30, len(boundary_seqs)))

    max_seq = rr_series["max_any_seq"]
    random_ceilings = [rng.randint(0, max_seq + 10) for _ in range(40)]
    ceilings = sorted({max(0, c) for c in boundary_sample + random_ceilings})

    combo_count = 0
    for ceiling in ceilings:
        progress.reset_ceiling(pconn, book1, ceiling)
        progress.reset_ceiling(pconn, book2, ceiling)
        t = tools.Tools(iconn, pconn)
        assert t._ceiling == ceiling

        for query in QUERIES:
            combo_count += 1
            for name, result in _lean_tool_calls(t, book1, book2, rr_series["sample_citations"], query):
                _assert_no_citation_above_ceiling(result, ceiling, book_order)
                _assert_no_excerpt_citation_ever(result, iconn, book_order)
                _assert_no_unique_text_leak(result, ceiling, unique_text_index)

    assert combo_count >= 200, f"expected >= 200 ceiling x query combinations, got {combo_count}"


# -- test 3: cross-book behaviour --------------------------------------------


def test_search_crosses_books_when_ceiling_is_inside_book_two(rr_series):
    iconn, pconn = rr_series["iconn"], rr_series["pconn"]
    book1, book2 = rr_series["book1"], rr_series["book2"]

    progress.reset_ceiling(pconn, book1, _finished_ceiling(iconn, book1))
    mid_ch = iconn.execute(
        "SELECT end_seq FROM chapter WHERE book_id = ? AND kind = 'body' ORDER BY chapter_idx LIMIT 1 OFFSET 5",
        (book2,),
    ).fetchone()
    progress.reset_ceiling(pconn, book2, mid_ch["end_seq"])
    t = tools.Tools(iconn, pconn)

    hit_books = set()
    for query in QUERIES:
        result = t.search(query)
        hit_books.update(r["citation_id"].split(":")[0] for r in result["results"])
    assert book1 in hit_books
    assert book2 in hit_books


def test_search_stays_within_book_one_when_book_two_unread(rr_series):
    iconn, pconn = rr_series["iconn"], rr_series["pconn"]
    book1, book2 = rr_series["book1"], rr_series["book2"]

    progress.reset_ceiling(pconn, book1, _finished_ceiling(iconn, book1))
    progress.reset_ceiling(pconn, book2, 0)
    t = tools.Tools(iconn, pconn)

    hit_books = set()
    for query in QUERIES:
        result = t.search(query)
        hit_books.update(r["citation_id"].split(":")[0] for r in result["results"])
    assert hit_books == {book1}, f"expected only {book1!r}, got {hit_books}"


# -- test 4: retrieval is not vacuously safe ---------------------------------


def test_raising_ceiling_reveals_previously_hidden_real_rows(rr_series):
    iconn, pconn = rr_series["iconn"], rr_series["pconn"]
    book1, book2 = rr_series["book1"], rr_series["book2"]

    chapters = iconn.execute(
        "SELECT chapter_idx, start_seq, end_seq FROM chapter WHERE book_id = ? AND kind = 'body' "
        "ORDER BY chapter_idx",
        (book1,),
    ).fetchall()
    assert len(chapters) > 5

    progress.reset_ceiling(pconn, book1, chapters[0]["end_seq"])
    progress.reset_ceiling(pconn, book2, 0)
    low = tools.Tools(iconn, pconn)
    low_chapters = low.list_chapters(book1)["chapters"]
    low_hits = low.search("the")["results"]

    progress.reset_ceiling(pconn, book1, chapters[-1]["end_seq"])
    high = tools.Tools(iconn, pconn)
    high_chapters = high.list_chapters(book1)["chapters"]
    high_hits = high.search("the")["results"]

    assert len(high_chapters) > len(low_chapters)
    assert len(high_hits) > len(low_hits)


# -- test 5: idempotent ingest ------------------------------------------------


def test_reingest_same_book_is_idempotent(rr_series, corpus):
    iconn = rr_series["iconn"]
    book1 = rr_series["book1"]

    before_paras = iconn.execute("SELECT COUNT(*) c FROM para WHERE book_id = ?", (book1,)).fetchone()["c"]
    before_chapters = iconn.execute(
        "SELECT COUNT(*) c FROM chapter WHERE book_id = ?", (book1,)
    ).fetchone()["c"]

    result = ingest.ingest_book(
        corpus["red-rising"], series_id="red-rising-series", book_order=1, iconn=iconn
    )
    assert result.skipped is True
    assert result.book_id == book1

    after_paras = iconn.execute("SELECT COUNT(*) c FROM para WHERE book_id = ?", (book1,)).fetchone()["c"]
    after_chapters = iconn.execute(
        "SELECT COUNT(*) c FROM chapter WHERE book_id = ?", (book1,)
    ).fetchone()["c"]
    assert after_paras == before_paras
    assert after_chapters == before_chapters


# -- test 6: structural invariants -------------------------------------------


def test_every_para_belongs_to_exactly_one_chapter(rr_series):
    iconn = rr_series["iconn"]
    for book_id in (rr_series["book1"], rr_series["book2"]):
        orphans = iconn.execute(
            """
            SELECT p.id FROM para p
            LEFT JOIN chapter c ON c.book_id = p.book_id AND c.chapter_idx = p.chapter_idx
            WHERE p.book_id = ? AND c.chapter_idx IS NULL
            """,
            (book_id,),
        ).fetchall()
        assert orphans == []


def test_chapter_seq_bounds_its_own_paragraphs(rr_series):
    iconn = rr_series["iconn"]
    for book_id in (rr_series["book1"], rr_series["book2"]):
        rows = iconn.execute(
            """
            SELECT c.chapter_idx, c.start_seq, c.end_seq, MIN(p.global_seq) AS pmin, MAX(p.global_seq) AS pmax
            FROM chapter c JOIN para p ON p.book_id = c.book_id AND p.chapter_idx = c.chapter_idx
            WHERE c.book_id = ?
            GROUP BY c.chapter_idx
            """,
            (book_id,),
        ).fetchall()
        assert rows, f"no chapters with paragraphs found for {book_id}"
        for r in rows:
            assert r["start_seq"] == r["pmin"], f"{book_id} chapter {r['chapter_idx']} start_seq mismatch"
            assert r["end_seq"] == r["pmax"], f"{book_id} chapter {r['chapter_idx']} end_seq mismatch"


def test_global_seq_unique_and_strictly_increasing(rr_series):
    iconn = rr_series["iconn"]
    book1, book2 = rr_series["book1"], rr_series["book2"]
    book_order = {book1: rr_series["result1"].book_order, book2: rr_series["result2"].book_order}

    rows = iconn.execute(
        "SELECT book_id, spine_idx, para_idx, global_seq FROM para WHERE book_id = ? OR book_id = ? "
        "ORDER BY book_id, spine_idx, para_idx",
        (book1, book2),
    ).fetchall()

    all_seqs = [r["global_seq"] for r in rows]
    assert len(all_seqs) == len(set(all_seqs)), "global_seq is not unique across the series"

    for book_id in (book1, book2):
        book_rows = [r for r in rows if r["book_id"] == book_id]
        seqs = [r["global_seq"] for r in book_rows]
        assert seqs == sorted(seqs), f"{book_id}: global_seq not increasing in (spine_idx, para_idx) order"
        assert len(seqs) == len(set(seqs))
        for r in book_rows:
            expected = db.global_seq(book_order[book_id], r["spine_idx"], r["para_idx"])
            assert r["global_seq"] == expected
