"""Tests for booklens.cli: every retrieval subcommand goes through
booklens.tools.Tools, never ad-hoc SQL. Uses small synthetic EPUBs (via the
_make_epub helper from tests/test_ingest.py) so these run fast and stay
isolated from the real dev corpus."""

from __future__ import annotations

import json

import pytest

from booklens import cli
from booklens.llm.fake import FakeLLM
from tests.test_ingest import _simple_epub, _with_excerpt_epub
from tests.test_passes import _auto_responder


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("BOOKLENS_DATA_DIR", str(tmp_path / "data"))
    return tmp_path


def _run(argv):
    return cli.main(argv)


# -- status / books on an empty data dir -------------------------------


def test_status_on_empty_data_dir(data_dir, capsys):
    rc = _run(["status", "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["book_count"] == 0
    assert out["schema_version"] >= 2
    assert out["ceiling_seq"] == 0


def test_books_on_empty_data_dir(data_dir, capsys):
    rc = _run(["books", "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out == []


# -- ingest end-to-end ----------------------------------------------------


def test_ingest_then_books_and_status(data_dir, capsys):
    epub = _simple_epub(data_dir, name="book.epub")
    rc = _run(["ingest", str(epub), "--series", "s1"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Sample Book" in out
    assert "sample-book" in out

    rc = _run(["books", "--json"])
    assert rc == 0
    books = json.loads(capsys.readouterr().out)
    assert len(books) == 1
    assert books[0]["id"] == "sample-book"

    rc = _run(["status", "--json"])
    assert rc == 0
    status = json.loads(capsys.readouterr().out)
    assert status["book_count"] == 1


def test_ingest_prints_excerpt_quarantine_report(data_dir, capsys):
    epub = _with_excerpt_epub(data_dir, name="book2.epub")
    rc = _run(["ingest", str(epub), "--series", "s1"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "QUARANTINED as excerpt" in out
    assert "Excerpt from Sequel" in out


def test_ingest_no_excerpt_reports_none_detected(data_dir, capsys):
    epub = _simple_epub(data_dir, name="book.epub")
    _run(["ingest", str(epub), "--series", "s1"])
    out = capsys.readouterr().out
    assert "no excerpt back matter detected" in out


def test_ingest_prints_size_flag_report(data_dir, capsys):
    # _simple_epub's chapters are all a handful of words, well under the
    # likely-boilerplate threshold -- the report should flag them without
    # dropping or reclassifying anything (see test_ingest.py for that check).
    epub = _simple_epub(data_dir, name="book.epub")
    rc = _run(["ingest", str(epub), "--series", "s1"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "SIZE FLAG" in out
    assert "Prologue" in out


def test_ingest_json_output_is_parseable(data_dir, capsys):
    epub = _simple_epub(data_dir, name="book.epub")
    rc = _run(["ingest", str(epub), "--series", "s1", "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["book_id"] == "sample-book"
    assert out["skipped"] is False


def test_ingest_second_run_is_skipped(data_dir, capsys):
    epub = _simple_epub(data_dir, name="book.epub")
    _run(["ingest", str(epub), "--series", "s1"])
    capsys.readouterr()
    rc = _run(["ingest", str(epub), "--series", "s1"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "skipped" in out


# -- adopt-sources ---------------------------------------------------------


def test_adopt_sources_reports_the_three_outcomes(data_dir, capsys):
    from booklens import db as db_module
    from booklens import paths

    # A normal ingest is already self-contained -- ingest_book adopts its own
    # copy as its final step.
    already = _simple_epub(data_dir, name="already.epub", title="Already Book")
    _run(["ingest", str(already), "--series", "s1"])
    capsys.readouterr()

    # A "legacy" row, as if ingested before this feature existed: its
    # source_path is reset (by hand, simulating old data) to point outside
    # the library, at a file that still exists.
    external = _simple_epub(data_dir, name="external.epub", title="External Book")
    _run(["ingest", str(external), "--series", "s2"])
    capsys.readouterr()

    iconn = db_module.connect_index(paths.index_db_path())
    external_book_id = iconn.execute(
        "SELECT id FROM book WHERE title = 'External Book'"
    ).fetchone()["id"]
    iconn.execute(
        "UPDATE book SET source_path = ? WHERE id = ?", (str(external), external_book_id)
    )
    iconn.commit()

    # A book whose source has vanished entirely -- original deleted, and
    # (simulating data loss) its already-adopted copy deleted too.
    doomed = _simple_epub(data_dir, name="doomed.epub", title="Doomed Book")
    _run(["ingest", str(doomed), "--series", "s3"])
    capsys.readouterr()
    doomed_book_id = iconn.execute(
        "SELECT id FROM book WHERE title = 'Doomed Book'"
    ).fetchone()["id"]
    adopted_doomed_copy = paths.book_dir(doomed_book_id) / "doomed.epub"
    doomed.unlink()
    adopted_doomed_copy.unlink()
    # `adopt_source` only trusts the DB row, not the filesystem -- point it
    # back at the now-deleted original so this book is genuinely sourceless.
    iconn.execute(
        "UPDATE book SET source_path = ? WHERE id = ?", (str(doomed), doomed_book_id)
    )
    iconn.commit()

    rc = _run(["adopt-sources", "--json"])
    assert rc == 0
    results = json.loads(capsys.readouterr().out)
    outcomes = {r["book_id"]: r["outcome"] for r in results}
    assert outcomes[external_book_id] == "adopted"
    assert outcomes["already-book"] == "already_adopted"
    assert outcomes[doomed_book_id] == "source_missing"
    assert external.is_file()  # adoption copies, never moves or deletes the user's file

    # Safe to run again: the freshly-adopted book now reports
    # "already_adopted", and nothing raises or duplicates.
    rc = _run(["adopt-sources", "--json"])
    assert rc == 0
    results2 = json.loads(capsys.readouterr().out)
    outcomes2 = {r["book_id"]: r["outcome"] for r in results2}
    assert outcomes2[external_book_id] == "already_adopted"
    assert outcomes2["already-book"] == "already_adopted"
    assert outcomes2[doomed_book_id] == "source_missing"


# -- reindex ----------------------------------------------------------------


def test_reindex_rebuilds_from_source_epubs(data_dir, capsys):
    from booklens import paths

    epub = _simple_epub(data_dir, name="book.epub")
    _run(["ingest", str(epub), "--series", "s1"])
    capsys.readouterr()

    rc = _run(["reindex", "--json"])
    assert rc == 0
    reindexed = json.loads(capsys.readouterr().out)
    assert len(reindexed) == 1
    assert reindexed[0]["book_id"] == "sample-book"

    assert paths.index_db_path().with_name("index.db.bak").is_file()

    rc = _run(["books", "--json"])
    assert rc == 0
    books = json.loads(capsys.readouterr().out)
    assert len(books) == 1
    assert books[0]["id"] == "sample-book"


def test_reindex_survives_deletion_of_the_original_source_epub(data_dir, capsys):
    """The point of ingest-time source adoption: moving or deleting the
    user's own file no longer breaks reindex, because the library kept its
    own copy."""
    epub = _simple_epub(data_dir, name="book.epub")
    _run(["ingest", str(epub), "--series", "s1"])
    capsys.readouterr()
    epub.unlink()

    rc = _run(["reindex", "--json"])
    assert rc == 0


def test_reindex_aborts_and_restores_when_source_missing(data_dir, capsys):
    from booklens import db as db_module
    from booklens import paths

    epub = _simple_epub(data_dir, name="book.epub")
    _run(["ingest", str(epub), "--series", "s1"])
    capsys.readouterr()

    # A genuinely sourceless book -- both the user's original and the
    # library's own adopted copy are gone.
    iconn = db_module.connect_index(paths.index_db_path())
    book_id = iconn.execute("SELECT id FROM book").fetchone()["id"]
    (paths.book_dir(book_id) / "book.epub").unlink()
    epub.unlink()

    rc = _run(["reindex", "--json"])
    assert rc == 1
    capsys.readouterr()

    # index.db must be untouched -- the book is still there under its old schema.
    rc = _run(["books", "--json"])
    assert rc == 0
    books = json.loads(capsys.readouterr().out)
    assert len(books) == 1


def test_reindex_no_index_db_fails_cleanly(data_dir, capsys):
    rc = _run(["reindex", "--json"])
    assert rc == 1


# -- progress -------------------------------------------------------------


def test_progress_sets_status_and_prints_resolved_boundary(data_dir, capsys):
    epub = _simple_epub(data_dir, name="book.epub")
    _run(["ingest", str(epub), "--series", "s1"])
    capsys.readouterr()

    rc = _run(["progress", "sample-book", "--status", "reading", "--chapter", "prologue"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "sample-book" in out
    assert "ceiling_seq" in out
    assert "resolved boundary" in out


def test_progress_json_output(data_dir, capsys):
    epub = _simple_epub(data_dir, name="book.epub")
    _run(["ingest", str(epub), "--series", "s1"])
    capsys.readouterr()

    rc = _run(["progress", "sample-book", "--status", "finished", "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "finished"
    assert out["ceiling_seq"] > 0
    assert out["resolved_chapter_label"] is not None


def test_progress_chapter_takes_printed_number_not_internal_index(data_dir, capsys):
    # _simple_epub is [Prologue, Chapter 1, Chapter 2] -- internal chapter_idx
    # 1 is printed "Chapter 1", so --chapter 1 must resolve to that, not to
    # internal chapter_idx 1 by coincidence-free construction.
    epub = _simple_epub(data_dir, name="book.epub")
    _run(["ingest", str(epub), "--series", "s1"])
    capsys.readouterr()

    rc = _run(["progress", "sample-book", "--status", "reading", "--chapter", "1", "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["resolved_chapter_label"] == "Chapter 1"


def test_progress_unresolvable_chapter_fails_clean(data_dir, capsys):
    epub = _simple_epub(data_dir, name="book.epub")
    _run(["ingest", str(epub), "--series", "s1"])
    capsys.readouterr()

    rc = _run(["progress", "sample-book", "--status", "reading", "--chapter", "999"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "error" in err.lower()


def test_positions_hides_titles_above_ceiling(data_dir, capsys):
    epub = _simple_epub(data_dir, name="book.epub")
    _run(["ingest", str(epub), "--series", "s1"])
    capsys.readouterr()
    _run(["progress", "sample-book", "--status", "reading", "--chapter", "prologue"])
    capsys.readouterr()

    rc = _run(["positions", "sample-book", "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    by_number = {e["number"]: e for e in out["positions"] if "number" in e}
    assert "label" not in by_number[1]
    assert "label" not in by_number[2]
    named = [e for e in out["positions"] if e.get("name") == "prologue"]
    assert named[0]["label"] == "Prologue"


# -- chapters / read / search / context / first-seen -----------------------


def test_chapters_respects_ceiling(data_dir, capsys):
    epub = _simple_epub(data_dir, name="book.epub")
    _run(["ingest", str(epub), "--series", "s1"])
    capsys.readouterr()
    _run(["progress", "sample-book", "--status", "reading", "--chapter", "prologue"])
    capsys.readouterr()

    rc = _run(["chapters", "sample-book", "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert len(out["chapters"]) == 1
    assert out["chapters"][0]["label"] == "Prologue"


def test_read_prints_paragraphs_and_truncation_marker(data_dir, capsys):
    epub = _simple_epub(data_dir, name="book.epub")
    _run(["ingest", str(epub), "--series", "s1"])
    capsys.readouterr()
    _run(["progress", "sample-book", "--status", "reading", "--chapter", "prologue"])
    capsys.readouterr()

    rc = _run(["read", "sample-book", "--from", "0", "--to", "2"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Once upon a time." in out
    assert "truncated at" in out
    # chapter 1/2 content must never appear before the reader has read them.
    assert "story begins" not in out


def test_search_finds_readable_text_only(data_dir, capsys):
    epub = _simple_epub(data_dir, name="book.epub")
    _run(["ingest", str(epub), "--series", "s1"])
    capsys.readouterr()
    _run(["progress", "sample-book", "--status", "finished"])
    capsys.readouterr()

    rc = _run(["search", "story begins", "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert len(out["results"]) == 1


def test_search_never_surfaces_excerpt_rows(data_dir, capsys):
    epub = _with_excerpt_epub(data_dir, name="book2.epub")
    _run(["ingest", str(epub), "--series", "s1"])
    capsys.readouterr()
    _run(["progress", "book-with-excerpt", "--status", "finished"])
    capsys.readouterr()

    rc = _run(["search", "Spoiler paragraph", "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["results"] == []


def test_first_seen_json(data_dir, capsys):
    epub = _simple_epub(data_dir, name="book.epub")
    _run(["ingest", str(epub), "--series", "s1"])
    capsys.readouterr()
    _run(["progress", "sample-book", "--status", "finished"])
    capsys.readouterr()

    rc = _run(["first-seen", "story", "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["result"] == "FOUND"


def test_context_around_a_citation(data_dir, capsys):
    epub = _simple_epub(data_dir, name="book.epub")
    _run(["ingest", str(epub), "--series", "s1"])
    capsys.readouterr()
    _run(["progress", "sample-book", "--status", "finished"])
    capsys.readouterr()

    rc = _run(["context", "sample-book:0:p0", "--window", "1", "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["paragraphs"][0]["citation_id"] == "sample-book:0:p0"


def test_context_bad_citation_reports_error_not_traceback(data_dir, capsys):
    epub = _simple_epub(data_dir, name="book.epub")
    _run(["ingest", str(epub), "--series", "s1"])
    capsys.readouterr()

    rc = _run(["context", "not-a-citation"])
    assert rc == 1
    out = capsys.readouterr().out
    assert "error" in out.lower()


def test_cast_is_stub(data_dir, capsys):
    rc = _run(["cast", "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["cast"] == []


# -- digest -----------------------------------------------------------------


def test_digest_default_provider_is_fake_and_fails_cleanly_without_a_traceback(data_dir, capsys):
    """The default fake provider has no scripted response, so the pass fails on unparseable
    output -- but it must fail with a clean message, never a traceback, and never call the SDK."""
    epub = _simple_epub(data_dir, name="book.epub")
    _run(["ingest", str(epub), "--series", "s1"])
    capsys.readouterr()

    rc = _run(["digest", "sample-book"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "error" in err.lower()


def test_digest_runs_book_and_reports_progress(data_dir, capsys, monkeypatch):
    epub = _simple_epub(data_dir, name="book.epub")
    _run(["ingest", str(epub), "--series", "s1"])
    capsys.readouterr()

    monkeypatch.setattr(cli, "get_provider", lambda name, **kw: FakeLLM(responder=_auto_responder()))

    rc = _run(["digest", "sample-book"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "chapter" in out
    assert "chapters_processed=3" in out
    assert "calls_made=" in out


def test_digest_json_suppresses_progress_lines_and_reports_totals(data_dir, capsys, monkeypatch):
    epub = _simple_epub(data_dir, name="book.epub")
    _run(["ingest", str(epub), "--series", "s1"])
    capsys.readouterr()

    monkeypatch.setattr(cli, "get_provider", lambda name, **kw: FakeLLM(responder=_auto_responder()))

    rc = _run(["digest", "sample-book", "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["chapters_processed"] == 3
    assert out["llm_calls_made"] > 0
    assert "llm_cost_usd" in out


def test_digest_no_resume_reprocesses_everything(data_dir, capsys, monkeypatch):
    epub = _simple_epub(data_dir, name="book.epub")
    _run(["ingest", str(epub), "--series", "s1"])
    capsys.readouterr()

    monkeypatch.setattr(cli, "get_provider", lambda name, **kw: FakeLLM(responder=_auto_responder()))
    _run(["digest", "sample-book"])
    capsys.readouterr()

    monkeypatch.setattr(cli, "get_provider", lambda name, **kw: FakeLLM(responder=_auto_responder()))
    rc = _run(["digest", "sample-book", "--no-resume", "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["chapters_processed"] == 3
    assert out["chapters_skipped"] == 0


def test_digest_resume_skips_already_digested_chapters(data_dir, capsys, monkeypatch):
    epub = _simple_epub(data_dir, name="book.epub")
    _run(["ingest", str(epub), "--series", "s1"])
    capsys.readouterr()

    monkeypatch.setattr(cli, "get_provider", lambda name, **kw: FakeLLM(responder=_auto_responder()))
    _run(["digest", "sample-book"])
    capsys.readouterr()

    monkeypatch.setattr(cli, "get_provider", lambda name, **kw: FakeLLM(responder=_auto_responder()))
    rc = _run(["digest", "sample-book", "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["chapters_processed"] == 0
    assert out["chapters_skipped"] == 3


def test_digest_budget_exceeded_reports_partial_progress_not_a_traceback(data_dir, capsys, monkeypatch):
    epub = _simple_epub(data_dir, name="book.epub")
    _run(["ingest", str(epub), "--series", "s1"])
    capsys.readouterr()

    monkeypatch.setattr(cli, "get_provider", lambda name, **kw: FakeLLM(responder=_auto_responder()))

    rc = _run(["digest", "sample-book", "--max-calls", "1"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "error" in err.lower()
    assert "partial progress" in err.lower()
