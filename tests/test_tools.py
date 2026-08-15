"""Tests for booklens.tools: the bounded tool layer.

Also defines build_fixture(), a small synthetic two-book series used both
here and by tests/test_cutoff_invariant.py. All text is invented (lorem-style
placeholders) -- no real book content, per project policy.
"""

from __future__ import annotations

import pytest

from booklens import db, progress, tools

NUM_CHAPTERS = 3
PARAS_PER_CHAPTER = 5

ENTITY_TOKEN = "ENTITYTOKEN_ZYX"
SPOILER_TOKEN = "SPOILERTOKEN_9317"


def build_fixture(tmp_path):
    """Build a synthetic 2-book series directly into fresh index/progress DBs.

    rr1 (book_order=1) and rr2 (book_order=2), each with NUM_CHAPTERS chapters
    of PARAS_PER_CHAPTER paragraphs. One spine document per chapter (spine_idx
    == chapter_idx) for simplicity.

    ENTITY_TOKEN appears once, at rr1 chapter 2 paragraph 0.
    SPOILER_TOKEN appears once, at rr2 chapter 2 paragraph 4 -- the single
    highest global_seq in the whole fixture. Useful as a leakage sentinel.

    Returns (iconn, pconn, meta) where meta["books"][book_id]["chapters"] is
    a list of {chapter_idx, label, start_seq, end_seq}.
    """
    iconn = db.connect_index(tmp_path / "index.db")
    pconn = db.connect_progress(tmp_path / "progress.db")

    meta = {"books": {}}
    for book_id, book_order in (("rr1", 1), ("rr2", 2)):
        iconn.execute(
            """
            INSERT INTO book(id, sha256, title, author, source_path, series_id,
                              book_order, sequence_tier, label_tier, ingested_at)
            VALUES (?, ?, ?, 'Some Author', '/x.epub', 's1', ?, 'S1', 'L1', '2026-01-01')
            """,
            (book_id, f"sha-{book_id}", f"Book {book_order}", book_order),
        )
        chapters = []
        for ch in range(NUM_CHAPTERS):
            para_rows = []
            for p in range(PARAS_PER_CHAPTER):
                gseq = db.global_seq(book_order, ch, p)
                text = f"lorem {book_id} chapter {ch} paragraph {p} ipsum dolor sit amet"
                if book_id == "rr1" and ch == 2 and p == 0:
                    text += f" {ENTITY_TOKEN} appears here"
                if book_id == "rr2" and ch == 2 and p == 4:
                    text += f" {SPOILER_TOKEN} secret reveal"
                iconn.execute(
                    """
                    INSERT INTO para(book_id, spine_idx, para_idx, global_seq,
                                      chapter_idx, chapter_label, text)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (book_id, ch, p, gseq, ch, f"Chapter {ch}", text),
                )
                para_rows.append(gseq)
            start, end = para_rows[0], para_rows[-1]
            iconn.execute(
                """
                INSERT INTO chapter(book_id, chapter_idx, label, part_label, start_seq, end_seq)
                VALUES (?, ?, ?, NULL, ?, ?)
                """,
                (book_id, ch, f"Chapter {ch}", start, end),
            )
            chapters.append(
                {"chapter_idx": ch, "label": f"Chapter {ch}", "start_seq": start, "end_seq": end}
            )
        meta["books"][book_id] = {"book_order": book_order, "chapters": chapters}

    iconn.commit()
    pconn.commit()
    return iconn, pconn, meta


def _set_ceiling(pconn, iconn, book_id, ceiling_seq):
    progress.reset_ceiling(pconn, book_id, ceiling_seq)


# -- citation id helpers -----------------------------------------------------


def test_format_and_parse_citation_id_roundtrip():
    cid = tools.format_citation_id("rr2", 78, 14)
    assert cid == "rr2:78:p14"
    assert tools.parse_citation_id(cid) == ("rr2", 78, 14)


@pytest.mark.parametrize(
    "bad",
    ["", "rr2", "rr2:78", "rr2:78:14", "rr2:p14", "rr2:78:pX", ":78:p14", "rr2:-1:p1", 12345, None],
)
def test_parse_citation_id_rejects_malformed(bad):
    with pytest.raises(ValueError):
        tools.parse_citation_id(bad)


def test_format_citation_id_rejects_colon_in_book_id():
    with pytest.raises(ValueError):
        tools.format_citation_id("rr:2", 0, 0)


# -- basic behaviour, one method at a time -----------------------------------


def test_list_books_basic(tmp_path):
    iconn, pconn, meta = build_fixture(tmp_path)
    progress.set_position(pconn, iconn, "rr1", status="reading", chapter_idx=0)
    t = tools.Tools(iconn, pconn)
    books = t.list_books()
    ids = {b["id"] for b in books}
    assert ids == {"rr1", "rr2"}
    rr1 = next(b for b in books if b["id"] == "rr1")
    assert rr1["status"] == "reading"
    assert rr1["current_chapter"] == "Chapter 0"


def test_list_chapters_respects_ceiling(tmp_path):
    iconn, pconn, meta = build_fixture(tmp_path)
    end_of_ch0 = meta["books"]["rr1"]["chapters"][0]["end_seq"]
    _set_ceiling(pconn, iconn, "rr1", end_of_ch0)
    t = tools.Tools(iconn, pconn)
    result = t.list_chapters("rr1")
    labels = [c["label"] for c in result["chapters"]]
    assert labels == ["Chapter 0"]
    assert result["truncated_at"] == "Chapter 0"
    assert result["reason"] == "reading position"


def test_list_chapters_no_truncation_when_fully_read(tmp_path):
    iconn, pconn, meta = build_fixture(tmp_path)
    end_of_book = meta["books"]["rr1"]["chapters"][-1]["end_seq"]
    _set_ceiling(pconn, iconn, "rr1", end_of_book)
    t = tools.Tools(iconn, pconn)
    result = t.list_chapters("rr1")
    assert len(result["chapters"]) == NUM_CHAPTERS
    assert "truncated_at" not in result


def test_list_chapters_unknown_book_returns_empty_not_error(tmp_path):
    iconn, pconn, meta = build_fixture(tmp_path)
    t = tools.Tools(iconn, pconn)
    result = t.list_chapters("nonexistent-book")
    assert result["chapters"] == []


def test_read_raw_clamped_to_ceiling(tmp_path):
    iconn, pconn, meta = build_fixture(tmp_path)
    ch0 = meta["books"]["rr1"]["chapters"][0]
    mid_ceiling = ch0["start_seq"] + 2  # partway through chapter 0
    _set_ceiling(pconn, iconn, "rr1", mid_ceiling)
    t = tools.Tools(iconn, pconn)
    result = t.read_raw("rr1", 0, 2)
    seqs = [p["citation_id"] for p in result["paragraphs"]]
    assert len(seqs) == 3  # para_idx 0, 1, 2 (global_seq <= start+2)
    assert result["truncated_at"] == "Chapter 0"


def test_read_raw_swaps_inverted_range(tmp_path):
    iconn, pconn, meta = build_fixture(tmp_path)
    _set_ceiling(pconn, iconn, "rr1", meta["books"]["rr1"]["chapters"][-1]["end_seq"])
    t = tools.Tools(iconn, pconn)
    forward = t.read_raw("rr1", 0, 1)
    backward = t.read_raw("rr1", 1, 0)
    assert forward["paragraphs"] == backward["paragraphs"]


def test_read_raw_negative_indices_clamped(tmp_path):
    iconn, pconn, meta = build_fixture(tmp_path)
    _set_ceiling(pconn, iconn, "rr1", meta["books"]["rr1"]["chapters"][-1]["end_seq"])
    t = tools.Tools(iconn, pconn)
    result = t.read_raw("rr1", -100, 0)
    assert len(result["paragraphs"]) == PARAS_PER_CHAPTER


def test_read_raw_huge_range_does_not_crash(tmp_path):
    iconn, pconn, meta = build_fixture(tmp_path)
    _set_ceiling(pconn, iconn, "rr1", meta["books"]["rr1"]["chapters"][-1]["end_seq"])
    t = tools.Tools(iconn, pconn)
    result = t.read_raw("rr1", 0, 10**9)
    assert isinstance(result["paragraphs"], list)


def test_read_digest_is_stub(tmp_path):
    iconn, pconn, meta = build_fixture(tmp_path)
    _set_ceiling(pconn, iconn, "rr1", meta["books"]["rr1"]["chapters"][0]["end_seq"])
    t = tools.Tools(iconn, pconn)
    result = t.read_digest("rr1", chapter=0)
    assert result["digests"] == []


def test_read_digest_refuses_beyond_ceiling(tmp_path):
    iconn, pconn, meta = build_fixture(tmp_path)
    _set_ceiling(pconn, iconn, "rr1", meta["books"]["rr1"]["chapters"][0]["end_seq"])
    t = tools.Tools(iconn, pconn)
    result = t.read_digest("rr1", chapter=2)
    assert result["digests"] == []
    assert result.get("truncated_at") == "Chapter 0"


def test_search_fts_basic(tmp_path):
    iconn, pconn, meta = build_fixture(tmp_path)
    _set_ceiling(pconn, iconn, "rr1", meta["books"]["rr1"]["chapters"][-1]["end_seq"])
    t = tools.Tools(iconn, pconn)
    result = t.search("lorem")
    assert len(result["results"]) > 0
    assert all("citation_id" in r for r in result["results"])


def test_search_fts_ceiling_hides_hits(tmp_path):
    iconn, pconn, meta = build_fixture(tmp_path)
    _set_ceiling(pconn, iconn, "rr1", meta["books"]["rr1"]["chapters"][0]["end_seq"])
    t = tools.Tools(iconn, pconn)
    result = t.search("lorem")
    # only chapter 0 of rr1 is readable
    assert all(r["chapter"] == "Chapter 0" for r in result["results"])


def test_search_malformed_fts_syntax_no_traceback(tmp_path):
    iconn, pconn, meta = build_fixture(tmp_path)
    _set_ceiling(pconn, iconn, "rr1", meta["books"]["rr1"]["chapters"][-1]["end_seq"])
    t = tools.Tools(iconn, pconn)
    result = t.search('"unbalanced quote')
    assert "results" in result  # clean error, no exception


def test_search_regex_mode(tmp_path):
    iconn, pconn, meta = build_fixture(tmp_path)
    _set_ceiling(pconn, iconn, "rr1", meta["books"]["rr1"]["chapters"][-1]["end_seq"])
    t = tools.Tools(iconn, pconn)
    result = t.search(r"paragraph \d", regex=True)
    assert len(result["results"]) > 0


def test_search_invalid_regex_no_traceback(tmp_path):
    iconn, pconn, meta = build_fixture(tmp_path)
    _set_ceiling(pconn, iconn, "rr1", meta["books"]["rr1"]["chapters"][-1]["end_seq"])
    t = tools.Tools(iconn, pconn)
    result = t.search("(unclosed", regex=True)
    assert result["results"] == []
    assert "error" in result


def test_first_seen_found(tmp_path):
    iconn, pconn, meta = build_fixture(tmp_path)
    _set_ceiling(pconn, iconn, "rr1", meta["books"]["rr1"]["chapters"][-1]["end_seq"])
    t = tools.Tools(iconn, pconn)
    result = t.first_seen(ENTITY_TOKEN)
    assert result["result"] == "FOUND"
    assert result["citation_id"] == "rr1:2:p0"


def test_first_seen_not_yet_seen_when_above_ceiling(tmp_path):
    iconn, pconn, meta = build_fixture(tmp_path)
    _set_ceiling(pconn, iconn, "rr1", meta["books"]["rr1"]["chapters"][1]["end_seq"])
    t = tools.Tools(iconn, pconn)
    result = t.first_seen(ENTITY_TOKEN)
    assert result == {"result": "NOT_YET_SEEN"}


def test_first_seen_not_yet_seen_when_never_appears(tmp_path):
    iconn, pconn, meta = build_fixture(tmp_path)
    _set_ceiling(pconn, iconn, "rr1", meta["books"]["rr1"]["chapters"][-1]["end_seq"])
    t = tools.Tools(iconn, pconn)
    result = t.first_seen("SOME_ENTITY_THAT_NEVER_APPEARS_XYZ")
    assert result == {"result": "NOT_YET_SEEN"}


def test_cast_is_stub(tmp_path):
    iconn, pconn, meta = build_fixture(tmp_path)
    t = tools.Tools(iconn, pconn)
    assert t.cast() == {"cast": [], "note": t.cast()["note"]}


def test_context_basic(tmp_path):
    iconn, pconn, meta = build_fixture(tmp_path)
    _set_ceiling(pconn, iconn, "rr1", meta["books"]["rr1"]["chapters"][-1]["end_seq"])
    t = tools.Tools(iconn, pconn)
    result = t.context("rr1:1:p2", window=2)
    cids = [p["citation_id"] for p in result["paragraphs"]]
    assert cids == ["rr1:1:p0", "rr1:1:p1", "rr1:1:p2", "rr1:1:p3", "rr1:1:p4"]


def test_context_clamped_forward_by_ceiling(tmp_path):
    iconn, pconn, meta = build_fixture(tmp_path)
    ch1 = meta["books"]["rr1"]["chapters"][1]
    ceiling = ch1["start_seq"] + 2  # p0, p1, p2 readable in chapter 1
    _set_ceiling(pconn, iconn, "rr1", ceiling)
    t = tools.Tools(iconn, pconn)
    # window=1 keeps the expansion within chapter 1, isolating the forward clamp.
    result = t.context("rr1:1:p1", window=1)
    cids = [p["citation_id"] for p in result["paragraphs"]]
    assert cids == ["rr1:1:p0", "rr1:1:p1", "rr1:1:p2"]

    # A wider window is free to reach back into the previous chapter (backward
    # is unclamped -- everything before the center is already <= ceiling by
    # construction) but must never reach past p2 going forward.
    wide = t.context("rr1:1:p1", window=5)
    wide_cids = [p["citation_id"] for p in wide["paragraphs"]]
    assert "rr1:1:p3" not in wide_cids
    assert "rr1:1:p4" not in wide_cids


def test_context_raises_on_bogus_citation(tmp_path):
    iconn, pconn, meta = build_fixture(tmp_path)
    _set_ceiling(pconn, iconn, "rr1", meta["books"]["rr1"]["chapters"][-1]["end_seq"])
    t = tools.Tools(iconn, pconn)
    with pytest.raises(ValueError):
        t.context("not-a-citation-id")


def test_context_raises_on_citation_above_ceiling(tmp_path):
    iconn, pconn, meta = build_fixture(tmp_path)
    _set_ceiling(pconn, iconn, "rr1", meta["books"]["rr1"]["chapters"][0]["end_seq"])
    t = tools.Tools(iconn, pconn)
    with pytest.raises(ValueError):
        t.context("rr1:2:p0")  # chapter 2, above ceiling


def test_context_raises_on_unknown_book(tmp_path):
    iconn, pconn, meta = build_fixture(tmp_path)
    _set_ceiling(pconn, iconn, "rr1", meta["books"]["rr1"]["chapters"][-1]["end_seq"])
    t = tools.Tools(iconn, pconn)
    with pytest.raises(ValueError):
        t.context("nope:0:p0")
