"""Command line entry point for ingesting and querying books.

Retrieval always goes through `Tools`, never ad-hoc SQL, so the CLI cannot
become a second unbounded path to the text.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

from dotenv import load_dotenv

from booklens import chat, context, db, ingest, passes, paths, progress, tools
from booklens.llm.base import (BudgetedLLM, BudgetExceeded, FatalLLMError,
                               get_provider)


def _print(result, as_json: bool) -> None:
    """Write a command result to stdout."""
    if as_json:
        print(json.dumps(result, indent=2, default=str))
        return
    print(_format(result))


def _format(result) -> str:
    """Render a result for human reading."""
    if isinstance(result, str):
        return result
    return json.dumps(result, indent=2, default=str)


def _open_dbs() -> tuple:
    """Open the index and progress databases together."""
    iconn = db.connect_index()
    pconn = db.connect_progress()
    return iconn, pconn


def _manifest_for(book_id: str) -> dict:
    """Load a book's ingest manifest, empty if it was never written."""
    return paths.manifest_for(book_id)


# -- subcommands --------------------------------------------------------


def cmd_ingest(args: argparse.Namespace) -> int:
    """Ingest EPUBs in order, reporting what was quarantined as excerpt."""
    iconn, _pconn = _open_dbs()
    order = args.start_order
    for epub_path in args.epubs:
        result = ingest.ingest_book(
            epub_path,
            series_id=args.series,
            book_order=order,
            iconn=iconn,
            force=args.force,
        )
        order += 1

        if args.json:
            print(json.dumps(result.__dict__, indent=2))
            continue

        status = "skipped (already ingested)" if result.skipped else "ingested"
        print(f"== {result.title} [{result.book_id}] -- {status} ==")
        print(f"  book_order={result.book_order} sequence_tier={result.sequence_tier} "
              f"label_tier={result.label_tier}")
        print(f"  documents={result.documents} chapters={result.chapters} "
              f"paragraphs={result.paragraphs}")
        manifest = _manifest_for(result.book_id)
        excerpt_chapters = manifest.get("excerpt_chapters", [])
        if excerpt_chapters:
            print(f"  QUARANTINED as excerpt ({result.excerpt_paragraphs} paragraphs, "
                  f"never served at any ceiling):")
            for entry in excerpt_chapters:
                print(f"    - {entry['label']!r}: {entry['paragraphs']} paragraphs")
        else:
            print("  no excerpt back matter detected")
        skipped_empty = manifest.get("skipped_empty_chapters", [])
        if skipped_empty:
            print(f"  chapters with zero extracted paragraphs (not stored): {skipped_empty}")
        size_flags = manifest.get("size_flags", [])
        if size_flags:
            print("  SIZE FLAG (short for its kind -- check for misclassification, nothing was dropped):")
            for entry in size_flags:
                print(f"    - {entry['label']!r} ({entry['kind']}): {entry['words']} words")
    return 0


def cmd_covers(args: argparse.Namespace) -> int:
    """Backfill covers for already-ingested books, without re-running ingest."""
    from booklens.ingest import _write_cover

    iconn, _pconn = _open_dbs()
    rows = iconn.execute("SELECT id, source_path FROM book ORDER BY series_id, book_order").fetchall()

    results = []
    for row in rows:
        book_id, source_path = row["id"], row["source_path"]
        book_dir = paths.book_dir(book_id)

        if paths.cover_path(book_id) is not None and not args.force:
            entry = {"book_id": book_id, "outcome": "skipped"}
            results.append(entry)
            if not args.json:
                print(f"{book_id}: skipped (already have one)")
            continue

        if not Path(source_path).is_file():
            entry = {"book_id": book_id, "outcome": "source_missing", "source_path": source_path}
            results.append(entry)
            if not args.json:
                print(f"{book_id}: source file no longer at {source_path}")
            continue

        tier = _write_cover(Path(source_path), book_dir)
        if tier is None:
            entry = {"book_id": book_id, "outcome": "no_cover"}
            results.append(entry)
            if not args.json:
                print(f"{book_id}: no cover found")
            continue

        cover_file = paths.cover_path(book_id)
        size_kb = cover_file.stat().st_size // 1024
        media_type = _extension_for_report(cover_file)
        entry = {
            "book_id": book_id, "outcome": "written", "tier": tier,
            "media_type": media_type, "size_kb": size_kb,
        }
        results.append(entry)
        if not args.json:
            print(f"{book_id}: cover written ({tier}, {media_type}, {size_kb} KB)")

    if args.json:
        print(json.dumps(results, indent=2))
    return 0


def cmd_adopt_sources(args: argparse.Namespace) -> int:
    """Backfill the app's own copy of every book's EPUB into its library directory."""
    iconn, _pconn = _open_dbs()
    rows = iconn.execute("SELECT id FROM book ORDER BY series_id, book_order").fetchall()

    results = []
    for row in rows:
        book_id = row["id"]
        before = iconn.execute(
            "SELECT source_path FROM book WHERE id = ?", (book_id,)
        ).fetchone()["source_path"]

        new_path = ingest.adopt_source(iconn, book_id)

        if new_path is None:
            entry = {"book_id": book_id, "outcome": "source_missing", "source_path": before}
            results.append(entry)
            if not args.json:
                print(f"{book_id}: source file no longer at {before}")
            continue

        if str(new_path) == before:
            entry = {"book_id": book_id, "outcome": "already_adopted", "source_path": before}
            results.append(entry)
            if not args.json:
                print(f"{book_id}: already in the library ({before})")
            continue

        entry = {"book_id": book_id, "outcome": "adopted", "source_path": str(new_path)}
        results.append(entry)
        if not args.json:
            print(f"{book_id}: adopted a copy at {new_path}")

    if args.json:
        print(json.dumps(results, indent=2))
    return 0


_COVER_EXT_MEDIA_TYPES = {
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
    ".gif": "image/gif", ".svg": "image/svg+xml", ".webp": "image/webp",
}


def _extension_for_report(cover_file: Path) -> str:
    """Best-effort media type for the human-readable `covers` report line."""
    return _COVER_EXT_MEDIA_TYPES.get(cover_file.suffix.lower(), "application/octet-stream")


def cmd_reindex(args: argparse.Namespace) -> int:
    """Rebuild index.db from the source EPUBs it already knows about.

    The fix for a schema too old to open the normal way: source paths and
    series/order live inside the very file that has to be rebuilt, so this
    reads them with a raw connection first, then re-ingests into a fresh
    index.db under the same book ids. Backs up the old file to
    `index.db.bak`; restores it on any failure so the index is never left
    half-rebuilt.
    """
    old_path = paths.index_db_path()
    if not old_path.is_file():
        print(f"error: no index.db at {old_path}", file=sys.stderr)
        return 1

    raw = sqlite3.connect(str(old_path))
    raw.row_factory = sqlite3.Row
    try:
        # The old database may predate the `standalone` column (an additive
        # migration that only runs through connect_index, not this raw read).
        has_standalone = "standalone" in {
            r["name"] for r in raw.execute("PRAGMA table_info(book)")
        }
        if has_standalone:
            books = raw.execute(
                "SELECT id, source_path, series_id, book_order, standalone FROM book "
                "ORDER BY series_id, book_order"
            ).fetchall()
        else:
            books = raw.execute(
                "SELECT id, source_path, series_id, book_order FROM book "
                "ORDER BY series_id, book_order"
            ).fetchall()
    finally:
        raw.close()

    missing = [b["source_path"] for b in books if not Path(b["source_path"]).is_file()]
    if missing:
        print("error: cannot reindex, source file(s) missing:", file=sys.stderr)
        for p in missing:
            print(f"  - {p}", file=sys.stderr)
        return 1

    bak_path = old_path.with_name(old_path.name + ".bak")
    os.replace(old_path, bak_path)

    results = []
    try:
        iconn = db.connect_index()
        for b in books:
            result = ingest.ingest_book(
                b["source_path"],
                series_id=b["series_id"],
                book_order=b["book_order"],
                book_id=b["id"],
                iconn=iconn,
                standalone=bool(b["standalone"]) if has_standalone else False,
            )
            results.append(result)
            if not args.json:
                print(f"{result.book_id}: reingested ({result.chapters} chapters, "
                      f"{result.paragraphs} paragraphs)")
        iconn.close()
    except Exception as exc:
        old_path.unlink(missing_ok=True)
        os.replace(bak_path, old_path)
        print(f"error: reindex failed, restored the previous index.db: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps([r.__dict__ for r in results], indent=2, default=str))
    else:
        print(f"reindexed {len(results)} book(s); previous index.db backed up to {bak_path}")
    return 0


def cmd_digest(args: argparse.Namespace) -> int:
    """Run the progressive digest + entity pass over a book, printing per-chapter progress."""
    iconn, _pconn = _open_dbs()
    llm = BudgetedLLM(get_provider(args.provider), max_calls=args.max_calls)

    count = 0

    def on_progress(event) -> None:
        nonlocal count
        count += 1
        status = "skipped" if event.skipped else "done"
        print(f"[{count}] {event.level} {event.label!r} -- {status}")

    progress_cb = None if args.json else on_progress

    try:
        result = passes.run_book(iconn, llm, args.book_id, resume=args.resume, on_progress=progress_cb)
    except (BudgetExceeded, FatalLLMError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        print(
            f"partial progress: {count} chapter/part/book unit(s) reported before the failure "
            "-- already-written digests are safe to resume from",
            file=sys.stderr,
        )
        return 1

    payload = dict(result.__dict__)
    payload["llm_calls_made"] = llm.calls_made
    payload["llm_tokens_used"] = llm.tokens_used
    payload["llm_cost_usd"] = llm.cost_usd

    if args.json:
        print(json.dumps(payload, indent=2))
        return 0

    print(f"chapters_processed={result.chapters_processed} chapters_skipped={result.chapters_skipped}")
    print(f"digests_written={result.digests_written} entities_created={result.entities_created} "
          f"edges_created={result.edges_created} attrs_created={result.attrs_created}")
    print(f"calls_made={llm.calls_made} rerolls={result.rerolls} tokens_used={llm.tokens_used} "
          f"cost_usd={llm.cost_usd:.4f}")
    return 0


def cmd_books(args: argparse.Namespace) -> int:
    """List the library with the reader's standing in each book."""
    iconn, pconn = _open_dbs()
    with tools.Tools(iconn, pconn) as t:
        books = t.list_books()
    _print(books, args.json)
    return 0


def cmd_progress(args: argparse.Namespace) -> int:
    """Set reading position and confirm the boundary it resolved to.

    `--chapter` takes the number printed in the book (or a named division
    like "prologue"), never the internal chapter_idx.
    """
    iconn, pconn = _open_dbs()
    chapter_idx = None
    if args.chapter is not None:
        chapter_idx = tools.resolve_chapter_ref(iconn, args.book_id, args.chapter)
    prog = progress.set_position(
        pconn, iconn, args.book_id, status=args.status, chapter_idx=chapter_idx
    )
    with tools.Tools(iconn, pconn) as t:
        chapters = t.list_chapters(args.book_id)["chapters"]
    resolved_label = chapters[-1]["label"] if chapters else None

    result = {
        "book_id": prog.book_id,
        "status": prog.status,
        "position_chapter_idx": prog.position_chapter_idx,
        "ceiling_seq": prog.ceiling_seq,
        "resolved_chapter_label": resolved_label,
    }
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"{args.book_id}: status={prog.status} ceiling_seq={prog.ceiling_seq}")
        print(f"  resolved boundary: {resolved_label!r} "
              "(the reading position is ambiguous by nature -- confirm this is right)")
    return 0


def cmd_chapters(args: argparse.Namespace) -> int:
    """List the chapters the reader has begun."""
    iconn, pconn = _open_dbs()
    with tools.Tools(iconn, pconn) as t:
        result = t.list_chapters(args.book_id, part=args.part)
    _print(result, args.json)
    return 0


def cmd_positions(args: argparse.Namespace) -> int:
    """Show the reading-position picker: structure for the whole book, titles once reached."""
    iconn, pconn = _open_dbs()
    with tools.Tools(iconn, pconn) as t:
        result = t.list_chapter_positions(args.book_id)
    _print(result, args.json)
    return 0


def cmd_read(args: argparse.Namespace) -> int:
    """Print raw text for a chapter range."""
    iconn, pconn = _open_dbs()
    with tools.Tools(iconn, pconn) as t:
        result = t.read_raw(args.book_id, args.from_ch, args.to_ch)
    if args.json:
        print(json.dumps(result, indent=2))
        return 0
    for p in result["paragraphs"]:
        print(f"[{p['citation_id']}] ({p['chapter']}) {p['text']}")
    if "truncated_at" in result:
        print(f"-- truncated at {result['truncated_at']!r} ({result['reason']}) --")
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    """Search the text the reader has already read."""
    iconn, pconn = _open_dbs()
    with tools.Tools(iconn, pconn) as t:
        result = t.search(args.query, book=args.book, regex=args.regex)
    if args.json:
        print(json.dumps(result, indent=2))
        return 0
    if result.get("error"):
        print(f"error: {result['error']}")
        return 0
    for r in result["results"]:
        print(f"[{r['citation_id']}] ({r['chapter']}) {r['snippet']}")
    return 0


def cmd_first_seen(args: argparse.Namespace) -> int:
    """Report where something was first encountered."""
    iconn, pconn = _open_dbs()
    with tools.Tools(iconn, pconn) as t:
        result = t.first_seen(args.entity)
    _print(result, args.json)
    return 0


def cmd_context(args: argparse.Namespace) -> int:
    """Expand the passage around a citation."""
    iconn, pconn = _open_dbs()
    with tools.Tools(iconn, pconn) as t:
        try:
            result = t.context(args.citation_id, window=args.window)
        except ValueError as exc:
            print(f"error: {exc}")
            return 1
    if args.json:
        print(json.dumps(result, indent=2))
        return 0
    for p in result["paragraphs"]:
        marker = ">> " if p["citation_id"] == args.citation_id else "   "
        print(f"{marker}[{p['citation_id']}] ({p['chapter']}) {p['text']}")
    if "truncated_at" in result:
        print(f"-- truncated at {result['truncated_at']!r} ({result['reason']}) --")
    return 0


def cmd_cast(args: argparse.Namespace) -> int:
    """Show the cast as the reader knows it."""
    iconn, pconn = _open_dbs()
    with tools.Tools(iconn, pconn) as t:
        result = t.cast(book=args.book)
    _print(result, args.json)
    return 0


def cmd_credits(args: argparse.Namespace) -> int:
    """Report the configured OpenRouter key's remaining balance."""
    from dataclasses import asdict

    from booklens.llm.base import TransientLLMError
    from booklens.llm.openrouter import get_credits

    try:
        credits = asdict(get_credits())
    except (FatalLLMError, TransientLLMError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    _print(credits, args.json)
    return 0


def cmd_chat(args: argparse.Namespace) -> int:
    """Resolve the reading position, assemble the readable set once, and start the REPL.

    `--chapter` is the reader-facing reference (a printed number, or a named
    division like 'prologue'); an unresolvable one exits with the error
    `tools.resolve_chapter_ref` raises, which already names what's valid.
    `--chapter` is a lens on the corpus, not a claim about what the reader has
    read, so it is applied to an in-memory clone of progress and never
    written to `data/progress.db` -- see `chat.ephemeral_ceiling_conn`.
    """
    iconn, _pconn = _open_dbs()
    try:
        chapter_idx = tools.resolve_chapter_ref(iconn, args.book_id, args.chapter)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    session_pconn = chat.ephemeral_ceiling_conn(iconn, args.book_id, chapter_idx)
    series_id, target_order = progress.series_and_order(iconn, args.book_id)
    prior_titles = [
        row["title"]
        for row in iconn.execute(
            "SELECT title FROM book WHERE series_id = ? AND book_order < ? ORDER BY book_order",
            (series_id, target_order),
        )
    ]

    with tools.Tools(iconn, session_pconn) as t:
        assembled = context.assemble(t)
        chapters = t.list_chapters(args.book_id)["chapters"]
        book = next((b for b in t.list_books() if b["id"] == args.book_id), None)

    title = book["title"] if book else args.book_id
    chapter_label = chapters[-1]["label"] if chapters else args.chapter

    llm = chat.build_llm(args.provider)
    session = chat.ChatSession(llm, assembled, temperature=args.temperature)
    return chat.run_repl(
        session, title=title, chapter_label=chapter_label, prior_titles=prior_titles, debug=args.debug
    )


def cmd_serve(args: argparse.Namespace) -> int:
    """Run the local web API (and, if built, the SPA) with uvicorn."""
    try:
        import uvicorn
    except ImportError:
        print("error: uvicorn is not installed; `pip install booklens[web]`", file=sys.stderr)
        return 1
    uvicorn.run("booklens.web.app:app", host=args.host, port=args.port, reload=args.reload)
    return 0


def _goodreads_user_id(args: argparse.Namespace) -> str:
    """Resolve the Goodreads user id from `--user-id`, falling back to `GOODREADS_USER_ID`."""
    user_id = args.user_id or os.environ.get("GOODREADS_USER_ID")
    if not user_id:
        raise ValueError("no Goodreads user id: pass --user-id or set GOODREADS_USER_ID")
    return user_id


def cmd_goodreads_sync(args: argparse.Namespace) -> int:
    """Fetch every configured shelf from Goodreads and cache it in goodreads.db."""
    from booklens.goodreads import GoodreadsError, connect, sync

    user_id = _goodreads_user_id(args)
    conn = connect()
    try:
        report = sync(conn, user_id, dnf_shelf=args.dnf_shelf)
    except GoodreadsError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(
            {
                "shelf_counts": report.shelf_counts,
                "truncated_shelves": list(report.truncated_shelves),
                "total_books": report.total_books,
            },
            indent=2,
        ))
        return 0

    for shelf, count in report.shelf_counts.items():
        print(f"{shelf}: {count} book(s)")
    print(f"total: {report.total_books} book(s)")
    for shelf in report.truncated_shelves:
        print(
            f"WARNING: shelf {shelf!r} returned {report.shelf_counts[shelf]} items -- "
            "Goodreads' RSS feed caps at 100, so this shelf is almost certainly "
            "incomplete, and the local cache was NOT pruned of vanished books for it"
        )
    return 0


def cmd_goodreads_shelf(args: argparse.Namespace) -> int:
    """List cached books on one shelf (or all books, when `--all` given)."""
    from dataclasses import asdict

    from booklens.goodreads import all_books, books_on_shelf, connect

    conn = connect()
    books = all_books(conn) if args.shelf == "all" else books_on_shelf(conn, args.shelf)

    if args.json:
        print(json.dumps([asdict(b) for b in books], indent=2, default=str))
        return 0

    for b in books:
        rating = f" ({b.user_rating}*)" if b.user_rating else ""
        print(f"[{b.shelf}] {b.title} -- {b.author}{rating}")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    """Summarise where data lives and how far the reader has got."""
    iconn, pconn = _open_dbs()
    with tools.Tools(iconn, pconn) as t:
        result = {
            "data_dir": str(paths.data_dir()),
            "schema_version": db.SCHEMA_VERSION,
            "book_count": len(t.list_books()),
            "ceiling_seq": progress.ceiling_for(pconn, iconn),
        }
    _print(result, args.json)
    return 0


# -- argparse wiring ------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    """Assemble the argument parser and its subcommands."""
    load_dotenv()
    parser = argparse.ArgumentParser(prog="booklens")
    sub = parser.add_subparsers(dest="command", required=True)

    p_ingest = sub.add_parser("ingest", help="ingest one or more EPUBs into a series")
    p_ingest.add_argument("epubs", nargs="+")
    p_ingest.add_argument("--series", required=True)
    p_ingest.add_argument("--start-order", type=int, default=1)
    p_ingest.add_argument("--force", action="store_true")
    p_ingest.add_argument("--json", action="store_true")
    p_ingest.set_defaults(func=cmd_ingest)

    p_covers = sub.add_parser("covers", help="backfill covers for already-ingested books")
    p_covers.add_argument("--force", action="store_true", help="overwrite an existing cover")
    p_covers.add_argument("--json", action="store_true")
    p_covers.set_defaults(func=cmd_covers)

    p_adopt = sub.add_parser(
        "adopt-sources", help="backfill each book's own copy of its EPUB into the library"
    )
    p_adopt.add_argument("--json", action="store_true")
    p_adopt.set_defaults(func=cmd_adopt_sources)

    p_reindex = sub.add_parser("reindex", help="rebuild index.db from its source EPUBs")
    p_reindex.add_argument("--json", action="store_true")
    p_reindex.set_defaults(func=cmd_reindex)

    p_digest = sub.add_parser("digest", help="run the progressive digest + entity pass over a book")
    p_digest.add_argument("book_id")
    p_digest.add_argument("--provider", default=None, help="'fake' (default) or 'claude-sdk'")
    p_digest.add_argument("--max-calls", type=int, default=200)
    p_digest.add_argument("--no-resume", dest="resume", action="store_false", default=True)
    p_digest.add_argument("--json", action="store_true")
    p_digest.set_defaults(func=cmd_digest)

    p_books = sub.add_parser("books", help="list ingested books")
    p_books.add_argument("--json", action="store_true")
    p_books.set_defaults(func=cmd_books)

    p_progress = sub.add_parser("progress", help="set a book's reading position")
    p_progress.add_argument("book_id")
    p_progress.add_argument("--status", required=True, choices=["unread", "reading", "finished"])
    p_progress.add_argument(
        "--chapter", default=None,
        help="the printed chapter number or a named division (e.g. 'prologue'), not the internal index",
    )
    p_progress.add_argument("--json", action="store_true")
    p_progress.set_defaults(func=cmd_progress)

    p_chapters = sub.add_parser("chapters", help="list a book's readable chapters")
    p_chapters.add_argument("book_id")
    p_chapters.add_argument("--part", default=None)
    p_chapters.add_argument("--json", action="store_true")
    p_chapters.set_defaults(func=cmd_chapters)

    p_positions = sub.add_parser("positions", help="show the reading-position picker")
    p_positions.add_argument("book_id")
    p_positions.add_argument("--json", action="store_true")
    p_positions.set_defaults(func=cmd_positions)

    p_read = sub.add_parser("read", help="read raw paragraphs in a chapter range")
    p_read.add_argument("book_id")
    p_read.add_argument("--from", dest="from_ch", type=int, required=True)
    p_read.add_argument("--to", dest="to_ch", type=int, required=True)
    p_read.add_argument("--json", action="store_true")
    p_read.set_defaults(func=cmd_read)

    p_search = sub.add_parser("search", help="search readable text")
    p_search.add_argument("query")
    p_search.add_argument("--book", default=None)
    p_search.add_argument("--regex", action="store_true")
    p_search.add_argument("--json", action="store_true")
    p_search.set_defaults(func=cmd_search)

    p_first_seen = sub.add_parser("first-seen", help="find the first readable mention of an entity")
    p_first_seen.add_argument("entity")
    p_first_seen.add_argument("--json", action="store_true")
    p_first_seen.set_defaults(func=cmd_first_seen)

    p_context = sub.add_parser("context", help="expand a citation with surrounding paragraphs")
    p_context.add_argument("citation_id")
    p_context.add_argument("--window", type=int, default=3)
    p_context.add_argument("--json", action="store_true")
    p_context.set_defaults(func=cmd_context)

    p_cast = sub.add_parser("cast", help="list known characters (stub until Phase 1)")
    p_cast.add_argument("--book", default=None)
    p_cast.add_argument("--json", action="store_true")
    p_cast.set_defaults(func=cmd_cast)

    p_chat = sub.add_parser("chat", help="interactive chat bounded to a fixed reading position")
    p_chat.add_argument("--book", dest="book_id", required=True)
    p_chat.add_argument(
        "--chapter", required=True,
        help="the printed chapter number or a named division (e.g. 'prologue'), fixed for the session",
    )
    p_chat.add_argument("--temperature", type=float, default=chat.DEFAULT_TEMPERATURE)
    p_chat.add_argument("--debug", action="store_true", help="start with per-turn debug output on")
    p_chat.add_argument("--provider", default="openrouter", help="LLM provider name (default: openrouter)")
    p_chat.set_defaults(func=cmd_chat)

    p_serve = sub.add_parser("serve", help="run the local web API")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8000)
    p_serve.add_argument("--reload", action="store_true")
    p_serve.set_defaults(func=cmd_serve)

    p_status = sub.add_parser("status", help="show data dir, schema, and ceiling info")
    p_status.add_argument("--json", action="store_true")
    p_status.set_defaults(func=cmd_status)

    p_credits = sub.add_parser("credits", help="show remaining OpenRouter credit balance")
    p_credits.add_argument("--json", action="store_true")
    p_credits.set_defaults(func=cmd_credits)

    p_goodreads = sub.add_parser("goodreads", help="read-only Goodreads shelf sync")
    goodreads_sub = p_goodreads.add_subparsers(dest="goodreads_command", required=True)

    p_gr_sync = goodreads_sub.add_parser("sync", help="fetch and cache every configured shelf")
    p_gr_sync.add_argument(
        "--user-id", default=None,
        help="Goodreads numeric user id (falls back to GOODREADS_USER_ID)",
    )
    p_gr_sync.add_argument(
        "--dnf-shelf", default=None,
        help="the user's did-not-finish shelf name, if any (shelf names are user-chosen)",
    )
    p_gr_sync.add_argument("--json", action="store_true")
    p_gr_sync.set_defaults(func=cmd_goodreads_sync)

    p_gr_shelf = goodreads_sub.add_parser("shelf", help="list cached books on one shelf")
    p_gr_shelf.add_argument("shelf", help="'read', 'currently-reading', 'to-read', a configured DNF shelf, or 'all'")
    p_gr_shelf.add_argument("--json", action="store_true")
    p_gr_shelf.set_defaults(func=cmd_goodreads_shelf)

    return parser


def main(argv: list[str] | None = None) -> int:
    """Run a single CLI invocation, returning its exit code."""
    parser = build_parser()
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])
    try:
        return args.func(args)
    except db.SchemaVersionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
