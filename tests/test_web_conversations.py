"""Tests for saved chat conversations: the HTTP surface and what it persists.

One is a spoiler invariant: a conversation reopened after the reader has moved
on is re-ceilinged at the *new* position, and the stored turns keep the position
they were answered at.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from booklens import conversations, db, paths
from booklens.web.app import app
from booklens.web.sessions import registry
from tests.test_web import _setup

app.state.llm_provider = "fake"

client = TestClient(app)


def _new_conversation(book_id: str = "sample-book"):
    resp = client.post("/api/chat/conversations", json={"book_id": book_id})
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_new_conversation_starts_empty_and_is_pinned_to_the_reading_position(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, status="reading", chapter="1")

    payload = _new_conversation()
    assert payload["turns"] == []
    assert payload["book_title"] == "Sample Book"
    assert payload["moved_on"] is False
    assert payload["conversation"]["turn_count"] == 0
    # An unnamed conversation has no title until its first question names it.
    assert payload["conversation"]["title"] == ""

    record = registry.get(payload["session_id"])
    assert record is not None
    assert record.conversation_id == payload["conversation"]["id"]


def test_conversation_without_a_reading_position_is_refused(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, status=None)

    resp = client.post("/api/chat/conversations", json={"book_id": "sample-book"})
    assert resp.status_code == 409
    assert "sample-book" in resp.json()["detail"]


def test_a_turn_is_persisted_and_names_the_conversation(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, status="reading", chapter="1")
    cid = _new_conversation()["conversation"]["id"]

    ask = client.post(
        f"/api/chat/conversations/{cid}/messages", json={"question": "Who is in this chapter?"}
    )
    assert ask.status_code == 200, ask.text
    body = ask.json()
    assert "answer" in body and "debug" in body
    assert body["conversation"]["title"] == "Who is in this chapter?"
    assert body["conversation"]["turn_count"] == 1

    pconn = db.connect_progress(paths.progress_db_path())
    stored = conversations.turns(pconn, cid)
    assert len(stored) == 1
    assert stored[0].question == "Who is in this chapter?"


def test_reopening_replays_stored_turns_into_the_model_history(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, status="reading", chapter="1")
    opened = _new_conversation()
    cid = opened["conversation"]["id"]
    client.post(f"/api/chat/conversations/{cid}/messages", json={"question": "first question"})

    # Drop the live session, as a server restart or an eviction would.
    registry.drop_for_conversation(cid)

    resp = client.get(f"/api/chat/conversations/{cid}")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert [t["question"] for t in body["turns"]] == ["first question"]

    record = registry.get(body["session_id"])
    assert record is not None
    assert len(record.session.history) == 2  # the replayed pair
    assert record.session.history[0].content == "first question"


def test_reopening_after_reading_on_reports_the_move_and_receilings(tmp_path, monkeypatch):
    """Spoiler invariant: the new ceiling is the reader's real position, not the stored one."""
    _setup(tmp_path, monkeypatch, status="reading", chapter="1")
    cid = _new_conversation()["conversation"]["id"]
    client.post(f"/api/chat/conversations/{cid}/messages", json={"question": "first question"})

    pconn = db.connect_progress(paths.progress_db_path())
    started = conversations.get(pconn, cid).chapter_idx

    reopened = client.get(f"/api/chat/conversations/{cid}").json()
    assert reopened["started_at_chapter_idx"] == started
    assert reopened["chapter_idx"] >= started
    assert reopened["moved_on"] == (reopened["chapter_idx"] > started)
    assert reopened["turns"][0]["chapter_idx"] == started


def test_listing_groups_by_book_and_hides_deleted_books(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, status="reading", chapter="1")
    cid = _new_conversation()["conversation"]["id"]
    client.post(f"/api/chat/conversations/{cid}/messages", json={"question": "a question"})

    listing = client.get("/api/chat/conversations").json()
    assert len(listing["groups"]) == 1
    group = listing["groups"][0]
    assert group["book_id"] == "sample-book"
    assert group["book_title"] == "Sample Book"
    assert [c["id"] for c in group["conversations"]] == [cid]
    assert group["conversations"][0]["chapter_label"]

    assert client.delete("/api/books/sample-book").status_code == 204
    assert client.get("/api/chat/conversations").json()["groups"] == []


def test_undo_removes_the_turn_from_the_transcript_and_the_session(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, status="reading", chapter="1")
    cid = _new_conversation()["conversation"]["id"]
    client.post(f"/api/chat/conversations/{cid}/messages", json={"question": "a question"})

    record = registry.for_conversation(cid)
    assert record is not None and len(record.session.history) == 2

    assert client.post(f"/api/chat/conversations/{cid}/undo").status_code == 200
    assert len(record.session.history) == 0

    pconn = db.connect_progress(paths.progress_db_path())
    assert conversations.turns(pconn, cid) == []


def test_rename_and_delete(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, status="reading", chapter="1")
    cid = _new_conversation()["conversation"]["id"]

    renamed = client.patch(f"/api/chat/conversations/{cid}", json={"title": "  Kell  and  Ansa "})
    assert renamed.status_code == 200
    assert renamed.json()["title"] == "Kell and Ansa"

    assert client.delete(f"/api/chat/conversations/{cid}").status_code == 204
    assert client.get(f"/api/chat/conversations/{cid}").status_code == 404
    assert registry.for_conversation(cid) is None


def test_unknown_conversation_is_404(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, status="reading", chapter="1")
    assert client.get("/api/chat/conversations/nope").status_code == 404
    assert (
        client.post("/api/chat/conversations/nope/messages", json={"question": "x"}).status_code
        == 404
    )
