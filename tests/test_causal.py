"""Tests for booklens.causal: the bounded generation window.

Mirrors tests/test_cutoff_invariant.py's style for booklens.tools -- the
window's bound must be fixed at construction and unwidenable by any method.
"""

from __future__ import annotations

import inspect

import pytest

from booklens import causal, db

NUM_CHAPTERS = 3
PARAS_PER_CHAPTER = 4


def _build_book(iconn, book_id="b1", book_order=1, with_front=False):
    iconn.execute(
        """
        INSERT INTO book(id, sha256, title, author, source_path, series_id,
                          book_order, sequence_tier, label_tier, ingested_at)
        VALUES (?, ?, 'Title', 'Author', '/x.epub', 's1', ?, 'S1', 'L1', '2026-01-01')
        """,
        (book_id, f"sha-{book_id}", book_order),
    )

    chapters = []
    next_idx = 0

    if with_front:
        gseq = db.global_seq(book_order, next_idx, 0)
        iconn.execute(
            """
            INSERT INTO para(book_id, spine_idx, para_idx, global_seq, chapter_idx,
                              chapter_label, text, kind)
            VALUES (?, ?, 0, ?, ?, 'Dramatis Personae', 'INVENTED_FRONT_TEXT alpha is beta', 'reference')
            """,
            (book_id, next_idx, gseq, next_idx),
        )
        iconn.execute(
            """
            INSERT INTO chapter(book_id, chapter_idx, label, part_label, start_seq, end_seq, kind)
            VALUES (?, ?, 'Dramatis Personae', NULL, ?, ?, 'reference')
            """,
            (book_id, next_idx, gseq, gseq),
        )
        chapters.append({"chapter_idx": next_idx, "start_seq": gseq, "end_seq": gseq, "kind": "reference"})
        next_idx += 1

    for ch in range(NUM_CHAPTERS):
        chapter_idx = next_idx + ch
        seqs = []
        for p in range(PARAS_PER_CHAPTER):
            gseq = db.global_seq(book_order, chapter_idx, p)
            text = f"INVENTED_TOKEN_{book_id}_{chapter_idx}_{p}"
            iconn.execute(
                """
                INSERT INTO para(book_id, spine_idx, para_idx, global_seq, chapter_idx,
                                  chapter_label, text, kind)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'body')
                """,
                (book_id, chapter_idx, p, gseq, chapter_idx, f"Chapter {ch}", text),
            )
            seqs.append(gseq)
        start, end = seqs[0], seqs[-1]
        iconn.execute(
            """
            INSERT INTO chapter(book_id, chapter_idx, label, part_label, start_seq, end_seq, kind)
            VALUES (?, ?, ?, NULL, ?, ?, 'body')
            """,
            (book_id, chapter_idx, f"Chapter {ch}", start, end),
        )
        chapters.append({"chapter_idx": chapter_idx, "start_seq": start, "end_seq": end, "kind": "body"})

    # An excerpt chapter tacked on the end, numerically inside this book's range,
    # so it can be checked for exclusion even from a window bounded past it.
    excerpt_idx = next_idx + NUM_CHAPTERS
    gseq = db.global_seq(book_order, excerpt_idx, 0)
    iconn.execute(
        """
        INSERT INTO para(book_id, spine_idx, para_idx, global_seq, chapter_idx,
                          chapter_label, text, kind)
        VALUES (?, ?, 0, ?, ?, 'Excerpt', 'INVENTED_EXCERPT_TEXT_should_never_appear', 'excerpt')
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

    iconn.commit()
    return chapters


@pytest.fixture
def iconn(tmp_path):
    return db.connect_index(tmp_path / "index.db")


def test_chapters_excludes_above_bound(iconn):
    chapters = _build_book(iconn)
    window = causal.CausalWindow(iconn, max_seq=chapters[0]["end_seq"])
    result = window.chapters("b1")
    assert [c["chapter_idx"] for c in result] == [0]


def test_chapters_includes_front_matter(iconn):
    chapters = _build_book(iconn, with_front=True)
    window = causal.CausalWindow(iconn, max_seq=chapters[-1]["end_seq"])
    result = window.chapters("b1")
    kinds = {c["chapter_idx"]: c["kind"] for c in result}
    assert kinds[0] == "reference"


def test_chapters_never_includes_excerpt(iconn):
    chapters = _build_book(iconn)
    huge = chapters[-1]["end_seq"] + 1_000_000
    window = causal.CausalWindow(iconn, max_seq=huge)
    result = window.chapters("b1")
    assert all(c["kind"] != "excerpt" for c in result)


def test_chapter_paragraphs_returns_full_chapter(iconn):
    chapters = _build_book(iconn)
    window = causal.CausalWindow(iconn, max_seq=chapters[0]["end_seq"])
    paras = window.chapter_paragraphs("b1", 0)
    assert len(paras) == PARAS_PER_CHAPTER
    assert all(p["global_seq"] <= chapters[0]["end_seq"] for p in paras)


def test_chapter_paragraphs_raises_above_bound(iconn):
    chapters = _build_book(iconn)
    # Bound sits inside chapter 1, so chapter 1's own end_seq exceeds it.
    window = causal.CausalWindow(iconn, max_seq=chapters[1]["start_seq"])
    with pytest.raises(ValueError):
        window.chapter_paragraphs("b1", 1)


def test_chapter_paragraphs_raises_on_excerpt(iconn):
    chapters = _build_book(iconn)
    excerpt_idx = chapters[-1]["chapter_idx"] + 1
    huge = chapters[-1]["end_seq"] + 1_000_000
    window = causal.CausalWindow(iconn, max_seq=huge)
    with pytest.raises(ValueError):
        window.chapter_paragraphs("b1", excerpt_idx)


def test_chapter_paragraphs_raises_on_unknown_chapter(iconn):
    _build_book(iconn)
    window = causal.CausalWindow(iconn, max_seq=10**9)
    with pytest.raises(ValueError):
        window.chapter_paragraphs("b1", 999)


def test_paragraphs_in_range_raises_when_end_exceeds_bound(iconn):
    chapters = _build_book(iconn)
    window = causal.CausalWindow(iconn, max_seq=chapters[0]["end_seq"])
    with pytest.raises(ValueError):
        window.paragraphs_in_range("b1", chapters[0]["start_seq"], chapters[1]["end_seq"])


def test_paragraphs_in_range_excludes_excerpts(iconn):
    chapters = _build_book(iconn)
    huge = chapters[-1]["end_seq"] + 1_000_000
    window = causal.CausalWindow(iconn, max_seq=huge)
    paras = window.paragraphs_in_range("b1", 0, huge)
    assert all("EXCERPT" not in p["text"] for p in paras)


def test_registry_state_filters_nodes_edges_attrs_by_bound(iconn):
    chapters = _build_book(iconn)
    early_para = iconn.execute(
        "SELECT id FROM para WHERE book_id='b1' AND chapter_idx=0 ORDER BY para_idx LIMIT 1"
    ).fetchone()["id"]
    late_para = iconn.execute(
        "SELECT id FROM para WHERE book_id='b1' AND chapter_idx=2 ORDER BY para_idx LIMIT 1"
    ).fetchone()["id"]

    iconn.execute(
        "INSERT INTO entity_node(id, book_id, designator, node_kind, first_seq, cite_para_id) "
        "VALUES (1, 'b1', 'Alpha', 'named', ?, ?)",
        (chapters[0]["end_seq"], early_para),
    )
    iconn.execute(
        "INSERT INTO entity_node(id, book_id, designator, node_kind, first_seq, cite_para_id) "
        "VALUES (2, 'b1', 'Omega', 'named', ?, ?)",
        (chapters[2]["end_seq"], late_para),
    )
    iconn.execute(
        "INSERT INTO entity_attr(node_id, attr_kind, value, first_seq, cite_para_id) "
        "VALUES (1, 'trait', 'invented', ?, ?)",
        (chapters[0]["end_seq"], early_para),
    )
    iconn.execute(
        "INSERT INTO entity_edge(src_node_id, dst_node_id, edge_type, revealed_at_seq, cite_para_id) "
        "VALUES (2, 1, 'stated', ?, ?)",
        (chapters[2]["end_seq"], late_para),
    )
    iconn.commit()

    window = causal.CausalWindow(iconn, max_seq=chapters[0]["end_seq"])
    registry = window.registry_state("b1")
    assert [n["designator"] for n in registry["nodes"]] == ["Alpha"]
    assert registry["edges"] == []
    assert len(registry["attrs"]) == 1

    wide_window = causal.CausalWindow(iconn, max_seq=chapters[2]["end_seq"])
    wide_registry = wide_window.registry_state("b1")
    assert {n["designator"] for n in wide_registry["nodes"]} == {"Alpha", "Omega"}
    assert len(wide_registry["edges"]) == 1


def test_no_method_accepts_a_bound_shaped_parameter():
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


def test_init_only_place_max_seq_is_set():
    sig = inspect.signature(causal.CausalWindow.__init__)
    assert "max_seq" in sig.parameters


# -- real corpus, no model call ----------------------------------------------


def test_causal_window_walks_real_ingested_book_without_error(tmp_path, corpus):
    """Proves CausalWindow holds up against real publisher structure -- real
    chapter counts, real front matter, real excerpt back matter -- not just
    the synthetic fixture above. No model call: this only exercises retrieval."""
    if "red-rising" not in corpus:
        pytest.skip("red-rising not present in uploads/")

    from booklens import ingest

    iconn = db.connect_index(tmp_path / "index.db")
    result = ingest.ingest_book(corpus["red-rising"], series_id="rr-series", book_order=1, iconn=iconn)
    book_id = result.book_id

    all_chapters = iconn.execute(
        "SELECT chapter_idx, end_seq, kind FROM chapter WHERE book_id = ? ORDER BY start_seq",
        (book_id,),
    ).fetchall()
    body_and_front = [c for c in all_chapters if c["kind"] != "excerpt"]
    excerpt = [c for c in all_chapters if c["kind"] == "excerpt"]
    assert body_and_front, "fixture assumption: red-rising has non-excerpt chapters"

    final_end_seq = body_and_front[-1]["end_seq"]
    window = causal.CausalWindow(iconn, max_seq=final_end_seq)

    windowed_chapters = window.chapters(book_id)
    assert len(windowed_chapters) == len(body_and_front)
    assert all(c["kind"] != "excerpt" for c in windowed_chapters)

    total_paragraphs = 0
    for ch in windowed_chapters:
        paras = window.chapter_paragraphs(book_id, ch["chapter_idx"])
        assert paras, f"chapter {ch['chapter_idx']} yielded no paragraphs"
        total_paragraphs += len(paras)
    assert total_paragraphs > 0

    if excerpt:
        # A window bounded exactly at the last body chapter must never be
        # askable for the excerpt chapter that follows it.
        with pytest.raises(ValueError):
            window.chapter_paragraphs(book_id, excerpt[0]["chapter_idx"])

    registry = window.registry_state(book_id)
    assert registry == {"nodes": [], "edges": [], "attrs": []}  # no digest pass has run yet
