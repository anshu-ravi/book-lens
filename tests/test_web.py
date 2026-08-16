"""Tests for booklens.web.app: the HTTP surface over the bounded tool layer.

Two tests are spoiler invariants, called out explicitly: the position picker
must never leak a title above the ceiling, and citation expansion must never
reach past a session's own ceiling.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from booklens import cli, db, tools
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
