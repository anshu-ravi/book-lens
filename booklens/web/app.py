"""The FastAPI app: HTTP surface over the same bounded `Tools` layer the CLI uses.

Every route that reads book text goes through `tools.Tools` or `booklens.chat`; the
only raw SQL here reads structural book/series metadata, never `para` or `chapter` text.
"""

from __future__ import annotations

import hashlib
import mimetypes
import os
import shutil
import sqlite3
from dataclasses import asdict
from pathlib import Path
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from booklens import chat, classify, context, db, goodreads, ingest, paths, progress, reseq, tools
from booklens.extract import extract_book, extract_cover, read_series_hint
from booklens.ingest import _slugify as _slugify_name
from booklens.llm.base import FatalLLMError, TransientLLMError
from booklens.web import sessions

app = FastAPI(title="booklens")
app.state.llm_provider = "openrouter"

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _get_dbs():
    """Per-request index/progress connections, closed when the request ends.

    `check_same_thread=False`: FastAPI may run this dependency and the route
    handler on different threadpool threads for the same request.
    """
    iconn = db.connect_index(check_same_thread=False)
    pconn = db.connect_progress(check_same_thread=False)
    try:
        yield iconn, pconn
    finally:
        iconn.close()
        pconn.close()


DbDep = Annotated[tuple[sqlite3.Connection, sqlite3.Connection], Depends(_get_dbs)]


def _get_goodreads_db():
    """Per-request connection to the Goodreads cache -- its own database, never `index.db`."""
    conn = goodreads.connect()
    try:
        yield conn
    finally:
        conn.close()


GoodreadsDbDep = Annotated[sqlite3.Connection, Depends(_get_goodreads_db)]


# -- request/response models -------------------------------------------------


class ProgressUpdate(BaseModel):
    """Body of `PUT /api/books/{book_id}/progress`."""

    status: Literal["unread", "reading", "finished"]
    chapter: str | None = None


class BookEdit(BaseModel):
    """Body of `PUT /api/books/{book_id}`."""

    title: str
    author: str | None = None
    series_id: str
    book_order: int
    standalone: bool


class UploadCommitRequest(BaseModel):
    """Body of `POST /api/upload/commit`."""

    sha256: str
    title: str | None = None
    author: str | None = None
    series_id: str
    book_order: int
    standalone: bool


class CreateSessionRequest(BaseModel):
    """Body of `POST /api/chat/sessions`."""

    book_id: str


class AskRequest(BaseModel):
    """Body of `POST /api/chat/sessions/{sid}/messages`."""

    question: str


class GoodreadsSyncRequest(BaseModel):
    """Body of `POST /api/goodreads/sync`."""

    user_id: str | None = None
    dnf_shelf: str | None = None


class GoodreadsSettingsUpdate(BaseModel):
    """Body of `PUT /api/goodreads/settings`."""

    user_id: str
    dnf_shelf: str | None = None


# -- shared helpers -----------------------------------------------------------


def _book_payload(iconn: sqlite3.Connection, pconn: sqlite3.Connection, book_id: str) -> dict:
    """The `Book` shape shared by `/api/library` and the progress-update response."""
    row = iconn.execute(
        "SELECT id, title, author, book_order, standalone FROM book WHERE id = ?",
        (book_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"unknown book_id {book_id!r}")

    with tools.Tools(iconn, pconn) as t:
        chapters = t.list_chapters(book_id)["chapters"]
        chapters_read = t.count_chapters_read(book_id)
    chapter_count = tools.count_addressable_chapters(iconn, book_id)
    prog = progress.get_progress(pconn, book_id)
    percent = round(100 * chapters_read / chapter_count) if chapter_count else 0

    return {
        "id": row["id"],
        "title": row["title"],
        "author": row["author"],
        "book_order": row["book_order"],
        "status": prog.status,
        "position_chapter_idx": prog.position_chapter_idx,
        "position_ref": (
            tools.chapter_ref_for(iconn, book_id, prog.position_chapter_idx)
            if prog.position_chapter_idx is not None
            else None
        ),
        "position_label": chapters[-1]["label"] if chapters else None,
        "chapter_count": chapter_count,
        "chapters_read": chapters_read,
        "percent": percent,
        "has_cover": paths.cover_path(book_id) is not None,
        "standalone": bool(row["standalone"]),
    }


def _check_slot_free(
    iconn: sqlite3.Connection, series_id: str, book_order: int, exclude_book_id: str | None = None
) -> None:
    """Raise 409 if another book already occupies (series_id, book_order)."""
    query = "SELECT id FROM book WHERE series_id = ? AND book_order = ?"
    params: list = [series_id, book_order]
    if exclude_book_id is not None:
        query += " AND id != ?"
        params.append(exclude_book_id)
    occupant = iconn.execute(query, params).fetchone()
    if occupant is not None:
        raise HTTPException(
            status_code=409,
            detail=f"series {series_id!r} already has a book at position {book_order}",
        )


def _humanize_series_id(series_id: str) -> str:
    """Turn a series slug into a display name, mirroring the frontend's `seriesName`."""
    return " ".join(word.capitalize() for word in series_id.replace("_", "-").split("-") if word)


def _suggest_series(iconn: sqlite3.Connection, book) -> dict:
    """The series-suggestion ladder: EPUB3 collection, then Calibre series, then shared authorship."""
    rows = iconn.execute("SELECT series_id, book_order, author, standalone FROM book").fetchall()
    stats: dict[str, dict] = {}
    for r in rows:
        s = stats.setdefault(
            r["series_id"], {"count": 0, "max_order": 0, "authors": set(), "standalone": 0}
        )
        s["count"] += 1
        s["max_order"] = max(s["max_order"], r["book_order"])
        s["standalone"] += int(bool(r["standalone"]))
        if r["author"]:
            s["authors"].add(r["author"])

    hint = read_series_hint(book.source_path)
    if hint is not None:
        sid = _slugify_name(hint.name)
        existing = stats.get(sid)
        prior_volumes = existing["count"] if existing else 0
        if hint.position is not None:
            order = hint.position
        elif existing is not None:
            order = existing["max_order"] + 1
        else:
            order = 1
        return {
            "suggested_series_id": sid,
            "suggested_series_name": hint.name,
            "prior_volumes": prior_volumes,
            "suggested_book_order": order,
        }

    if book.author:
        candidates = [
            (sid, s)
            for sid, s in stats.items()
            if book.author in s["authors"] and not (s["count"] == 1 and s["standalone"] == 1)
        ]
        if candidates:
            sid, s = max(candidates, key=lambda kv: kv[1]["count"])
            return {
                "suggested_series_id": sid,
                "suggested_series_name": _humanize_series_id(sid),
                "prior_volumes": s["count"],
                "suggested_book_order": s["max_order"] + 1,
            }

    return {
        "suggested_series_id": None,
        "suggested_series_name": None,
        "prior_volumes": 0,
        "suggested_book_order": 1,
    }


# -- library / progress --------------------------------------------------------


@app.get("/api/library")
def get_library(dbs: DbDep):
    """Every series and book, with the reader's standing in each."""
    iconn, pconn = dbs
    rows = iconn.execute(
        "SELECT id, series_id FROM book ORDER BY series_id, book_order"
    ).fetchall()

    series_map: dict[str, list[dict]] = {}
    for row in rows:
        series_map.setdefault(row["series_id"], []).append(_book_payload(iconn, pconn, row["id"]))

    series = [
        {
            "id": sid,
            "books": books,
            # Computed here, once: a series is standalone only when it has a
            # single book and that book carries the flag. Never derived client-side.
            "standalone": len(books) == 1 and books[0]["standalone"],
        }
        for sid, books in sorted(series_map.items())
    ]
    return {"series": series}


@app.get("/api/books/{book_id}/positions")
def get_book_positions(book_id: str, dbs: DbDep):
    """The reading-position picker: structure for the whole book, titles once reached."""
    iconn, pconn = dbs
    row = iconn.execute("SELECT 1 FROM book WHERE id = ?", (book_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"unknown book_id {book_id!r}")
    with tools.Tools(iconn, pconn) as t:
        return t.list_chapter_positions(book_id)


@app.put("/api/books/{book_id}/progress")
def put_book_progress(book_id: str, body: ProgressUpdate, dbs: DbDep):
    """Move the reader's position, resolving `chapter` the way the reader names it."""
    iconn, pconn = dbs
    chapter_idx = None
    if body.chapter is not None:
        try:
            chapter_idx = tools.resolve_chapter_ref(iconn, book_id, body.chapter)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        progress.set_position(pconn, iconn, book_id, status=body.status, chapter_idx=chapter_idx)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _book_payload(iconn, pconn, book_id)


@app.put("/api/books/{book_id}")
def put_book(book_id: str, body: BookEdit, dbs: DbDep):
    """Edit a book's title, author, standalone flag, and series placement.

    A move to a new (series_id, book_order) is a metadata and seq-shift
    operation only -- it never reads the EPUB. `global_seq` packs
    `book_order` into its high digits, so a change of position is a constant
    arithmetic shift of every seq the book owns (`reseq.rebase_book_order`);
    a change of `series_id` alone doesn't touch seq at all.
    """
    iconn, pconn = dbs
    row = iconn.execute(
        "SELECT series_id, book_order FROM book WHERE id = ?", (book_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"unknown book_id {book_id!r}")

    title = body.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="title must not be empty")
    author = body.author.strip() if body.author and body.author.strip() else None

    iconn.execute(
        "UPDATE book SET title = ?, author = ?, standalone = ? WHERE id = ?",
        (title, author, int(body.standalone), book_id),
    )
    iconn.commit()

    if row["series_id"] != body.series_id or row["book_order"] != body.book_order:
        _check_slot_free(iconn, body.series_id, body.book_order, exclude_book_id=book_id)
        reseq.rebase_book_order(iconn, pconn, book_id, body.book_order, series_id=body.series_id)

    return _book_payload(iconn, pconn, book_id)


@app.delete("/api/books/{book_id}", status_code=204)
def delete_book(book_id: str, dbs: DbDep):
    """Remove a book entirely: live sessions, index rows (cascading), progress row, and its data directory.

    Sessions are dropped first, before their `index.db` connections are
    orphaned by the row disappearing underneath them. The data directory --
    including the library's own adopted copy of the EPUB -- is only ever
    removed after being confirmed to sit inside `paths.data_dir()`; the
    user's own original file, wherever it lives, is never touched.
    """
    iconn, pconn = dbs
    row = iconn.execute("SELECT 1 FROM book WHERE id = ?", (book_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"unknown book_id {book_id!r}")

    sessions.registry.drop_for_book(book_id)

    iconn.execute("DELETE FROM book WHERE id = ?", (book_id,))
    iconn.commit()

    pconn.execute("DELETE FROM book_progress WHERE book_id = ?", (book_id,))
    pconn.commit()

    book_dir = paths.book_dir(book_id).resolve()
    data_root = paths.data_dir().resolve()
    if book_dir == data_root or data_root not in book_dir.parents:
        raise HTTPException(
            status_code=500,
            detail=f"refusing to delete book_dir outside data_dir: {book_dir}",
        )
    shutil.rmtree(book_dir, ignore_errors=True)

    return Response(status_code=204)


@app.get("/api/books/{book_id}/cover")
def get_book_cover(book_id: str, dbs: DbDep):
    """The book's real EPUB cover art, content-addressed by hash so it's safe to cache long."""
    iconn, _pconn = dbs
    row = iconn.execute("SELECT 1 FROM book WHERE id = ?", (book_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"unknown book_id {book_id!r}")
    cover_file = paths.cover_path(book_id)
    if cover_file is None:
        raise HTTPException(status_code=404, detail=f"no cover for book_id {book_id!r}")
    media_type = mimetypes.guess_type(str(cover_file))[0] or "application/octet-stream"
    return FileResponse(
        cover_file, media_type=media_type, headers={"Cache-Control": "public, max-age=86400"}
    )


# -- series / upload ------------------------------------------------------------


@app.get("/api/series")
def get_series(dbs: DbDep):
    """Existing series names and each one's next `book_order`, to seed the upload form.

    Standalone shelves are omitted -- they are one book's own container, never
    something a second volume joins.
    """
    iconn, _pconn = dbs
    rows = iconn.execute("SELECT series_id, book_order, standalone FROM book").fetchall()

    agg: dict[str, dict] = {}
    for r in rows:
        entry = agg.setdefault(r["series_id"], {"book_count": 0, "max_order": 0, "standalone": 0})
        entry["book_count"] += 1
        entry["max_order"] = max(entry["max_order"], r["book_order"])
        entry["standalone"] += int(bool(r["standalone"]))

    series = [
        {"id": sid, "book_count": v["book_count"], "next_order": v["max_order"] + 1}
        for sid, v in sorted(agg.items())
        if not (v["book_count"] == 1 and v["standalone"] == 1)
    ]
    return {"series": series}


@app.post("/api/upload/inspect")
async def inspect_upload(dbs: DbDep, file: UploadFile = File(...)):
    """Parse an EPUB into a catalog entry, writing nothing to `index.db`.

    The bytes are stashed under `data/uploads/`, content-addressed by hash,
    so `/api/upload/commit` doesn't need the file re-sent.
    """
    iconn, _pconn = dbs
    data = await file.read()
    sha256 = hashlib.sha256(data).hexdigest()

    stash_path = paths.upload_stash_path(sha256)
    stash_path.write_bytes(data)
    paths.upload_name_path(sha256).write_text(file.filename or "")
    paths.prune_stale_uploads()

    try:
        book = extract_book(stash_path)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"could not read this EPUB: {exc}") from exc

    kinds = classify.classify_chapters(book)
    body_chapters = [ch for ch in book.chapters if kinds[ch.chapter_idx] == "body"]
    has_prologue = any(ch.label.strip().lower().startswith("prologue") for ch in body_chapters)

    try:
        has_cover = extract_cover(stash_path) is not None
    except Exception:
        has_cover = False

    existing = iconn.execute("SELECT id FROM book WHERE sha256 = ?", (sha256,)).fetchone()

    return {
        "sha256": sha256,
        "filename": file.filename,
        "size_bytes": len(data),
        "title": book.title,
        "author": book.author,
        "chapters_detected": len(body_chapters),
        "has_prologue": has_prologue,
        "has_cover": has_cover,
        **_suggest_series(iconn, book),
        "already_ingested": existing is not None,
        "existing_book_id": existing["id"] if existing else None,
    }


@app.get("/api/upload/inspect/{sha256}/cover")
def get_inspect_cover(sha256: str):
    """The cover plate for a stashed, not-yet-committed upload."""
    stash_path = paths.upload_stash_path(sha256)
    if not stash_path.is_file():
        raise HTTPException(status_code=404, detail=f"no stashed upload for sha256 {sha256!r}")
    try:
        cover = extract_cover(stash_path)
    except Exception:
        cover = None
    if cover is None:
        raise HTTPException(status_code=404, detail="this EPUB has no cover image")
    media_type = cover.media_type or mimetypes.guess_type(cover.zip_path)[0] or "application/octet-stream"
    return Response(content=cover.data, media_type=media_type)


@app.post("/api/upload/commit")
def commit_upload(body: UploadCommitRequest, dbs: DbDep):
    """Ingest a previously inspected, stashed EPUB. Never writes into the user's Books directory."""
    iconn, _pconn = dbs
    stash_path = paths.upload_stash_path(body.sha256)
    if not stash_path.is_file():
        raise HTTPException(
            status_code=404,
            detail="this upload has expired or was never inspected -- please re-drop the file",
        )

    existing = iconn.execute("SELECT id FROM book WHERE sha256 = ?", (body.sha256,)).fetchone()
    _check_slot_free(
        iconn, body.series_id, body.book_order, exclude_book_id=existing["id"] if existing else None
    )

    try:
        result = ingest.ingest_book(
            stash_path,
            series_id=body.series_id,
            book_order=body.book_order,
            iconn=iconn,
            force=False,
            standalone=body.standalone,
            title=body.title,
            author=body.author,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"could not shelve this EPUB: {exc}") from exc

    name_path = paths.upload_name_path(body.sha256)
    if not result.skipped:
        # `ingest_book` already adopted a copy of the stash under its own
        # (hash) name; rename it to the name the user actually uploaded.
        original_name = name_path.read_text().strip() if name_path.is_file() else ""
        ingest.adopt_source(iconn, result.book_id, move=True, filename=original_name)
    # The stash's own bytes are now redundant either way -- the book row (on
    # skip) or the adopted copy (on a real ingest) is what's kept.
    stash_path.unlink(missing_ok=True)
    name_path.unlink(missing_ok=True)

    author_row = iconn.execute("SELECT author FROM book WHERE id = ?", (result.book_id,)).fetchone()
    manifest = paths.manifest_for(result.book_id)

    return {
        "book_id": result.book_id,
        "title": result.title,
        "author": author_row["author"] if author_row else None,
        "book_order": result.book_order,
        "series_id": body.series_id,
        "chapters": result.chapters,
        "paragraphs": result.paragraphs,
        "skipped": result.skipped,
        "excerpt_chapters": manifest.get("excerpt_chapters", []),
        "standalone": body.standalone,
    }


# -- chat -----------------------------------------------------------------------


@app.post("/api/chat/sessions")
def create_chat_session(body: CreateSessionRequest, dbs: DbDep):
    """Start a session ceilinged at the reader's real, persisted position -- never a client-supplied one."""
    iconn, pconn = dbs
    prog = progress.get_progress(pconn, body.book_id)
    chapter_idx = prog.position_chapter_idx
    # A book marked finished before positions were recorded for 'finished' has no
    # stored position; the last chapter is what finished has always meant.
    if chapter_idx is None and prog.status == "finished":
        chapter_idx = progress.last_addressable_chapter_idx(iconn, body.book_id)
    if chapter_idx is None or prog.status == "unread":
        raise HTTPException(status_code=409, detail=f"no reading position set for {body.book_id}")

    session_iconn = db.connect_index(check_same_thread=False)
    session_pconn = chat.ephemeral_ceiling_conn(
        session_iconn, body.book_id, chapter_idx, check_same_thread=False
    )
    try:
        with tools.Tools(session_iconn, session_pconn) as t:
            assembled = context.assemble(t)
            chapters = t.list_chapters(body.book_id)["chapters"]
            book = next((b for b in t.list_books() if b["id"] == body.book_id), None)

        series_id, target_order = progress.series_and_order(session_iconn, body.book_id)
        prior_titles = [
            row["title"]
            for row in session_iconn.execute(
                "SELECT title FROM book WHERE series_id = ? AND book_order < ? ORDER BY book_order",
                (series_id, target_order),
            )
        ]
    except context.ContextOverflowError as exc:
        session_iconn.close()
        session_pconn.close()
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    except Exception:
        session_iconn.close()
        session_pconn.close()
        raise

    llm = chat.build_llm(app.state.llm_provider)
    session = chat.ChatSession(llm, assembled)
    sid = sessions.registry.create(body.book_id, session, session_iconn, session_pconn)

    return {
        "session_id": sid,
        "book_id": body.book_id,
        "book_title": book["title"] if book else body.book_id,
        "prior_titles": prior_titles,
        "chapter_label": chapters[-1]["label"] if chapters else "",
        "para_count": assembled.para_count,
        "token_estimate": assembled.token_estimate,
    }


def _get_session(sid: str) -> sessions.SessionRecord:
    """Look up a chat session or raise the 404 every session route shares."""
    record = sessions.registry.get(sid)
    if record is None:
        raise HTTPException(status_code=404, detail=f"unknown session {sid!r}")
    return record


@app.post("/api/chat/sessions/{sid}/messages")
def post_chat_message(sid: str, body: AskRequest):
    """Ask a question in an existing session."""
    record = _get_session(sid)
    try:
        result = record.session.ask(body.question)
    except TransientLLMError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except FatalLLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    r = result.response
    return {
        "answer": result.text,
        "citations": result.citation_ids,
        "debug": {
            "context_tokens": record.session.assembled.token_estimate,
            "prompt_tokens": r.input_tokens,
            "cached_tokens": r.cached_tokens,
            "cache_write_tokens": r.cache_write_tokens,
            "turn_cost_usd": r.cost_usd,
            "session_cost_usd": result.session_cost_usd,
        },
    }


@app.post("/api/chat/sessions/{sid}/undo")
def undo_chat_message(sid: str):
    """Pop the last (user, assistant) pair -- how the UI cancels an in-flight question."""
    record = _get_session(sid)
    history = record.session.history
    if len(history) >= 2:
        del history[-2:]
    return {"ok": True, "turns": len(history) // 2}


@app.get("/api/chat/sessions/{sid}/citations/{citation_id}")
def get_chat_citation(sid: str, citation_id: str, window: int = 3):
    """Expand a citation, bounded by the session's own ceiling."""
    record = _get_session(sid)
    with tools.Tools(record.iconn, record.session_pconn) as t:
        try:
            return t.context(citation_id, window=window)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.delete("/api/chat/sessions/{sid}", status_code=204)
def delete_chat_session(sid: str):
    """Close and drop a session."""
    sessions.registry.drop(sid)
    return Response(status_code=204)


# -- goodreads ------------------------------------------------------------------

# Fixed lead-in order for `/api/goodreads/shelves`; anything else present in
# the cache follows, alphabetically. Never hardcode a DNF shelf name here --
# it's a user-chosen custom shelf, not one of Goodreads' exclusive three.
_SHELF_ORDER_PREFIX = ("currently-reading", "read", "to-read")


def _goodreads_book_payload(book: goodreads.GoodreadsBook) -> dict:
    """The `GoodreadsBook` dataclass in snake_case, plus a derived `goodreads_url`."""
    payload = asdict(book)
    payload["custom_shelves"] = list(book.custom_shelves)
    payload["goodreads_url"] = f"https://www.goodreads.com/book/show/{book.book_id}"
    return payload


@app.get("/api/goodreads/shelves")
def get_goodreads_shelves(conn: GoodreadsDbDep):
    """Per-shelf counts from the cache, plus each shelf's most recent truncation flag."""
    count_rows = conn.execute(
        "SELECT shelf, COUNT(*) AS count FROM goodreads_book GROUP BY shelf"
    ).fetchall()
    counts = {r["shelf"]: r["count"] for r in count_rows}

    latest_sync_rows = conn.execute(
        """
        SELECT s.shelf, s.truncated
        FROM goodreads_sync s
        JOIN (SELECT shelf, MAX(id) AS max_id FROM goodreads_sync GROUP BY shelf) latest
          ON s.id = latest.max_id
        """
    ).fetchall()
    truncated_by_shelf = {r["shelf"]: bool(r["truncated"]) for r in latest_sync_rows}

    synced_at = conn.execute("SELECT MAX(synced_at) AS m FROM goodreads_sync").fetchone()["m"]

    others = sorted(s for s in counts if s not in _SHELF_ORDER_PREFIX)
    order = [s for s in _SHELF_ORDER_PREFIX if s in counts] + others

    shelves = [
        {"shelf": s, "count": counts[s], "truncated": truncated_by_shelf.get(s, False)}
        for s in order
    ]
    return {"shelves": shelves, "total": sum(counts.values()), "synced_at": synced_at}


@app.get("/api/goodreads/books")
def get_goodreads_books(conn: GoodreadsDbDep, shelf: str = "all"):
    """Cached books on one shelf, or every cached book when `shelf` is `all` or omitted."""
    books = goodreads.all_books(conn) if shelf == "all" else goodreads.books_on_shelf(conn, shelf)
    books = sorted(books, key=lambda b: b.title)
    return {"books": [_goodreads_book_payload(b) for b in books]}


def _goodreads_settings_payload(conn: sqlite3.Connection) -> dict:
    """The effective `user_id`/`dnf_shelf` and where the id came from.

    Resolution order for `user_id`: stored setting, then `GOODREADS_USER_ID`.
    """
    stored_user_id = goodreads.get_setting(conn, "user_id")
    dnf_shelf = goodreads.get_setting(conn, "dnf_shelf")
    if stored_user_id:
        return {"user_id": stored_user_id, "dnf_shelf": dnf_shelf, "source": "stored"}
    env_user_id = os.environ.get("GOODREADS_USER_ID")
    if env_user_id:
        return {"user_id": env_user_id, "dnf_shelf": dnf_shelf, "source": "env"}
    return {"user_id": None, "dnf_shelf": dnf_shelf, "source": "none"}


@app.get("/api/goodreads/settings")
def get_goodreads_settings(conn: GoodreadsDbDep):
    """The effective Goodreads user id and DNF shelf, and where the id came from."""
    return _goodreads_settings_payload(conn)


@app.put("/api/goodreads/settings")
def put_goodreads_settings(body: GoodreadsSettingsUpdate, conn: GoodreadsDbDep):
    """Persist a Goodreads user id (accepting a bare id or a profile URL) and DNF shelf."""
    try:
        user_id = goodreads.normalize_user_id(body.user_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    goodreads.set_setting(conn, "user_id", user_id)
    goodreads.set_setting(conn, "dnf_shelf", body.dnf_shelf)
    return _goodreads_settings_payload(conn)


@app.post("/api/goodreads/sync")
def post_goodreads_sync(body: GoodreadsSyncRequest, conn: GoodreadsDbDep):
    """Fetch the reader's Goodreads shelves live and refresh the cache.

    `user_id` resolution order: the request body, then the stored setting,
    then `GOODREADS_USER_ID`. `dnf_shelf` falls back to the stored setting
    only when the body omits it entirely.
    """
    stored = _goodreads_settings_payload(conn)
    user_id = body.user_id or stored["user_id"]
    if not user_id:
        raise HTTPException(
            status_code=400,
            detail="no Goodreads user id: pass user_id, save it in settings, or set GOODREADS_USER_ID",
        )
    dnf_shelf = body.dnf_shelf if body.dnf_shelf is not None else stored["dnf_shelf"]
    try:
        report = goodreads.sync(conn, user_id, dnf_shelf=dnf_shelf)
    except goodreads.GoodreadsError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return {
        "shelf_counts": report.shelf_counts,
        "truncated_shelves": list(report.truncated_shelves),
        "total_books": report.total_books,
    }


# -- misc -------------------------------------------------------------------


@app.get("/api/credits")
def get_credits():
    """Remaining OpenRouter balance for the configured key."""
    from booklens.llm.openrouter import get_credits as _get_credits

    try:
        return asdict(_get_credits())
    except (FatalLLMError, TransientLLMError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


# -- static frontend (production build only; Vite dev server otherwise) --------

_FRONTEND_BUILD = Path(__file__).resolve().parent.parent.parent / "web" / "frontend" / "build"
if (_FRONTEND_BUILD / "index.html").is_file():
    app.mount("/_app", StaticFiles(directory=str(_FRONTEND_BUILD / "_app")), name="frontend-assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        """Serve a built asset if one exists, else index.html -- client-side routing owns the rest."""
        candidate = (_FRONTEND_BUILD / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(_FRONTEND_BUILD):
            return FileResponse(candidate)
        return FileResponse(_FRONTEND_BUILD / "index.html")
