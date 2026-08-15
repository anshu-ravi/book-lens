"""One-time batch ingest, turning an EPUB into index rows and metadata.

Content-addressed by hash, so re-importing a file is a no-op. The source EPUB
is never written to.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from booklens import classify, db, paths
from booklens.extract import extract_book

_SLUG_RE = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class IngestResult:
    """What one ingest run produced, or skipped."""

    book_id: str
    title: str
    sha256: str
    book_order: int
    documents: int
    chapters: int
    paragraphs: int
    excerpt_paragraphs: int
    sequence_tier: str
    label_tier: str
    skipped: bool  # True if this sha256 was already ingested


def _now() -> str:
    """Current UTC time, as stored in the timestamp columns."""
    return datetime.now(timezone.utc).isoformat()


def _sha256_of_file(path: Path) -> str:
    """Hash the file so an already-ingested book can be skipped before parsing."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _slugify(title: str) -> str:
    """Derive a book id from a title, safe to embed in a citation."""
    slug = _SLUG_RE.sub("-", title.lower()).strip("-")
    return slug or "book"


def _unique_book_id(iconn: sqlite3.Connection, base: str) -> str:
    """Suffix the slug as needed so two books never share an id."""
    candidate = base
    n = 2
    while iconn.execute("SELECT 1 FROM book WHERE id = ?", (candidate,)).fetchone() is not None:
        candidate = f"{base}-{n}"
        n += 1
    return candidate


def _skip_result(iconn: sqlite3.Connection, sha256: str) -> IngestResult:
    """Rebuild the result for a book already present, without re-reading it."""
    row = iconn.execute(
        "SELECT id, title, book_order, sequence_tier, label_tier FROM book WHERE sha256 = ?",
        (sha256,),
    ).fetchone()
    manifest_path = paths.book_dir(sha256) / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.is_file() else {}
    return IngestResult(
        book_id=row["id"],
        title=row["title"],
        sha256=sha256,
        book_order=row["book_order"],
        documents=manifest.get("documents", 0),
        chapters=manifest.get("chapters", 0),
        paragraphs=manifest.get("paragraphs", 0),
        excerpt_paragraphs=manifest.get("excerpt_paragraphs", 0),
        sequence_tier=row["sequence_tier"],
        label_tier=row["label_tier"],
        skipped=True,
    )


def ingest_book(
    path: str | Path,
    *,
    series_id: str,
    book_order: int,
    book_id: str | None = None,
    iconn: sqlite3.Connection | None = None,
    force: bool = False,
) -> IngestResult:
    """Read a book into the index, assigning every paragraph its sequence.

    Runs as one transaction, so a failure leaves no half-ingested book behind.
    """
    path = Path(path)
    if iconn is None:
        iconn = db.connect_index()

    sha256 = _sha256_of_file(path)
    existing = iconn.execute("SELECT id FROM book WHERE sha256 = ?", (sha256,)).fetchone()

    if existing is not None and not force:
        return _skip_result(iconn, sha256)

    if existing is not None and force:
        iconn.execute("DELETE FROM book WHERE id = ?", (existing["id"],))
        iconn.commit()

    # Full extraction ladder -- only paid for on a genuine new/forced ingest.
    book = extract_book(path)
    assert book.sha256 == sha256, "sha256 mismatch between pre-hash and extraction"

    resolved_book_id = book_id if book_id is not None else _slugify(book.title)
    if ":" in resolved_book_id:
        raise ValueError(f"book_id must not contain ':': {resolved_book_id!r}")
    resolved_book_id = _unique_book_id(iconn, resolved_book_id)

    kinds = classify.classify_chapters(book)
    doc_paragraphs = {d.spine_idx: d.paragraphs for d in book.documents}

    total_paragraphs = 0
    total_excerpt_paragraphs = 0
    chapters_written = 0
    skipped_empty_chapters: list[str] = []
    excerpt_summary: list[dict] = []

    try:
        iconn.execute(
            """
            INSERT INTO book(id, sha256, title, author, source_path, series_id,
                              book_order, sequence_tier, label_tier, ingested_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                resolved_book_id,
                book.sha256,
                book.title,
                book.author,
                str(path),
                series_id,
                book_order,
                book.sequence_tier,
                book.label_tier,
                _now(),
            ),
        )

        for ch in book.chapters:
            kind = kinds[ch.chapter_idx]
            rows_for_chapter: list[tuple[int, int, int, str]] = []
            for spine_idx in range(ch.start_spine_idx, ch.end_spine_idx + 1):
                for p in doc_paragraphs.get(spine_idx, ()):
                    gseq = db.global_seq(book_order, spine_idx, p.para_idx)  # raises loudly on overflow
                    rows_for_chapter.append((spine_idx, p.para_idx, gseq, p.text))

            if not rows_for_chapter:
                # A chapter whose documents yielded zero paragraphs must not
                # get a bogus start_seq/end_seq range -- skip and report it.
                skipped_empty_chapters.append(ch.label)
                continue

            seqs = [r[2] for r in rows_for_chapter]
            start_seq, end_seq = min(seqs), max(seqs)

            iconn.execute(
                """
                INSERT INTO chapter(book_id, chapter_idx, label, part_label,
                                     start_seq, end_seq, kind)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (resolved_book_id, ch.chapter_idx, ch.label, ch.part_label, start_seq, end_seq, kind),
            )
            chapters_written += 1

            for spine_idx, para_idx, gseq, text in rows_for_chapter:
                iconn.execute(
                    """
                    INSERT INTO para(book_id, spine_idx, para_idx, global_seq,
                                      chapter_idx, chapter_label, text, kind)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (resolved_book_id, spine_idx, para_idx, gseq, ch.chapter_idx, ch.label, text, kind),
                )
                total_paragraphs += 1
                if kind == "excerpt":
                    total_excerpt_paragraphs += 1

            if kind == "excerpt":
                excerpt_summary.append({"label": ch.label, "paragraphs": len(rows_for_chapter)})

        iconn.commit()
    except Exception:
        iconn.rollback()
        raise

    book_dir = paths.book_dir(book.sha256)
    meta = {
        "title": book.title,
        "author": book.author,
        "source_path": str(path),
        "sha256": book.sha256,
        "series_id": series_id,
        "book_order": book_order,
    }
    (book_dir / "meta.json").write_text(json.dumps(meta, indent=2))

    manifest = {
        "schema_version": db.SCHEMA_VERSION,
        "sequence_tier": book.sequence_tier,
        "label_tier": book.label_tier,
        "ingested_at": _now(),
        "documents": len(book.documents),
        "chapters": chapters_written,
        "paragraphs": total_paragraphs,
        "excerpt_paragraphs": total_excerpt_paragraphs,
        "excerpt_chapters": excerpt_summary,
        "skipped_empty_chapters": skipped_empty_chapters,
    }
    (book_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    paths.digests_dir(book.sha256)  # created empty; Phase 1 fills it

    return IngestResult(
        book_id=resolved_book_id,
        title=book.title,
        sha256=book.sha256,
        book_order=book_order,
        documents=len(book.documents),
        chapters=chapters_written,
        paragraphs=total_paragraphs,
        excerpt_paragraphs=total_excerpt_paragraphs,
        sequence_tier=book.sequence_tier,
        label_tier=book.label_tier,
        skipped=False,
    )
