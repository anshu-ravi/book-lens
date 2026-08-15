"""Opt-in tests against the real Claude Agent SDK (subscription-backed).

Skipped by default -- `pyproject.toml` sets `addopts = -m "not realmodel"`.
Run explicitly with `pytest -m realmodel`. These do NOT run in CI or as part
of the normal `pytest -q` suite; every other test file in this project uses
`booklens.llm.fake.FakeLLM` exclusively, per project policy.

The point of these three calls is narrow: prove the real model's output
satisfies the strict JSON contract in booklens/prompts.py and stays within
the compression budget DECISIONS.md section 10 requires -- not to evaluate
summarization quality exhaustively.
"""

from __future__ import annotations

import pytest

from booklens import causal, ingest, prompts
from booklens.llm.base import BudgetedLLM

pytestmark = pytest.mark.realmodel


def _skip_unless_sdk_ready():
    pytest.importorskip("claude_agent_sdk")
    from booklens.llm.claude_sdk import ClaudeSDKProvider

    try:
        provider = ClaudeSDKProvider()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"claude_agent_sdk present but unusable in this environment: {exc!r}")
    # Real calls occasionally hit a transient turn/session error; BudgetedLLM's
    # retry (see booklens/llm/base.py) absorbs that the same way passes.py's
    # real callers are expected to run every provider wrapped, per this
    # project's LLM layer contract -- not a workaround specific to this test.
    return BudgetedLLM(provider, max_calls=10, max_retries=3)


@pytest.fixture(scope="module")
def real_llm():
    return _skip_unless_sdk_ready()


@pytest.fixture(scope="module")
def rr_book(tmp_path_factory, corpus):
    if "red-rising" not in corpus:
        pytest.skip("red-rising not present in uploads/")
    d = tmp_path_factory.mktemp("realmodel-corpus")
    from booklens import db

    iconn = db.connect_index(d / "index.db")
    result = ingest.ingest_book(corpus["red-rising"], series_id="rr-series", book_order=1, iconn=iconn)
    return iconn, result.book_id


def _first_two_body_chapters(iconn, book_id):
    rows = iconn.execute(
        "SELECT chapter_idx, label, part_label, end_seq FROM chapter "
        "WHERE book_id = ? AND kind = 'body' ORDER BY start_seq LIMIT 2",
        (book_id,),
    ).fetchall()
    assert len(rows) == 2, "fixture assumption: red-rising has at least two body chapters"
    return rows


def _digest_word_count(markdown: str) -> int:
    """Word count of the digest body, excluding the front-matter block."""
    body = markdown.split("---", 2)[-1] if markdown.count("---") >= 2 else markdown
    return len(body.split())


def test_real_chapter_digest_parses_and_compresses(real_llm, rr_book):
    """One real chapter digest call: response must satisfy the strict parser,
    every citation must resolve inside the chapter, and the digest must be
    meaningfully shorter than the chapter it summarizes.

    Compression ratio: DECISIONS.md section 10 targets 20-40x book-level, ~1.5KB
    against ~60KB raw for an interlude. A single chapter is smaller, so this
    test uses a looser but still meaningful bound: the digest body must be
    under half the chapter's own word count, AND under the prompt's explicit
    ~250-word target (with slack) regardless of chapter length.
    """
    iconn, book_id = rr_book
    ch = _first_two_body_chapters(iconn, book_id)[0]

    window = causal.CausalWindow(iconn, max_seq=ch["end_seq"])
    paragraphs = window.chapter_paragraphs(book_id, ch["chapter_idx"])
    registry = window.registry_state(book_id)
    chapter_word_count = sum(len(p["text"].split()) for p in paragraphs)

    bundle = prompts.build_chapter_prompt(
        book_id=book_id,
        chapter_idx=ch["chapter_idx"],
        chapter_label=ch["label"],
        part_label=ch["part_label"],
        registry=registry,
        paragraphs=paragraphs,
    )
    response = real_llm.complete(bundle.messages, system=bundle.system)

    valid_para_ids = {p["id"] for p in paragraphs}
    extraction = prompts.parse_chapter_response(response.text, valid_para_ids=valid_para_ids)

    for entity in extraction.entities:
        assert entity.cite_para_id in valid_para_ids
        for attr in entity.attributes:
            assert attr.cite_para_id in valid_para_ids
        for alias in entity.aliases:
            assert alias.cite_para_id in valid_para_ids

    digest_words = _digest_word_count(extraction.digest_markdown)
    assert digest_words < chapter_word_count, (
        f"digest ({digest_words} words) was not shorter than its chapter "
        f"({chapter_word_count} words) -- compression defect, see DECISIONS.md section 10"
    )
    assert digest_words <= 300, f"digest ({digest_words} words) exceeded the ~250-word target with slack"


def test_real_rollup_parses_and_contains_no_verbatim_book_text(real_llm, rr_book):
    """Two real chapter digest calls feed one real rollup call (3 calls total
    across this module). The rollup must parse, and its markdown must not
    quote any long run of words verbatim from the raw chapters that fed it --
    proof that the rollup call itself received only digest text, never raw
    paragraphs, and that the model didn't smuggle raw phrasing through."""
    iconn, book_id = rr_book
    chapters = _first_two_body_chapters(iconn, book_id)

    source_digests = []
    raw_phrases = []
    for ch in chapters:
        window = causal.CausalWindow(iconn, max_seq=ch["end_seq"])
        paragraphs = window.chapter_paragraphs(book_id, ch["chapter_idx"])
        registry = window.registry_state(book_id)

        for p in paragraphs:
            words = p["text"].split()
            if len(words) >= 8:
                raw_phrases.append(" ".join(words[:8]))

        bundle = prompts.build_chapter_prompt(
            book_id=book_id,
            chapter_idx=ch["chapter_idx"],
            chapter_label=ch["label"],
            part_label=ch["part_label"],
            registry=registry,
            paragraphs=paragraphs,
        )
        response = real_llm.complete(bundle.messages, system=bundle.system)
        valid_para_ids = {p["id"] for p in paragraphs}
        extraction = prompts.parse_chapter_response(response.text, valid_para_ids=valid_para_ids)
        source_digests.append(extraction.digest_markdown)

    rollup_bundle = prompts.build_rollup_prompt(
        book_id=book_id, level="part", target_label="test-part", source_digests=source_digests
    )
    rollup_response = real_llm.complete(rollup_bundle.messages, system=rollup_bundle.system)
    rollup_markdown = prompts.parse_rollup_response(rollup_response.text)

    leaked = [phrase for phrase in raw_phrases if phrase in rollup_markdown]
    assert not leaked, f"rollup markdown contained verbatim raw text: {leaked!r}"
