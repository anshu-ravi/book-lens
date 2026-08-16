"""Tests for booklens.web.app: the HTTP surface over the bounded tool layer.

Two tests are spoiler invariants, called out explicitly: the position picker
must never leak a title above the ceiling, and citation expansion must never
reach past a session's own ceiling.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from booklens import cli, db, progress, tools
from booklens.web.app import app
from booklens.web.sessions import registry
from tests.test_ingest import _simple_epub

# Every chat-session test needs the fake provider so nothing here can spend money.
app.state.llm_provider = "fake"

client = TestClient(app)


def _setup(tmp_path, monkeypatch, status="reading", chapter="1"):
    """Ingest the sample book and (optionally) set a reading position."""
    monkeypatch.setenv("BOOKLENS_DATA_DIR", str(tmp_path / "data"))
    epub = _simple_epub(tmp_path)
    rc = cli.main(["ingest", str(epub), "--series", "s1"])
    assert rc == 0
    if status is not None:
        rc = cli.main(["progress", "sample-book", "--status", status] + (["--chapter", chapter] if chapter else []))
        assert rc == 0


# -- library ------------------------------------------------------------------


def test_library_shape_and_percent(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, status="reading", chapter="1")

    resp = client.get("/api/library")
    assert resp.status_code == 200
    body = resp.json()

    assert [s["id"] for s in body["series"]] == ["s1"]
    books = body["series"][0]["books"]
    assert len(books) == 1
    book = books[0]

    assert book["id"] == "sample-book"
    assert book["title"] == "Sample Book"
    assert book["status"] == "reading"
    assert book["chapter_count"] == 3  # Prologue, Chapter 1, Chapter 2
    assert book["chapters_read"] == 2  # Prologue + Chapter 1
    assert book["percent"] == round(100 * 2 / 3)
    assert book["position_label"] == "Chapter 1"


def test_book_without_cover_reports_false_and_cover_route_404s(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, status="reading", chapter="1")

    book = client.get("/api/library").json()["series"][0]["books"][0]
    assert book["has_cover"] is False

    resp = client.get("/api/books/sample-book/cover")
    assert resp.status_code == 404


def test_library_unread_book_has_zero_percent(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, status=None)

    book = client.get("/api/library").json()["series"][0]["books"][0]
    assert book["status"] == "unread"
    assert book["chapters_read"] == 0
    assert book["percent"] == 0
    assert book["position_label"] is None


# -- positions (spoiler invariant) --------------------------------------------


def test_positions_does_not_leak_labels_above_ceiling(tmp_path, monkeypatch):
    """Spoiler-invariant: a position past the reader's ceiling must carry no 'label' key."""
    _setup(tmp_path, monkeypatch, status="reading", chapter="1")

    resp = client.get("/api/books/sample-book/positions")
    assert resp.status_code == 200
    positions = resp.json()["positions"]

    seen_unlabeled_number = False
    for entry in positions:
        if entry.get("number") == 2:  # Chapter 2 is beyond the ceiling
            assert "label" not in entry
            seen_unlabeled_number = True
    assert seen_unlabeled_number, "expected Chapter 2 to appear withheld in the picker"


def test_positions_404_for_unknown_book(tmp_path, monkeypatch):
    monkeypatch.setenv("BOOKLENS_DATA_DIR", str(tmp_path / "data"))
    db.connect_index().close()
    resp = client.get("/api/books/no-such-book/positions")
    assert resp.status_code == 404


# -- progress -------------------------------------------------------------------


def test_put_progress_invalid_chapter_returns_400_naming_valid_chapters(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, status=None)

    resp = client.put("/api/books/sample-book/progress", json={"status": "reading", "chapter": "999"})
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert "valid printed chapters" in detail


def test_put_progress_updates_and_returns_book(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, status=None)

    resp = client.put("/api/books/sample-book/progress", json={"status": "reading", "chapter": "1"})
    assert resp.status_code == 200
    book = resp.json()
    assert book["status"] == "reading"
    assert book["position_label"] == "Chapter 1"


# -- series / upload ------------------------------------------------------------


def test_series_reports_next_order(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, status=None)

    resp = client.get("/api/series")
    assert resp.status_code == 200
    series = resp.json()["series"]
    assert series == [{"id": "s1", "book_count": 1, "next_order": 2}]


def test_upload_ingests_and_reports_manifest(tmp_path, monkeypatch):
    monkeypatch.setenv("BOOKLENS_DATA_DIR", str(tmp_path / "data"))
    db.connect_index().close()  # establish the data dir before upload

    epub_path = _simple_epub(tmp_path, name="uploaded.epub")
    with open(epub_path, "rb") as f:
        resp = client.post(
            "/api/upload",
            files={"file": ("uploaded.epub", f, "application/epub+zip")},
            data={"series": "s2"},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["book_id"] == "sample-book"
    assert body["series_id"] == "s2"
    assert body["book_order"] == 1
    assert body["chapters"] == 3
    assert body["skipped"] is False
    assert isinstance(body["excerpt_chapters"], list)


# -- shelf placement -------------------------------------------------------------


def test_library_marks_single_book_series_standalone_only_when_flagged(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, status=None)

    series = client.get("/api/library").json()["series"]
    assert series[0]["standalone"] is False

    resp = client.put(
        "/api/books/sample-book/shelf",
        json={"series_id": "s1", "book_order": 1, "standalone": True},
    )
    assert resp.status_code == 200

    series = client.get("/api/library").json()["series"]
    assert series[0]["standalone"] is True


def test_shelf_flag_only_toggle_does_not_reingest(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, status=None)
    iconn = db.connect_index()
    before = iconn.execute(
        "SELECT ingested_at FROM book WHERE id = 'sample-book'"
    ).fetchone()["ingested_at"]
    para_ids_before = [
        r["id"] for r in iconn.execute("SELECT id FROM para WHERE book_id = 'sample-book' ORDER BY id")
    ]

    resp = client.put(
        "/api/books/sample-book/shelf",
        json={"series_id": "s1", "book_order": 1, "standalone": True},
    )
    assert resp.status_code == 200
    assert resp.json()["standalone"] is True

    after = iconn.execute(
        "SELECT ingested_at FROM book WHERE id = 'sample-book'"
    ).fetchone()["ingested_at"]
    para_ids_after = [
        r["id"] for r in iconn.execute("SELECT id FROM para WHERE book_id = 'sample-book' ORDER BY id")
    ]
    assert after == before
    assert para_ids_after == para_ids_before


def test_shelf_move_to_occupied_slot_returns_409_and_changes_nothing(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, status=None)
    epub2 = _simple_epub(tmp_path, name="book2.epub", title="Second Book")
    rc = cli.main(["ingest", str(epub2), "--series", "s1", "--start-order", "2"])
    assert rc == 0

    iconn = db.connect_index()
    before = dict(
        iconn.execute("SELECT series_id, book_order FROM book WHERE id = 'sample-book'").fetchone()
    )

    resp = client.put(
        "/api/books/sample-book/shelf",
        json={"series_id": "s1", "book_order": 2, "standalone": False},
    )
    assert resp.status_code == 409

    after = dict(
        iconn.execute("SELECT series_id, book_order FROM book WHERE id = 'sample-book'").fetchone()
    )
    assert after == before


def test_shelf_move_rebases_ceiling_to_the_same_chapter(tmp_path, monkeypatch):
    """The invariant test: moving book_order must not leave a stale ceiling
    that resolves to the wrong chapter (or none at all)."""
    _setup(tmp_path, monkeypatch, status="reading", chapter="1")

    iconn = db.connect_index()
    pconn = db.connect_progress()
    with tools.Tools(iconn, pconn) as t:
        before_paras = t.read_raw("sample-book", 0, 2)["paragraphs"]
    assert before_paras  # sanity: reading position actually exposes text

    resp = client.put(
        "/api/books/sample-book/shelf",
        json={"series_id": "s1", "book_order": 3, "standalone": False},
    )
    assert resp.status_code == 200
    book = resp.json()
    assert book["position_label"] == "Chapter 1"

    iconn2 = db.connect_index()
    pconn2 = db.connect_progress()
    with tools.Tools(iconn2, pconn2) as t:
        after_paras = t.read_raw("sample-book", 0, 2)["paragraphs"]

    before_texts = {p["text"] for p in before_paras}
    after_texts = {p["text"] for p in after_paras}
    assert after_texts == before_texts

    new_book_row = iconn2.execute(
        "SELECT book_order FROM book WHERE id = 'sample-book'"
    ).fetchone()
    assert new_book_row["book_order"] == 3
    ceiling = pconn2.execute(
        "SELECT ceiling_seq FROM book_progress WHERE book_id = 'sample-book'"
    ).fetchone()["ceiling_seq"]
    # The ceiling must sit within this book's new range and at the same
    # chapter boundary -- not a leftover value from book_order=1's numbering.
    chapter_end = progress.chapter_end_seq(iconn2, "sample-book", 1)
    assert ceiling == chapter_end
    assert ceiling >= 3_000_000


def test_shelf_move_400s_when_source_file_is_gone(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, status=None)
    iconn = db.connect_index()
    source_path = iconn.execute(
        "SELECT source_path FROM book WHERE id = 'sample-book'"
    ).fetchone()["source_path"]
    Path(source_path).unlink()

    resp = client.put(
        "/api/books/sample-book/shelf",
        json={"series_id": "s1", "book_order": 5, "standalone": False},
    )
    assert resp.status_code == 400


# -- chat -----------------------------------------------------------------------


def test_create_session_without_position_returns_409(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, status=None)

    resp = client.post("/api/chat/sessions", json={"book_id": "sample-book"})
    assert resp.status_code == 409
    assert "sample-book" in resp.json()["detail"]


def test_chat_session_answers_and_undo_removes_the_exchange(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, status="reading", chapter="1")

    create = client.post("/api/chat/sessions", json={"book_id": "sample-book"})
    assert create.status_code == 200
    payload = create.json()
    sid = payload["session_id"]
    assert payload["book_title"] == "Sample Book"
    assert payload["prior_titles"] == []
    assert payload["para_count"] > 0

    record = registry.get(sid)
    assert record is not None
    assert len(record.session.history) == 0

    ask = client.post(f"/api/chat/sessions/{sid}/messages", json={"question": "what happens?"})
    assert ask.status_code == 200
    body = ask.json()
    assert isinstance(body["answer"], str)  # FakeLLM with no script returns ""
    assert body["citations"] == []
    assert "debug" in body and "session_cost_usd" in body["debug"]

    assert len(record.session.history) == 2  # one user turn, one assistant turn

    undo = client.post(f"/api/chat/sessions/{sid}/undo")
    assert undo.status_code == 200
    assert undo.json() == {"ok": True, "turns": 0}
    assert len(record.session.history) == 0

    # undo on an empty history is a no-op, not an error
    undo2 = client.post(f"/api/chat/sessions/{sid}/undo")
    assert undo2.status_code == 200
    assert undo2.json() == {"ok": True, "turns": 0}

    delete = client.delete(f"/api/chat/sessions/{sid}")
    assert delete.status_code == 204
    assert registry.get(sid) is None


def test_citation_above_session_ceiling_returns_404(tmp_path, monkeypatch):
    """Spoiler-invariant: expanding a citation past the session's ceiling must 404, not leak text."""
    _setup(tmp_path, monkeypatch, status="reading", chapter="1")

    create = client.post("/api/chat/sessions", json={"book_id": "sample-book"})
    sid = create.json()["session_id"]

    # Chapter 2 (spine_idx=2) is beyond the ceiling for --chapter 1.
    beyond_ceiling_citation = tools.format_citation_id("sample-book", 2, 0)
    resp = client.get(f"/api/chat/sessions/{sid}/citations/{beyond_ceiling_citation}")
    assert resp.status_code == 404


def test_messages_404_for_unknown_session():
    resp = client.post("/api/chat/sessions/does-not-exist/messages", json={"question": "hi?"})
    assert resp.status_code == 404
