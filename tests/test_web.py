"""Tests for booklens.web.app: the HTTP surface over the bounded tool layer.

Two tests are spoiler invariants, called out explicitly: the position picker
must never leak a title above the ceiling, and citation expansion must never
reach past a session's own ceiling.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

from booklens import cli, db, progress, tools
from booklens.web.app import app
from booklens.web.sessions import registry
from tests.test_ingest import CONTAINER_XML, _simple_epub

# Every chat-session test needs the fake provider so nothing here can spend money.
app.state.llm_provider = "fake"

client = TestClient(app)


def _epub_with_metadata(
    tmp_path: Path, name: str, title: str, author: str, extra_metadata_xml: str
) -> Path:
    """A minimal one-chapter EPUB with extra `<meta>` tags injected into the OPF,
    for exercising the series-suggestion ladder against real collection metadata."""
    path = tmp_path / name
    opf = f"""<?xml version="1.0"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>{title}</dc:title>
    <dc:creator>{author}</dc:creator>
    {extra_metadata_xml}
  </metadata>
  <manifest>
    <item id="ch0" href="text/ch0.xhtml" media-type="application/xhtml+xml"/>
    <item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>
  </manifest>
  <spine toc="ncx">
    <itemref idref="ch0"/>
  </spine>
</package>"""
    ncx = """<?xml version="1.0"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">
  <navMap>
    <navPoint id="np0"><navLabel><text>Chapter 1</text></navLabel><content src="text/ch0.xhtml"/></navPoint>
  </navMap>
</ncx>"""
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("META-INF/container.xml", CONTAINER_XML)
        zf.writestr("OEBPS/content.opf", opf)
        zf.writestr("OEBPS/toc.ncx", ncx)
        zf.writestr("OEBPS/text/ch0.xhtml", "<html><body><p>Once upon a time.</p></body></html>")
    return path


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


def test_series_omits_standalone_shelves(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, status=None)

    resp = client.put(
        "/api/books/sample-book/shelf",
        json={"series_id": "s1", "book_order": 1, "standalone": True},
    )
    assert resp.status_code == 200

    assert client.get("/api/series").json()["series"] == []


def _inspect(tmp_path, monkeypatch, epub_path: Path, filename: str | None = None):
    monkeypatch.setenv("BOOKLENS_DATA_DIR", str(tmp_path / "data"))
    db.connect_index().close()  # establish the data dir before inspecting
    with open(epub_path, "rb") as f:
        return client.post(
            "/api/upload/inspect",
            files={"file": (filename or epub_path.name, f, "application/epub+zip")},
        )


def test_inspect_parses_metadata_and_writes_nothing_to_index(tmp_path, monkeypatch):
    epub_path = _simple_epub(tmp_path, name="uploaded.epub")
    resp = _inspect(tmp_path, monkeypatch, epub_path)
    assert resp.status_code == 200
    body = resp.json()

    assert body["title"] == "Sample Book"
    assert body["chapters_detected"] == 3  # Prologue, Chapter 1, Chapter 2 -- all body
    assert body["has_prologue"] is True
    assert "word_count" not in body
    assert body["already_ingested"] is False
    assert body["existing_book_id"] is None

    iconn = db.connect_index()
    assert iconn.execute("SELECT COUNT(*) c FROM book").fetchone()["c"] == 0


def test_inspect_reports_already_ingested(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, status=None)
    epub_path = Path(
        db.connect_index().execute("SELECT source_path FROM book WHERE id = 'sample-book'").fetchone()[
            "source_path"
        ]
    )

    resp = _inspect(tmp_path, monkeypatch, epub_path, filename="reupload.epub")
    assert resp.status_code == 200
    body = resp.json()
    assert body["already_ingested"] is True
    assert body["existing_book_id"] == "sample-book"


def _commit(tmp_path, monkeypatch, epub_path: Path, **overrides):
    resp = _inspect(tmp_path, monkeypatch, epub_path)
    assert resp.status_code == 200
    sha256 = resp.json()["sha256"]
    body = {"sha256": sha256, "series_id": "s1", "book_order": 1, "standalone": False, **overrides}
    return client.post("/api/upload/commit", json=body), sha256


def test_commit_with_title_author_override_stores_overrides(tmp_path, monkeypatch):
    epub_path = _simple_epub(tmp_path, name="uploaded.epub")
    resp, _sha = _commit(
        tmp_path, monkeypatch, epub_path, title="Renamed Title", author="Renamed Author;"
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["title"] == "Renamed Title"
    assert body["author"] == "Renamed Author;"

    iconn = db.connect_index()
    row = iconn.execute("SELECT title, author FROM book WHERE id = ?", (body["book_id"],)).fetchone()
    assert row["title"] == "Renamed Title"
    assert row["author"] == "Renamed Author;"


def test_commit_unknown_sha_returns_404(tmp_path, monkeypatch):
    monkeypatch.setenv("BOOKLENS_DATA_DIR", str(tmp_path / "data"))
    db.connect_index().close()
    resp = client.post(
        "/api/upload/commit",
        json={"sha256": "0" * 64, "series_id": "s1", "book_order": 1, "standalone": False},
    )
    assert resp.status_code == 404


def test_commit_into_occupied_slot_returns_409(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, status=None)  # occupies s1/1 with sample-book

    epub2 = _simple_epub(tmp_path, name="second.epub", title="Second Book")
    resp, _sha = _commit(tmp_path, monkeypatch, epub2, series_id="s1", book_order=1)
    assert resp.status_code == 409

    iconn = db.connect_index()
    assert iconn.execute("SELECT COUNT(*) c FROM book").fetchone()["c"] == 1


# -- series-suggestion ladder ---------------------------------------------------


def test_suggest_series_epub3_collection_gives_order_and_name(tmp_path, monkeypatch):
    epub = _epub_with_metadata(
        tmp_path,
        "collection.epub",
        "Hollow Coast",
        "A. Hilcaster",
        extra_metadata_xml=(
            '<meta property="belongs-to-collection" id="c1">The Mistwarden Cycle</meta>'
            '<meta refines="#c1" property="collection-type">series</meta>'
            '<meta refines="#c1" property="group-position">3</meta>'
        ),
    )
    resp = _inspect(tmp_path, monkeypatch, epub)
    assert resp.status_code == 200
    body = resp.json()
    assert body["suggested_series_name"] == "The Mistwarden Cycle"
    assert body["suggested_series_id"] == "the-mistwarden-cycle"
    assert body["suggested_book_order"] == 3
    assert body["prior_volumes"] == 0


def test_suggest_series_calibre_meta_gives_order_and_name(tmp_path, monkeypatch):
    epub = _epub_with_metadata(
        tmp_path,
        "calibre.epub",
        "Hollow Coast",
        "A. Hilcaster",
        extra_metadata_xml=(
            '<meta name="calibre:series" content="The Mistwarden Cycle"/>'
            '<meta name="calibre:series_index" content="2"/>'
        ),
    )
    resp = _inspect(tmp_path, monkeypatch, epub)
    assert resp.status_code == 200
    body = resp.json()
    assert body["suggested_series_name"] == "The Mistwarden Cycle"
    assert body["suggested_book_order"] == 2


def test_suggest_series_matches_existing_series_by_shared_author(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, status=None)  # shelves sample-book (author "Test Author") into s1
    epub = _epub_with_metadata(
        tmp_path, "second.epub", "Another Volume", "Test Author", extra_metadata_xml=""
    )
    resp = _inspect(tmp_path, monkeypatch, epub)
    assert resp.status_code == 200
    body = resp.json()
    assert body["suggested_series_id"] == "s1"
    assert body["prior_volumes"] == 1
    assert body["suggested_book_order"] == 2


def test_suggest_series_no_match_returns_nulls(tmp_path, monkeypatch):
    epub = _epub_with_metadata(
        tmp_path, "lonely.epub", "Lonely Book", "Nobody Known", extra_metadata_xml=""
    )
    resp = _inspect(tmp_path, monkeypatch, epub)
    assert resp.status_code == 200
    body = resp.json()
    assert body["suggested_series_id"] is None
    assert body["suggested_series_name"] is None
    assert body["prior_volumes"] == 0
    assert body["suggested_book_order"] == 1


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
