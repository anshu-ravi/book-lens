"""The file that matters most: proves the spoiler cutoff cannot be bypassed.

Every check here treats booklens.tools.Tools as the boundary the answering
model actually sees. If any of these fail, the one invariant in CLAUDE.md is
broken.
"""

from __future__ import annotations

import inspect
import json
import random
import re

import pytest

from booklens import db, progress, tools
from tests.test_tools import (
    ENTITY_TOKEN,
    NUM_CHAPTERS,
    PARAS_PER_CHAPTER,
    SPOILER_TOKEN,
    build_fixture,
)

BOOK_ORDER = {"rr1": 1, "rr2": 2}
MAX_GLOBAL_SEQ = db.global_seq(BOOK_ORDER["rr2"], NUM_CHAPTERS - 1, PARAS_PER_CHAPTER - 1)

_CITATION_RE = re.compile(r"\b([a-zA-Z0-9_-]+):(\d+):p(\d+)\b")


def _all_strings(obj):
    """Yield every string leaf in a nested dict/list structure."""
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield from _all_strings(k)
            yield from _all_strings(v)
    elif isinstance(obj, (list, tuple)):
        for item in obj:
            yield from _all_strings(item)


def _extract_citation_ids(obj):
    for s in _all_strings(obj):
        for m in _CITATION_RE.finditer(s):
            yield m.group(1), int(m.group(2)), int(m.group(3))


def _assert_no_rows_above_ceiling(result, ceiling):
    """Generic structural check: every citation id embedded anywhere in the
    response resolves to a global_seq <= ceiling."""
    for book_id, spine_idx, para_idx in _extract_citation_ids(result):
        if book_id not in BOOK_ORDER:
            continue  # not one of our fixture books; not a citation id
        gseq = db.global_seq(BOOK_ORDER[book_id], spine_idx, para_idx)
        assert gseq <= ceiling, (
            f"leak: citation {book_id}:{spine_idx}:p{para_idx} "
            f"(global_seq={gseq}) exceeds ceiling={ceiling} in {result!r}"
        )


def _assert_no_sentinel_leak(result, ceiling):
    blob = json.dumps(result, default=str)
    if ceiling < MAX_GLOBAL_SEQ:
        assert SPOILER_TOKEN not in blob, f"SPOILER_TOKEN leaked at ceiling={ceiling}: {result!r}"
    # ENTITY_TOKEN sits at rr1 chapter 2 paragraph 0 (global_seq 1002000).
    entity_seq = db.global_seq(1, 2, 0)
    if ceiling < entity_seq:
        assert ENTITY_TOKEN not in blob, f"ENTITY_TOKEN leaked at ceiling={ceiling}: {result!r}"


def _all_tool_calls(t: tools.Tools, query: str):
    """Call every public Tools method once with a mix of arguments; return
    (method_name, result) pairs. Wrapped so a single bad combination can't
    hide the others' failures."""
    calls = []

    calls.append(("list_books", t.list_books()))
    for book in ("rr1", "rr2", "nonexistent"):
        calls.append((f"list_chapters:{book}", t.list_chapters(book)))
        calls.append((f"read_raw:{book}", t.read_raw(book, 0, NUM_CHAPTERS - 1)))
        calls.append((f"read_digest:{book}", t.read_digest(book, chapter=NUM_CHAPTERS - 1)))
    calls.append(("search", t.search(query)))
    calls.append(("search_regex", t.search(query, regex=True)))
    calls.append(("first_seen_entity", t.first_seen(ENTITY_TOKEN)))
    calls.append(("first_seen_spoiler", t.first_seen(SPOILER_TOKEN)))
    calls.append(("cast", t.cast()))

    for book_id, spine, para in (("rr1", 2, 0), ("rr2", 2, 4), ("rr1", 0, 0)):
        cid = tools.format_citation_id(book_id, spine, para)
        try:
            calls.append((f"context:{cid}", t.context(cid, window=5)))
        except ValueError:
            calls.append((f"context:{cid}", {}))  # raised cleanly; nothing to check

    return calls


QUERIES = [
    "lorem",
    "paragraph",
    ENTITY_TOKEN,
    SPOILER_TOKEN,
    '"unbalanced quote',
    "chapter OR paragraph NEAR/3 lorem",
]


def test_property_zero_leaks_across_ceilings_and_queries(tmp_path):
    iconn, pconn, meta = build_fixture(tmp_path)
    rng = random.Random(20260815)

    # Sample ceilings across the full range, including exact chapter
    # boundaries (the likeliest place for off-by-one leaks).
    boundary_seqs = set()
    for book_id, book in meta["books"].items():
        for ch in book["chapters"]:
            boundary_seqs.add(ch["start_seq"])
            boundary_seqs.add(ch["end_seq"])
            boundary_seqs.add(ch["start_seq"] - 1)
            boundary_seqs.add(ch["end_seq"] + 1)
    ceilings = sorted(boundary_seqs) + [
        rng.randint(0, MAX_GLOBAL_SEQ + 10) for _ in range(40)
    ]
    ceilings = [max(0, c) for c in ceilings]

    combo_count = 0
    for ceiling in ceilings:
        progress.reset_ceiling(pconn, "rr1", ceiling)
        progress.reset_ceiling(pconn, "rr2", ceiling)
        t = tools.Tools(iconn, pconn)
        assert t._ceiling == ceiling  # sanity: the ceiling we think we set

        for query in QUERIES:
            combo_count += 1
            for name, result in _all_tool_calls(t, query):
                _assert_no_rows_above_ceiling(result, ceiling)
                _assert_no_sentinel_leak(result, ceiling)

    assert combo_count >= 200, f"expected a few hundred combinations, got {combo_count}"


# -- adversarial fuzz ---------------------------------------------------------

ADVERSARIAL_QUERIES = [
    "",
    " ",
    "*",
    '"',
    '""',
    "NEAR",
    "OR OR OR",
    "(unclosed(",
    "a" * 10_000,
    "tab\tnewline\n",
    "спойлер тест юникод",
    "'; DROP TABLE para; --",
    "%' OR '1'='1",
    "para_fts",
    "MATCH",
]

ADVERSARIAL_RANGES = [
    (-1, -1),
    (-100, 5),
    (5, -100),
    (10**9, -(10**9)),
    (0, 10**9),
    (2, 2),
    (-1, 10**12),
]

ADVERSARIAL_WINDOWS = [-1, 0, -(10**6), 10**6, 3.7, None, "3"]


def test_adversarial_fuzz_no_tracebacks_no_leaks(tmp_path):
    iconn, pconn, meta = build_fixture(tmp_path)
    ceiling = meta["books"]["rr1"]["chapters"][0]["end_seq"]  # partial read
    progress.reset_ceiling(pconn, "rr1", ceiling)
    progress.reset_ceiling(pconn, "rr2", 0)
    t = tools.Tools(iconn, pconn)

    for q in ADVERSARIAL_QUERIES:
        for regex in (False, True):
            result = t.search(q, regex=regex)
            _assert_no_rows_above_ceiling(result, ceiling)
            _assert_no_sentinel_leak(result, ceiling)

        result = t.first_seen(q)
        _assert_no_rows_above_ceiling(result, ceiling)
        _assert_no_sentinel_leak(result, ceiling)

    for book in ("rr1", "rr2", "", None, "../../etc/passwd", "rr1' OR '1'='1"):
        for from_ch, to_ch in ADVERSARIAL_RANGES:
            try:
                result = t.read_raw(book, from_ch, to_ch)
            except Exception as exc:  # noqa: BLE001
                pytest.fail(f"read_raw traceback for {book=} {from_ch=} {to_ch=}: {exc!r}")
            _assert_no_rows_above_ceiling(result, ceiling)
            _assert_no_sentinel_leak(result, ceiling)

        try:
            result = t.list_chapters(book)
        except Exception as exc:  # noqa: BLE001
            pytest.fail(f"list_chapters traceback for {book=}: {exc!r}")
        _assert_no_rows_above_ceiling(result, ceiling)
        _assert_no_sentinel_leak(result, ceiling)

    for cid in [
        "",
        "not-a-citation",
        "rr1:0:p0:extra",
        "rr1:-1:p0",
        "rr1:0:p-1",
        "rr1:99999:p0",
        "rr1:0:p99999",
        "'; DROP TABLE para; --:0:p0",
        None,
        123,
    ]:
        for window in ADVERSARIAL_WINDOWS:
            try:
                result = t.context(cid, window=window)
            except ValueError:
                continue
            except Exception as exc:  # noqa: BLE001
                pytest.fail(f"context traceback for {cid=} {window=}: {exc!r}")
            _assert_no_rows_above_ceiling(result, ceiling)
            _assert_no_sentinel_leak(result, ceiling)

    # A valid citation id with pathological windows must not leak or crash.
    for window in ADVERSARIAL_WINDOWS:
        result = t.context("rr1:0:p0", window=window)
        _assert_no_rows_above_ceiling(result, ceiling)
        _assert_no_sentinel_leak(result, ceiling)


# -- ceiling unreachable from the public API ---------------------------------

_FORBIDDEN_PARAM_NAMES = {"ceiling", "ceiling_seq", "max_seq", "max_ceiling", "seq_ceiling"}


def test_ceiling_not_a_parameter_of_any_public_method():
    for name, member in inspect.getmembers(tools.Tools, predicate=inspect.isfunction):
        if name.startswith("_"):
            continue
        sig = inspect.signature(member)
        for pname in sig.parameters:
            normalized = pname.lower().replace("-", "_")
            assert normalized not in _FORBIDDEN_PARAM_NAMES, (
                f"Tools.{name} exposes a ceiling-shaped parameter: {pname!r}"
            )


# -- text leakage, dedicated ---------------------------------------------------


def test_sentinel_never_appears_below_its_own_seq(tmp_path):
    iconn, pconn, meta = build_fixture(tmp_path)
    spoiler_seq = meta["books"]["rr2"]["chapters"][-1]["end_seq"]
    assert spoiler_seq == MAX_GLOBAL_SEQ

    progress.reset_ceiling(pconn, "rr1", meta["books"]["rr1"]["chapters"][-1]["end_seq"])
    progress.reset_ceiling(pconn, "rr2", spoiler_seq - 1)
    t = tools.Tools(iconn, pconn)

    for name, result in _all_tool_calls(t, SPOILER_TOKEN):
        blob = json.dumps(result, default=str)
        assert SPOILER_TOKEN not in blob, f"{name} leaked SPOILER_TOKEN: {result!r}"


def test_sentinel_appears_once_ceiling_reaches_it(tmp_path):
    iconn, pconn, meta = build_fixture(tmp_path)
    spoiler_seq = meta["books"]["rr2"]["chapters"][-1]["end_seq"]
    progress.reset_ceiling(pconn, "rr1", 0)
    progress.reset_ceiling(pconn, "rr2", spoiler_seq)
    t = tools.Tools(iconn, pconn)

    result = t.search(SPOILER_TOKEN)
    blob = json.dumps(result, default=str)
    assert SPOILER_TOKEN in blob


# -- first_seen indistinguishability -----------------------------------------


def test_first_seen_not_yet_seen_identical_shape(tmp_path):
    iconn, pconn, meta = build_fixture(tmp_path)
    progress.reset_ceiling(pconn, "rr1", meta["books"]["rr1"]["chapters"][1]["end_seq"])
    progress.reset_ceiling(pconn, "rr2", 0)
    t = tools.Tools(iconn, pconn)

    above_ceiling = t.first_seen(ENTITY_TOKEN)  # exists, but above ceiling
    never_appears = t.first_seen("TRULY_NONEXISTENT_ENTITY_QQQ")

    assert above_ceiling == never_appears == {"result": "NOT_YET_SEEN"}


# -- context near the ceiling ---------------------------------------------------


def test_context_never_spills_past_ceiling_at_any_boundary(tmp_path):
    iconn, pconn, meta = build_fixture(tmp_path)
    for ch in meta["books"]["rr1"]["chapters"]:
        for offset in (0, 1, 2):
            ceiling = ch["start_seq"] + offset
            progress.reset_ceiling(pconn, "rr1", ceiling)
            progress.reset_ceiling(pconn, "rr2", 0)
            t = tools.Tools(iconn, pconn)
            cid = tools.format_citation_id("rr1", ch["chapter_idx"], 0)
            result = t.context(cid, window=10)
            _assert_no_rows_above_ceiling(result, ceiling)


def test_context_raises_on_bogus_citation_id(tmp_path):
    iconn, pconn, meta = build_fixture(tmp_path)
    progress.reset_ceiling(pconn, "rr1", meta["books"]["rr1"]["chapters"][-1]["end_seq"])
    t = tools.Tools(iconn, pconn)
    with pytest.raises(ValueError):
        t.context("garbage")


# -- raising the ceiling reveals previously hidden rows ------------------------


def test_raising_ceiling_reveals_previously_hidden_rows(tmp_path):
    """Proves the earlier "no leak" assertions aren't vacuously true because
    retrieval is simply broken and never returns anything."""
    iconn, pconn, meta = build_fixture(tmp_path)
    ch0_end = meta["books"]["rr1"]["chapters"][0]["end_seq"]
    ch2_end = meta["books"]["rr1"]["chapters"][-1]["end_seq"]

    progress.reset_ceiling(pconn, "rr1", ch0_end)
    progress.reset_ceiling(pconn, "rr2", 0)
    low = tools.Tools(iconn, pconn)
    low_chapters = low.list_chapters("rr1")["chapters"]
    assert len(low_chapters) == 1

    progress.reset_ceiling(pconn, "rr1", ch2_end)
    high = tools.Tools(iconn, pconn)
    high_chapters = high.list_chapters("rr1")["chapters"]
    assert len(high_chapters) == NUM_CHAPTERS
    assert len(high_chapters) > len(low_chapters)

    low_search = low.search("lorem")["results"]
    high_search = high.search("lorem")["results"]
    assert len(high_search) > len(low_search)

    assert low.first_seen(ENTITY_TOKEN) == {"result": "NOT_YET_SEEN"}
    assert high.first_seen(ENTITY_TOKEN)["result"] == "FOUND"


# -- "never display counts of unknown things" --------------------------------


def test_no_total_or_count_fields_reference_hidden_rows(tmp_path):
    """Any total/count-shaped field in a response must equal len() of the
    readable items actually returned alongside it -- never a count that
    includes rows above the ceiling."""
    iconn, pconn, meta = build_fixture(tmp_path)
    progress.reset_ceiling(pconn, "rr1", meta["books"]["rr1"]["chapters"][0]["end_seq"])
    progress.reset_ceiling(pconn, "rr2", 0)
    t = tools.Tools(iconn, pconn)

    def check(d, path=""):
        if isinstance(d, dict):
            for k, v in d.items():
                if re.search(r"total|count", k, re.IGNORECASE) and isinstance(v, int):
                    # Find a sibling list to compare against, if present.
                    for sibling_key, sibling_val in d.items():
                        if isinstance(sibling_val, list):
                            assert v == len(sibling_val), (
                                f"{path}.{k} = {v} does not match len({sibling_key})="
                                f"{len(sibling_val)}; may be counting hidden rows"
                            )
                check(v, f"{path}.{k}")
        elif isinstance(d, list):
            for i, item in enumerate(d):
                check(item, f"{path}[{i}]")

    for name, result in _all_tool_calls(t, "lorem"):
        check(result, name)
