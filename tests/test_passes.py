"""Tests for booklens.passes: the chapter loop, rollups, resume, and staleness.

All book content is invented lorem-style text, per project policy.
"""

from __future__ import annotations

import json

import pytest

from booklens import causal, db, passes, prompts
from booklens.llm.base import BudgetedLLM, BudgetExceeded, Message
from booklens.llm.fake import FakeLLM

NUM_CHAPTERS = 3
PARAS_PER_CHAPTER = 3


def _seed_book(iconn, book_id="b1", book_order=1, with_front=False, part_labels=None):
    """Build a small synthetic book: optional front matter + NUM_CHAPTERS body chapters."""
    iconn.execute(
        """
        INSERT INTO book(id, sha256, title, author, source_path, series_id,
                          book_order, sequence_tier, label_tier, ingested_at)
        VALUES (?, ?, 'Title', 'Author', '/x.epub', 's1', ?, 'S1', 'L1', '2026-01-01')
        """,
        (book_id, f"sha-{book_id}", book_order),
    )

    next_idx = 0
    if with_front:
        gseq = db.global_seq(book_order, next_idx, 0)
        iconn.execute(
            "INSERT INTO para(book_id, spine_idx, para_idx, global_seq, chapter_idx, "
            "chapter_label, text, kind) VALUES (?, ?, 0, ?, ?, 'Dramatis Personae', "
            "'INVENTED front matter: Alpha is also called Ay', 'front')",
            (book_id, next_idx, gseq, next_idx),
        )
        iconn.execute(
            "INSERT INTO chapter(book_id, chapter_idx, label, part_label, start_seq, end_seq, kind) "
            "VALUES (?, ?, 'Dramatis Personae', NULL, ?, ?, 'front')",
            (book_id, next_idx, gseq, gseq),
        )
        next_idx += 1

    for ch in range(NUM_CHAPTERS):
        chapter_idx = next_idx + ch
        part_label = part_labels[ch] if part_labels else None
        seqs = []
        for p in range(PARAS_PER_CHAPTER):
            gseq = db.global_seq(book_order, chapter_idx, p)
            text = f"INVENTED_{book_id}_{chapter_idx}_{p} lorem ipsum"
            iconn.execute(
                "INSERT INTO para(book_id, spine_idx, para_idx, global_seq, chapter_idx, "
                "chapter_label, text, kind) VALUES (?, ?, ?, ?, ?, ?, ?, 'body')",
                (book_id, chapter_idx, p, gseq, chapter_idx, f"Chapter {ch}", text),
            )
            seqs.append(gseq)
        iconn.execute(
            "INSERT INTO chapter(book_id, chapter_idx, label, part_label, start_seq, end_seq, kind) "
            "VALUES (?, ?, ?, ?, ?, ?, 'body')",
            (book_id, chapter_idx, f"Chapter {ch}", part_label, seqs[0], seqs[-1]),
        )

    iconn.commit()
    return next_idx  # index of the first body chapter


VALID_DIGEST_MD = (
    "---\nseq: 1 | book: x | label: \"x\" | pov: x | location: x\n"
    "entities: []\nintroduces: []\nsource_paras: [1, 2]\n---\n"
    "## Events\n- invented\n## State changes\n- invented\n## Open questions\n- invented\n"
)


def _auto_responder(entities_by_chapter_label=None):
    """A FakeLLM responder that answers both chapter and rollup prompts validly.

    `entities_by_chapter_label` optionally injects entity records for a
    named chapter, using the first paragraph id seen in that call as the
    citation -- always inside the current chapter, since the caller only
    ever sends this chapter's own paragraphs.
    """
    entities_by_chapter_label = entities_by_chapter_label or {}

    def responder(messages: list[Message], system: str | None) -> str:
        payload = json.loads(messages[0].content)
        if "paragraphs" in payload:
            first_para_id = payload["paragraphs"][0]["para_id"]
            label = payload["chapter_label"]
            entities = entities_by_chapter_label.get(label, [])
            for e in entities:
                e.setdefault("cite_para_id", first_para_id)
                for a in e.get("attributes", []):
                    a.setdefault("cite_para_id", first_para_id)
                for al in e.get("aliases", []):
                    al.setdefault("cite_para_id", first_para_id)
            return json.dumps({"digest_markdown": VALID_DIGEST_MD, "entities": entities})
        else:
            return json.dumps({"digest_markdown": VALID_DIGEST_MD})

    return responder


@pytest.fixture(autouse=True)
def _isolate_digest_dir(tmp_path, monkeypatch):
    """Point digest file writes at this test's own tmp dir.

    The session-wide BOOKLENS_DATA_DIR override in conftest.py is shared by
    every test in the run; several tests here reuse the same synthetic
    sha256 ("sha-b1"), so without this they would all write into the same
    on-disk digests/ directory and see each other's leftover files.
    """
    monkeypatch.setenv("BOOKLENS_DATA_DIR", str(tmp_path / "data"))


@pytest.fixture
def iconn(tmp_path):
    return db.connect_index(tmp_path / "index.db")


# -- basic chapter pass ---------------------------------------------------------


def test_run_chapter_pass_writes_one_digest_per_chapter(iconn):
    _seed_book(iconn)
    llm = FakeLLM(responder=_auto_responder())
    result = passes.run_chapter_pass(iconn, llm, "b1")

    assert result.chapters_processed == NUM_CHAPTERS
    assert result.chapters_skipped == 0
    assert result.digests_written == NUM_CHAPTERS

    rows = iconn.execute("SELECT * FROM digest WHERE book_id='b1' AND level='chapter'").fetchall()
    assert len(rows) == NUM_CHAPTERS
    for r in rows:
        from pathlib import Path

        assert Path(r["path"]).is_file()
        assert Path(r["path"]).read_text() == VALID_DIGEST_MD
        assert r["schema_version"] == db.SCHEMA_VERSION
        assert r["prompt_hash"] == prompts.CHAPTER_PROMPT_HASH


def test_run_chapter_pass_mines_front_matter(iconn):
    _seed_book(iconn, with_front=True)
    llm = FakeLLM(responder=_auto_responder())
    result = passes.run_chapter_pass(iconn, llm, "b1")

    assert result.chapters_processed == NUM_CHAPTERS + 1  # + the front-matter chapter
    front_digest = iconn.execute(
        "SELECT * FROM digest WHERE book_id='b1' AND level='chapter' AND chapter_idx=0"
    ).fetchone()
    assert front_digest is not None


def test_run_chapter_pass_excludes_excerpt_chapters(iconn):
    _seed_book(iconn)
    # Tack on an excerpt chapter the pass must never touch.
    gseq = db.global_seq(1, 99, 0)
    iconn.execute(
        "INSERT INTO para(book_id, spine_idx, para_idx, global_seq, chapter_idx, chapter_label, text, kind) "
        "VALUES ('b1', 99, 0, ?, 99, 'Excerpt', 'EXCERPT_TEXT_SHOULD_NEVER_BE_PROCESSED', 'excerpt')",
        (gseq,),
    )
    iconn.execute(
        "INSERT INTO chapter(book_id, chapter_idx, label, part_label, start_seq, end_seq, kind) "
        "VALUES ('b1', 99, 'Excerpt', NULL, ?, ?, 'excerpt')",
        (gseq, gseq),
    )
    iconn.commit()

    llm = FakeLLM(responder=_auto_responder())
    passes.run_chapter_pass(iconn, llm, "b1")
    assert iconn.execute(
        "SELECT 1 FROM digest WHERE book_id='b1' AND chapter_idx=99"
    ).fetchone() is None


# -- entity extraction ------------------------------------------------------------


def test_entities_created_and_stamped_at_chapter_seq(iconn):
    _seed_book(iconn)
    entities_by_chapter = {
        "Chapter 0": [{"designator": "Alpha", "node_kind": "named"}],
    }
    llm = FakeLLM(responder=_auto_responder(entities_by_chapter))
    result = passes.run_chapter_pass(iconn, llm, "b1")

    assert result.entities_created == 1
    node = iconn.execute("SELECT * FROM entity_node WHERE book_id='b1'").fetchone()
    assert node["designator"] == "Alpha"
    ch0 = iconn.execute("SELECT end_seq FROM chapter WHERE book_id='b1' AND chapter_idx=0").fetchone()
    assert node["first_seq"] == ch0["end_seq"]


def test_alias_edge_resolves_across_chapters(iconn):
    """A later chapter can assert an alias to an entity from an earlier one; the
    edge is stamped at the LATER chapter's seq, never backdated to the earlier one."""
    _seed_book(iconn)
    entities_by_chapter = {
        "Chapter 0": [{"designator": "Alpha", "node_kind": "named"}],
        "Chapter 1": [
            {
                "designator": "Beta",
                "node_kind": "named",
                "aliases": [{"other_designator": "Alpha", "edge_type": "stated"}],
            }
        ],
    }
    llm = FakeLLM(responder=_auto_responder(entities_by_chapter))
    passes.run_chapter_pass(iconn, llm, "b1")

    edge = iconn.execute("SELECT * FROM entity_edge").fetchone()
    assert edge is not None
    ch1_end = iconn.execute("SELECT end_seq FROM chapter WHERE book_id='b1' AND chapter_idx=1").fetchone()["end_seq"]
    assert edge["revealed_at_seq"] == ch1_end


def test_alias_to_unknown_designator_raises(iconn):
    _seed_book(iconn)
    entities_by_chapter = {
        "Chapter 0": [
            {
                "designator": "Beta",
                "node_kind": "named",
                "aliases": [{"other_designator": "NeverIntroduced", "edge_type": "stated"}],
            }
        ],
    }
    llm = FakeLLM(responder=_auto_responder(entities_by_chapter))
    with pytest.raises(ValueError):
        passes.run_chapter_pass(iconn, llm, "b1")


# -- resume / staleness -----------------------------------------------------------


def test_resume_skips_chapters_with_current_digest(iconn):
    _seed_book(iconn)
    llm = FakeLLM(responder=_auto_responder())
    passes.run_chapter_pass(iconn, llm, "b1")

    llm2 = FakeLLM(responder=_auto_responder())
    result2 = passes.run_chapter_pass(iconn, llm2, "b1", resume=True)
    assert result2.chapters_processed == 0
    assert result2.chapters_skipped == NUM_CHAPTERS
    assert len(llm2.calls) == 0


def test_resume_false_reprocesses_everything(iconn):
    _seed_book(iconn)
    llm = FakeLLM(responder=_auto_responder())
    passes.run_chapter_pass(iconn, llm, "b1")

    llm2 = FakeLLM(responder=_auto_responder())
    result2 = passes.run_chapter_pass(iconn, llm2, "b1", resume=False)
    assert result2.chapters_processed == NUM_CHAPTERS
    # Still exactly one digest row per chapter -- no duplicates left behind.
    rows = iconn.execute("SELECT COUNT(*) c FROM digest WHERE book_id='b1' AND level='chapter'").fetchone()
    assert rows["c"] == NUM_CHAPTERS


def test_interrupted_run_resumes_without_regenerating_completed_chapters(iconn):
    _seed_book(iconn)
    # Fail on the 2nd LLM call -- the 2nd chapter never gets written.
    llm = FakeLLM(responder=_auto_responder(), raise_on_call={2: RuntimeError("simulated crash")})
    with pytest.raises(RuntimeError):
        passes.run_chapter_pass(iconn, llm, "b1")

    rows_after_crash = iconn.execute(
        "SELECT chapter_idx FROM digest WHERE book_id='b1' AND level='chapter'"
    ).fetchall()
    assert {r["chapter_idx"] for r in rows_after_crash} == {0}

    llm2 = FakeLLM(responder=_auto_responder())
    result = passes.run_chapter_pass(iconn, llm2, "b1", resume=True)
    assert result.chapters_skipped == 1
    assert result.chapters_processed == NUM_CHAPTERS - 1

    rows_final = iconn.execute(
        "SELECT chapter_idx FROM digest WHERE book_id='b1' AND level='chapter'"
    ).fetchall()
    assert {r["chapter_idx"] for r in rows_final} == set(range(NUM_CHAPTERS))


def test_changed_prompt_hash_marks_exactly_those_chapters_stale(iconn, monkeypatch):
    _seed_book(iconn)
    llm = FakeLLM(responder=_auto_responder())
    passes.run_chapter_pass(iconn, llm, "b1")

    # Simulate a prompt template change by patching the hash the pass compares against.
    monkeypatch.setattr(prompts, "CHAPTER_PROMPT_HASH", "changed-hash-0000")

    def responder2(messages, system):
        payload = json.loads(messages[0].content)
        first_para_id = payload["paragraphs"][0]["para_id"]
        return json.dumps({"digest_markdown": VALID_DIGEST_MD, "entities": []})

    llm2 = FakeLLM(responder=responder2)
    result = passes.run_chapter_pass(iconn, llm2, "b1", resume=True)
    assert result.chapters_processed == NUM_CHAPTERS
    assert result.chapters_skipped == 0

    rows = iconn.execute("SELECT DISTINCT prompt_hash FROM digest WHERE book_id='b1' AND level='chapter'").fetchall()
    assert [r["prompt_hash"] for r in rows] == ["changed-hash-0000"]


# -- malformed output -------------------------------------------------------------


def test_malformed_response_raises_and_writes_nothing(iconn):
    _seed_book(iconn)
    llm = FakeLLM(responses=["not valid json"])
    with pytest.raises(ValueError):
        passes.run_chapter_pass(iconn, llm, "b1")

    assert iconn.execute("SELECT 1 FROM digest WHERE book_id='b1'").fetchone() is None
    from pathlib import Path

    from booklens import paths

    sha256 = iconn.execute("SELECT sha256 FROM book WHERE id='b1'").fetchone()["sha256"]
    ch_dir = paths.digests_dir(sha256) / "ch"
    assert not ch_dir.is_dir() or list(ch_dir.iterdir()) == []


def test_malformed_response_preserves_earlier_chapters(iconn):
    _seed_book(iconn)
    good = _auto_responder()

    def responder(messages, system):
        payload = json.loads(messages[0].content)
        if payload.get("chapter_label") == "Chapter 1":
            return "not valid json, malformed on purpose"
        return good(messages, system)

    llm = FakeLLM(responder=responder)
    with pytest.raises(ValueError):
        passes.run_chapter_pass(iconn, llm, "b1")

    rows = iconn.execute("SELECT chapter_idx FROM digest WHERE book_id='b1'").fetchall()
    assert {r["chapter_idx"] for r in rows} == {0}


# -- budget -------------------------------------------------------------------------


def test_budget_exceeded_propagates_and_does_not_report_success(iconn):
    _seed_book(iconn)
    inner = FakeLLM(responder=_auto_responder())
    budgeted = BudgetedLLM(inner, max_calls=1)
    with pytest.raises(BudgetExceeded):
        passes.run_chapter_pass(iconn, budgeted, "b1")

    rows = iconn.execute("SELECT chapter_idx FROM digest WHERE book_id='b1'").fetchall()
    assert len(rows) == 1  # exactly the one call the budget allowed, no more


# -- rollups --------------------------------------------------------------------


def test_rollups_build_part_and_book_digests(iconn):
    _seed_book(iconn, part_labels=["Part One", "Part One", "Part Two"])
    llm = FakeLLM(responder=_auto_responder())
    passes.run_chapter_pass(iconn, llm, "b1")
    result = passes.run_rollups(iconn, llm, "b1")

    part_rows = iconn.execute("SELECT * FROM digest WHERE book_id='b1' AND level='part'").fetchall()
    assert {r["part_label"] for r in part_rows} == {"Part One", "Part Two"}

    book_row = iconn.execute("SELECT * FROM digest WHERE book_id='b1' AND level='book'").fetchone()
    assert book_row is not None
    assert result.digests_written == len(part_rows) + 1


def test_rollups_without_parts_roll_book_from_chapters_directly(iconn):
    _seed_book(iconn)  # no part_labels
    llm = FakeLLM(responder=_auto_responder())
    passes.run_chapter_pass(iconn, llm, "b1")
    passes.run_rollups(iconn, llm, "b1")

    assert iconn.execute("SELECT 1 FROM digest WHERE book_id='b1' AND level='part'").fetchone() is None
    book_row = iconn.execute("SELECT * FROM digest WHERE book_id='b1' AND level='book'").fetchone()
    assert book_row is not None


def test_rollup_prompts_contain_only_digest_content_not_raw_text(iconn):
    _seed_book(iconn)
    llm = FakeLLM(responder=_auto_responder())
    passes.run_chapter_pass(iconn, llm, "b1")

    recorder = FakeLLM(responder=_auto_responder())
    passes.run_rollups(iconn, recorder, "b1")

    for call in recorder.calls:
        blob = call.messages[0].content
        for ch in range(NUM_CHAPTERS):
            for p in range(PARAS_PER_CHAPTER):
                assert f"INVENTED_b1_{ch}_{p}" not in blob


def test_rollups_always_regenerate(iconn):
    _seed_book(iconn)
    llm = FakeLLM(responder=_auto_responder())
    passes.run_chapter_pass(iconn, llm, "b1")
    passes.run_rollups(iconn, llm, "b1")
    before = iconn.execute("SELECT created_at FROM digest WHERE book_id='b1' AND level='book'").fetchone()

    passes.run_rollups(iconn, llm, "b1")
    after_rows = iconn.execute("SELECT * FROM digest WHERE book_id='b1' AND level='book'").fetchall()
    assert len(after_rows) == 1  # no duplicate accumulation left behind by delete-then-insert
    assert after_rows[0]["created_at"] >= before["created_at"]


# -- run_book -----------------------------------------------------------------------


def test_run_book_runs_chapter_pass_then_rollups(iconn):
    _seed_book(iconn, part_labels=["Part One", "Part One", "Part Two"])
    llm = FakeLLM(responder=_auto_responder())
    result = passes.run_book(iconn, llm, "b1")

    assert result.chapters_processed == NUM_CHAPTERS
    assert iconn.execute("SELECT 1 FROM digest WHERE book_id='b1' AND level='book'").fetchone() is not None
    assert iconn.execute("SELECT 1 FROM digest WHERE book_id='b1' AND level='part'").fetchone() is not None


def test_run_book_resume_true_skips_completed_and_still_refreshes_rollups(iconn):
    _seed_book(iconn)
    llm = FakeLLM(responder=_auto_responder())
    passes.run_book(iconn, llm, "b1")

    llm2 = FakeLLM(responder=_auto_responder())
    result = passes.run_book(iconn, llm2, "b1", resume=True)
    assert result.chapters_processed == 0
    assert result.chapters_skipped == NUM_CHAPTERS
    # Rollups still ran (book digest still present, exactly one row).
    rows = iconn.execute("SELECT COUNT(*) c FROM digest WHERE book_id='b1' AND level='book'").fetchone()
    assert rows["c"] == 1
