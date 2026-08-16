"""Command line entry point for ingesting and querying books.

Retrieval always goes through `Tools`, never ad-hoc SQL, so the CLI cannot
become a second unbounded path to the text.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from booklens import db, ingest, passes, paths, progress, tools
from booklens.llm.base import BudgetedLLM, BudgetExceeded, FatalLLMError, get_provider


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


def _manifest_for(sha256: str) -> dict:
    """Load a book's ingest manifest, empty if it was never written."""
    p = paths.book_dir(sha256) / "manifest.json"
    if not p.is_file():
        return {}
    return json.loads(p.read_text())


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
        manifest = _manifest_for(result.sha256)
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
    """Set reading position and confirm the boundary it resolved to."""
    iconn, pconn = _open_dbs()
    prog = progress.set_position(
        pconn, iconn, args.book_id, status=args.status, chapter_idx=args.chapter
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
    parser = argparse.ArgumentParser(prog="booklens")
    sub = parser.add_subparsers(dest="command", required=True)

    p_ingest = sub.add_parser("ingest", help="ingest one or more EPUBs into a series")
    p_ingest.add_argument("epubs", nargs="+")
    p_ingest.add_argument("--series", required=True)
    p_ingest.add_argument("--start-order", type=int, default=1)
    p_ingest.add_argument("--force", action="store_true")
    p_ingest.add_argument("--json", action="store_true")
    p_ingest.set_defaults(func=cmd_ingest)

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
    p_progress.add_argument("--chapter", type=int, default=None)
    p_progress.add_argument("--json", action="store_true")
    p_progress.set_defaults(func=cmd_progress)

    p_chapters = sub.add_parser("chapters", help="list a book's readable chapters")
    p_chapters.add_argument("book_id")
    p_chapters.add_argument("--part", default=None)
    p_chapters.add_argument("--json", action="store_true")
    p_chapters.set_defaults(func=cmd_chapters)

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

    p_status = sub.add_parser("status", help="show data dir, schema, and ceiling info")
    p_status.add_argument("--json", action="store_true")
    p_status.set_defaults(func=cmd_status)

    p_credits = sub.add_parser("credits", help="show remaining OpenRouter credit balance")
    p_credits.add_argument("--json", action="store_true")
    p_credits.set_defaults(func=cmd_credits)

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
