"""The file that matters most for Phase 1: proves generation-time causality.

Every derived artifact must be tagged with the global_seq at which it became
knowable, and must have been generated from a context containing nothing
above that seq. This is a different failure mode from the retrieval cutoff
(tests/test_cutoff_invariant.py): a generation leak is quieter, because every
sentence in the artifact stays factually true while foregrounding what only
a model that saw the future would emphasize. FakeLLM records every call, so
this is directly assertable by scanning what was actually sent.

All text below is invented lorem-style placeholders, per project policy.
"""

from __future__ import annotations

import inspect
import json
import re

import pytest

from booklens import causal, db, passes, prompts
from booklens.llm.fake import FakeLLM

NUM_CHAPTERS = 4
PARAS_PER_CHAPTER = 3

_TOKEN_RE = re.compile(r"\bTOK_([a-z0-9]+)_(\d+)_(\d+)\b")


def _seed_two_book_series(iconn):
    """bk1 (book_order=1) and bk2 (book_order=2), each with NUM_CHAPTERS body chapters
    plus one excerpt chapter, every paragraph carrying a globally unique token."""
    books = {}
    for book_id, book_order in (("bk1", 1), ("bk2", 2)):
        iconn.execute(
            """
            INSERT INTO book(id, sha256, title, author, source_path, series_id,
                              book_order, sequence_tier, label_tier, ingested_at)
            VALUES (?, ?, 'Title', 'Author', '/x.epub', 'series1', ?, 'S1', 'L1', '2026-01-01')
            """,
            (book_id, f"sha-{book_id}", book_order),
        )
        chapters = []
        for ch in range(NUM_CHAPTERS):
            seqs = []
            for p in range(PARAS_PER_CHAPTER):
                gseq = db.global_seq(book_order, ch, p)
                text = f"lorem TOK_{book_id}_{ch}_{p} ipsum dolor"
                iconn.execute(
                    """
                    INSERT INTO para(book_id, spine_idx, para_idx, global_seq, chapter_idx,
                                      chapter_label, text, kind)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 'body')
                    """,
                    (book_id, ch, p, gseq, ch, f"Chapter {ch}", text),
                )
                seqs.append(gseq)
            iconn.execute(
                """
                INSERT INTO chapter(book_id, chapter_idx, label, part_label, start_seq, end_seq, kind)
                VALUES (?, ?, ?, NULL, ?, ?, 'body')
                """,
                (book_id, ch, f"Chapter {ch}", seqs[0], seqs[-1]),
            )
            chapters.append({"chapter_idx": ch, "start_seq": seqs[0], "end_seq": seqs[-1]})

        # An excerpt chapter, numerically inside this book's range, carrying its
        # own unmistakable token that must never reach any prompt for any book.
        excerpt_idx = NUM_CHAPTERS
        gseq = db.global_seq(book_order, excerpt_idx, 0)
        iconn.execute(
            """
            INSERT INTO para(book_id, spine_idx, para_idx, global_seq, chapter_idx,
                              chapter_label, text, kind)
            VALUES (?, ?, 0, ?, ?, 'Excerpt', 'EXCERPT_TOKEN_MUST_NEVER_APPEAR', 'excerpt')
            """,
            (book_id, excerpt_idx, gseq, excerpt_idx),
        )
        iconn.execute(
            """
            INSERT INTO chapter(book_id, chapter_idx, label, part_label, start_seq, end_seq, kind)
            VALUES (?, ?, 'Excerpt', NULL, ?, ?, 'excerpt')
            """,
            (book_id, excerpt_idx, gseq, gseq),
        )
        books[book_id] = {"book_order": book_order, "chapters": chapters}

    iconn.commit()
    return books


VALID_CHAPTER_DIGEST_MD = (
    "---\nbook_id: x\nchapter_idx: 0\nchapter_label: x\npart_label: x\n---\n"
    "## Events\n- invented\n## State changes\n- invented\n## Open questions\n- invented\n"
)

VALID_ROLLUP_DIGEST_MD = (
    "---\nbook_id: x\nlevel: part\ntarget_label: x\n---\n"
    "## Events\n- invented\n## State changes\n- invented\n## Open questions\n- invented\n"
)


def _responder(messages, system):
    """A minimal valid response for both chapter and rollup prompts -- introduces no
    entities, so this fixture stays focused purely on text leakage, not entity logic."""
    payload = json.loads(messages[0].content)
    if "paragraphs" in payload:
        return json.dumps({"digest_markdown": VALID_CHAPTER_DIGEST_MD, "entities": []})
    return json.dumps({"digest_markdown": VALID_ROLLUP_DIGEST_MD})


@pytest.fixture
def iconn(tmp_path):
    return db.connect_index(tmp_path / "index.db")


@pytest.fixture(autouse=True)
def _isolate_digest_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("BOOKLENS_DATA_DIR", str(tmp_path / "data"))


def _tokens_in(text: str):
    """Yield (book_id, chapter_idx, para_idx) for every TOK_ marker found in text."""
    for m in _TOKEN_RE.finditer(text):
        yield m.group(1), int(m.group(2)), int(m.group(3))


def _call_text(call) -> str:
    return (call.system or "") + "\n" + "\n".join(m.content for m in call.messages)


# -- 1. no prompt for chapter N contains text from above chapter N -----------------


def test_no_call_ever_sees_a_token_above_its_own_chapters_bound(iconn):
    books = _seed_two_book_series(iconn)
    llm = FakeLLM(responder=_responder)

    passes.run_chapter_pass(iconn, llm, "bk1")
    passes.run_chapter_pass(iconn, llm, "bk2")

    end_seq_by_chapter = {
        (book_id, c["chapter_idx"]): c["end_seq"]
        for book_id, info in books.items()
        for c in info["chapters"]
    }

    assert len(llm.calls) == NUM_CHAPTERS * 2

    call_idx = 0
    for book_id in ("bk1", "bk2"):
        for chapter_idx in range(NUM_CHAPTERS):
            call = llm.calls[call_idx]
            call_idx += 1
            payload = json.loads(call.messages[0].content)
            assert payload["book_id"] == book_id
            assert payload["chapter_idx"] == chapter_idx
            bound = end_seq_by_chapter[(book_id, chapter_idx)]

            blob = _call_text(call)
            for tok_book, tok_ch, tok_p in _tokens_in(blob):
                tok_seq = db.global_seq(books[tok_book]["book_order"], tok_ch, tok_p)
                assert tok_seq <= bound, (
                    f"chapter {book_id}:{chapter_idx} (bound={bound}) saw token "
                    f"TOK_{tok_book}_{tok_ch}_{tok_p} (seq={tok_seq}) from above its own bound"
                )
                # Same-book paragraphs beyond this chapter must never appear either,
                # even ones that happen to sit below the numeric bound of a later book.
                if tok_book == book_id:
                    assert tok_ch <= chapter_idx, (
                        f"chapter {book_id}:{chapter_idx} saw a same-book token from "
                        f"chapter {tok_ch}, which comes after it"
                    )


# -- 4. cross-book isolation --------------------------------------------------------


def test_book1_prompts_never_contain_book2_text(iconn):
    _seed_two_book_series(iconn)
    llm = FakeLLM(responder=_responder)
    passes.run_chapter_pass(iconn, llm, "bk1")

    for call in llm.calls:
        blob = _call_text(call)
        for tok_book, _, _ in _tokens_in(blob):
            assert tok_book != "bk2", f"book 1 call leaked a book 2 token: {blob!r}"


def test_book2_prompts_never_contain_book1_text(iconn):
    books = _seed_two_book_series(iconn)
    llm = FakeLLM(responder=_responder)
    # bk1 has to have been processed for bk2's registry_state calls to have
    # anything to potentially (and wrongly) leak from -- entity extraction
    # is per-book, so bk1's presence in the DB is the adversarial condition.
    passes.run_chapter_pass(iconn, llm, "bk1")
    llm2 = FakeLLM(responder=_responder)
    passes.run_chapter_pass(iconn, llm2, "bk2")

    for call in llm2.calls:
        blob = _call_text(call)
        for tok_book, _, _ in _tokens_in(blob):
            assert tok_book != "bk1", f"book 2 call leaked a book 1 token: {blob!r}"


# -- 6. excerpt paragraphs never appear in any prompt -------------------------------


def test_excerpt_token_never_appears_in_any_prompt(iconn):
    _seed_two_book_series(iconn)
    llm = FakeLLM(responder=_responder)
    passes.run_chapter_pass(iconn, llm, "bk1")
    passes.run_chapter_pass(iconn, llm, "bk2")
    passes.run_rollups(iconn, llm, "bk1")
    passes.run_rollups(iconn, llm, "bk2")

    for call in llm.calls:
        assert "EXCERPT_TOKEN_MUST_NEVER_APPEAR" not in _call_text(call)


# -- 3. rollups never see raw text --------------------------------------------------


def test_rollup_prompts_contain_no_raw_paragraph_tokens(iconn):
    _seed_two_book_series(iconn)
    llm = FakeLLM(responder=_responder)
    passes.run_chapter_pass(iconn, llm, "bk1")

    rollup_llm = FakeLLM(responder=_responder)
    passes.run_rollups(iconn, rollup_llm, "bk1")

    assert len(rollup_llm.calls) >= 1
    for call in rollup_llm.calls:
        blob = _call_text(call)
        assert not list(_tokens_in(blob)), f"rollup call saw raw paragraph text: {blob!r}"
        payload = json.loads(call.messages[0].content)
        assert "paragraphs" not in payload
        assert "source_digests" in payload


# -- 2. every digest row's source_end_seq is consistent with its own content -------


def test_digest_source_end_seq_matches_its_own_chapter_never_a_later_one(iconn):
    books = _seed_two_book_series(iconn)
    llm = FakeLLM(responder=_responder)
    passes.run_chapter_pass(iconn, llm, "bk1")

    rows = iconn.execute(
        "SELECT chapter_idx, source_start_seq, source_end_seq FROM digest "
        "WHERE book_id='bk1' AND level='chapter'"
    ).fetchall()
    assert len(rows) == NUM_CHAPTERS
    for r in rows:
        expected = next(c for c in books["bk1"]["chapters"] if c["chapter_idx"] == r["chapter_idx"])
        assert r["source_start_seq"] == expected["start_seq"]
        assert r["source_end_seq"] == expected["end_seq"]
        # Never stamped earlier than the content it claims to cover.
        assert r["source_end_seq"] >= r["source_start_seq"]

    # Entities are stamped no earlier than the paragraph that grounds them,
    # and no later than the chapter that produced them.
    entity_rows = iconn.execute(
        "SELECT n.first_seq, p.global_seq FROM entity_node n JOIN para p ON p.id = n.cite_para_id "
        "WHERE n.book_id='bk1'"
    ).fetchall()
    for r in entity_rows:
        assert r["first_seq"] >= r["global_seq"]


# -- 5. CausalWindow: raises above bound, unwidenable API ---------------------------


def test_causal_window_raises_above_its_own_bound(iconn):
    books = _seed_two_book_series(iconn)
    ch1 = books["bk1"]["chapters"][1]
    window = causal.CausalWindow(iconn, max_seq=ch1["start_seq"])
    with pytest.raises(ValueError):
        window.chapter_paragraphs("bk1", 1)


def test_causal_window_no_method_accepts_a_bound_shaped_parameter():
    forbidden = {"ceiling", "ceiling_seq", "max_seq", "max_ceiling", "seq_ceiling", "bound"}
    for name, member in inspect.getmembers(causal.CausalWindow, predicate=inspect.isfunction):
        if name == "__init__" or name.startswith("_"):
            continue
        sig = inspect.signature(member)
        for pname in sig.parameters:
            normalized = pname.lower().replace("-", "_")
            assert normalized not in forbidden, (
                f"CausalWindow.{name} exposes a bound-shaped parameter: {pname!r}"
            )
