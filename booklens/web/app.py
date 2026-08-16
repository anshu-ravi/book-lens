"""The FastAPI app: HTTP surface over the same bounded `Tools` layer the CLI uses.

Every route that reads book text goes through `tools.Tools` or `booklens.chat`; the
only raw SQL here reads structural book/series metadata, never `para` or `chapter` text.
"""

from __future__ import annotations

import mimetypes
import sqlite3
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from booklens import chat, context, db, ingest, paths, progress, tools
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


# -- request/response models -------------------------------------------------


class ProgressUpdate(BaseModel):
    """Body of `PUT /api/books/{book_id}/progress`."""

    status: Literal["unread", "reading", "finished"]
    chapter: str | None = None


class CreateSessionRequest(BaseModel):
    """Body of `POST /api/chat/sessions`."""

    book_id: str


class AskRequest(BaseModel):
    """Body of `POST /api/chat/sessions/{sid}/messages`."""

    question: str


# -- shared helpers -----------------------------------------------------------


def _book_payload(iconn: sqlite3.Connection, pconn: sqlite3.Connection, book_id: str) -> dict:
    """The `Book` shape shared by `/api/library` and the progress-update response."""
    row = iconn.execute(
        "SELECT id, title, author, book_order, sha256 FROM book WHERE id = ?", (book_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"unknown book_id {book_id!r}")

    with tools.Tools(iconn, pconn) as t:
        chapters = t.list_chapters(book_id)["chapters"]
    chapter_count = tools.count_addressable_chapters(iconn, book_id)
    chapters_read = len(chapters)
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
        "has_cover": paths.cover_path(row["sha256"]) is not None,
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

    series = [{"id": sid, "books": books} for sid, books in sorted(series_map.items())]
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


@app.get("/api/books/{book_id}/cover")
def get_book_cover(book_id: str, dbs: DbDep):
    """The book's real EPUB cover art, content-addressed by hash so it's safe to cache long."""
    iconn, _pconn = dbs
    row = iconn.execute("SELECT sha256 FROM book WHERE id = ?", (book_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"unknown book_id {book_id!r}")
    cover_file = paths.cover_path(row["sha256"])
    if cover_file is None:
        raise HTTPException(status_code=404, detail=f"no cover for book_id {book_id!r}")
    media_type = mimetypes.guess_type(str(cover_file))[0] or "application/octet-stream"
    return FileResponse(
        cover_file, media_type=media_type, headers={"Cache-Control": "public, max-age=86400"}
    )


# -- series / upload ------------------------------------------------------------


@app.get("/api/series")
def get_series(dbs: DbDep):
    """Existing series names and each one's next `book_order`, to seed the upload form."""
    iconn, _pconn = dbs
    rows = iconn.execute("SELECT series_id, book_order FROM book").fetchall()

    agg: dict[str, dict] = {}
    for r in rows:
        entry = agg.setdefault(r["series_id"], {"book_count": 0, "max_order": 0})
        entry["book_count"] += 1
        entry["max_order"] = max(entry["max_order"], r["book_order"])

    series = [
        {"id": sid, "book_count": v["book_count"], "next_order": v["max_order"] + 1}
        for sid, v in sorted(agg.items())
    ]
    return {"series": series}


@app.post("/api/upload")
async def upload_book(
    dbs: DbDep,
    file: UploadFile = File(...),
    series: str = Form(...),
    book_order: int | None = Form(None),
):
    """Ingest an uploaded EPUB into `series`, never writing into the user's Books directory."""
    iconn, _pconn = dbs
    if book_order is None:
        row = iconn.execute(
            "SELECT MAX(book_order) AS m FROM book WHERE series_id = ?", (series,)
        ).fetchone()
        book_order = (row["m"] or 0) + 1

    with tempfile.NamedTemporaryFile(suffix=".epub", delete=False) as tmp:
        tmp_path = Path(tmp.name)
        tmp.write(await file.read())

    try:
        try:
            result = ingest.ingest_book(
                tmp_path, series_id=series, book_order=book_order, iconn=iconn, force=False
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"could not shelve this EPUB: {exc}") from exc
    finally:
        tmp_path.unlink(missing_ok=True)

    author_row = iconn.execute("SELECT author FROM book WHERE id = ?", (result.book_id,)).fetchone()
    manifest = paths.manifest_for(result.sha256)

    return {
        "book_id": result.book_id,
        "title": result.title,
        "author": author_row["author"] if author_row else None,
        "book_order": result.book_order,
        "series_id": series,
        "chapters": result.chapters,
        "paragraphs": result.paragraphs,
        "skipped": result.skipped,
        "excerpt_chapters": manifest.get("excerpt_chapters", []),
    }


# -- chat -----------------------------------------------------------------------


@app.post("/api/chat/sessions")
def create_chat_session(body: CreateSessionRequest, dbs: DbDep):
    """Start a session ceilinged at the reader's real, persisted position -- never a client-supplied one."""
    _iconn, pconn = dbs
    prog = progress.get_progress(pconn, body.book_id)
    if prog.position_chapter_idx is None or prog.status == "unread":
        raise HTTPException(status_code=409, detail=f"no reading position set for {body.book_id}")

    session_iconn = db.connect_index(check_same_thread=False)
    session_pconn = chat.ephemeral_ceiling_conn(
        session_iconn, body.book_id, prog.position_chapter_idx, check_same_thread=False
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
