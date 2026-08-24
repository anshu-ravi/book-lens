"""Tests for citation marks: the positions the reading bar plots citations at.

The invariant here is that a mark is only ever returned for a paragraph the
session can already read -- an id above the ceiling resolves to nothing at all,
rather than to a position that would reveal where in the book it sits.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from booklens.web.app import app
from tests.test_web import _setup

app.state.llm_provider = "fake"

client = TestClient(app)


def _session(book_id: str = "sample-book") -> str:
    resp = client.post("/api/chat/sessions", json={"book_id": book_id})
    assert resp.status_code == 200, resp.text
    return resp.json()["session_id"]


def test_a_readable_citation_gets_a_fraction_and_a_chapter(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, status="reading", chapter="1")
    sid = _session()

    resp = client.post(
        f"/api/chat/sessions/{sid}/citation-marks",
        json={"citation_ids": ["sample-book:0:p0"]},
    )
    assert resp.status_code == 200, resp.text
    marks = resp.json()["marks"]
    assert len(marks) == 1
    assert marks[0]["id"] == "sample-book:0:p0"
    assert marks[0]["book_id"] == "sample-book"
    assert marks[0]["chapter_label"]
    assert 0.0 <= marks[0]["fraction"] <= 1.0


def test_an_unreadable_or_malformed_id_yields_no_mark(tmp_path, monkeypatch):
    """Spoiler invariant: nothing above the ceiling gets plotted, not even a position."""
    _setup(tmp_path, monkeypatch, status="reading", chapter="1")
    sid = _session()

    resp = client.post(
        f"/api/chat/sessions/{sid}/citation-marks",
        json={"citation_ids": ["sample-book:99:p9999", "not-a-citation", "other-book:0:p0"]},
    )
    assert resp.status_code == 200
    assert resp.json()["marks"] == []


def test_unknown_session_is_404(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, status="reading", chapter="1")
    resp = client.post(
        "/api/chat/sessions/nope/citation-marks", json={"citation_ids": ["sample-book:0:p0"]}
    )
    assert resp.status_code == 404
