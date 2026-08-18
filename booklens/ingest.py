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
from booklens.extract.cover import _extension_for, extract_cover

_SLUG_RE = re.compile(r"[^a-z0-9]+")

# A short chapter isn't dropped -- section 3 rejects length-based exclusion --
# but it's worth an operator's eye: this is the gap between real short
# chapters (a prologue) and the boilerplate the classifier already catches.
LIKELY_BOILERPLATE_BODY_WORDS = 400
LIKELY_BOILERPLATE_REFERENCE_WORDS = 250


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


def _write_cover(path: Path, book_dir: Path) -> str | None:
    """Extract and write the book's cover, returning the tier used or None.

    Never raises -- a cover extraction failure must not fail the (expensive,
    resumable) ingest pass.
    """
    try:
        cover = extract_cover(path)
    except Exception:
        return None
    if cover is None:
        return None
    ext = _extension_for(cover.media_type, cover.zip_path)
    (book_dir / f"cover{ext}").write_bytes(cover.data)
    return cover.tier


def _skip_result(iconn: sqlite3.Connection, sha256: str) -> IngestResult:
    """Rebuild the result for a book already present, without re-reading it."""
    row = iconn.execute(
        "SELECT id, title, book_order, sequence_tier, label_tier FROM book WHERE sha256 = ?",
        (sha256,),
    ).fetchone()
    manifest_path = paths.book_dir(row["id"]) / "manifest.json"
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


def relocate_source(iconn: sqlite3.Connection, book_id: str, new_path: str | Path) -> None:
    """Move a book's retained source file to `new_path`, keeping `book.source_path`
    and `meta.json` in agreement with where it actually is.

    A no-op move (source already at `new_path`) still rewrites the records,
    which is cheap and keeps this idempotent.
    """
    row = iconn.execute("SELECT source_path FROM book WHERE id = ?", (book_id,)).fetchone()
    if row is None:
        raise ValueError(f"unknown book_id {book_id!r}")

    old_path = Path(row["source_path"])
    new_path = Path(new_path)
    new_path.parent.mkdir(parents=True, exist_ok=True)
    if old_path != new_path and old_path.is_file():
        old_path.replace(new_path)

    iconn.execute("UPDATE book SET source_path = ? WHERE id = ?", (str(new_path), book_id))
    iconn.commit()

    meta_path = paths.book_dir(book_id) / "meta.json"
    if meta_path.is_file():
        meta = json.loads(meta_path.read_text())
        meta["source_path"] = str(new_path)
        meta_path.write_text(json.dumps(meta, indent=2))


def ingest_book(
    path: str | Path,
    *,
    series_id: str,
    book_order: int,
    book_id: str | None = None,
    iconn: sqlite3.Connection | None = None,
    force: bool = False,
    standalone: bool | None = None,
    title: str | None = None,
    author: str | None = None,
) -> IngestResult:
    """Read a book into the index, assigning every paragraph its sequence.

    Runs as one transaction, so a failure leaves no half-ingested book behind.
    `standalone` defaults to preserving whatever a re-ingested row already had
    (or False for a genuinely new book); pass it explicitly to set the flag.
    `title`/`author` override what the EPUB's own metadata claims, when given
    -- e.g. an embedded author string that carries stray punctuation. Extraction
    itself is untouched; only the values stored and returned are overridden.
    """
    path = Path(path)
    if iconn is None:
        iconn = db.connect_index()

    sha256 = _sha256_of_file(path)
    existing = iconn.execute(
        "SELECT id, standalone FROM book WHERE sha256 = ?", (sha256,)
    ).fetchone()

    if existing is not None and not force:
        return _skip_result(iconn, sha256)

    resolved_standalone = standalone
    if existing is not None and force:
        if resolved_standalone is None:
            resolved_standalone = bool(existing["standalone"])
        iconn.execute("DELETE FROM book WHERE id = ?", (existing["id"],))
        iconn.commit()
    if resolved_standalone is None:
        resolved_standalone = False

    # Full extraction ladder -- only paid for on a genuine new/forced ingest.
    book = extract_book(path)
    assert book.sha256 == sha256, "sha256 mismatch between pre-hash and extraction"

    resolved_title = title if title is not None else book.title
    resolved_author = author if author is not None else book.author

    resolved_book_id = book_id if book_id is not None else _slugify(resolved_title)
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
    size_flags: list[dict] = []

    try:
        iconn.execute(
            """
            INSERT INTO book(id, sha256, title, author, source_path, series_id,
                              book_order, sequence_tier, label_tier, ingested_at, standalone)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                resolved_book_id,
                book.sha256,
                resolved_title,
                resolved_author,
                str(path),
                series_id,
                book_order,
                book.sequence_tier,
                book.label_tier,
                _now(),
                int(resolved_standalone),
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

            word_count = sum(len(text.split()) for *_ignored, text in rows_for_chapter)
            threshold = {
                "body": LIKELY_BOILERPLATE_BODY_WORDS,
                "reference": LIKELY_BOILERPLATE_REFERENCE_WORDS,
            }.get(kind)
            if threshold is not None and word_count < threshold:
                size_flags.append({"label": ch.label, "kind": kind, "words": word_count})

        iconn.commit()
    except Exception:
        iconn.rollback()
        raise

    book_dir = paths.book_dir(resolved_book_id)
    meta = {
        "title": resolved_title,
        "author": resolved_author,
        "source_path": str(path),
        "sha256": book.sha256,
        "series_id": series_id,
        "book_order": book_order,
    }
    (book_dir / "meta.json").write_text(json.dumps(meta, indent=2))

    cover_tier = _write_cover(path, book_dir)

    manifest = {
        "schema_version": db.SCHEMA_VERSION,
        "sequence_tier": book.sequence_tier,
        "label_tier": book.label_tier,
        "cover_tier": cover_tier,
        "ingested_at": _now(),
        "documents": len(book.documents),
        "chapters": chapters_written,
        "paragraphs": total_paragraphs,
        "excerpt_paragraphs": total_excerpt_paragraphs,
        "excerpt_chapters": excerpt_summary,
        "skipped_empty_chapters": skipped_empty_chapters,
        "size_flags": size_flags,
    }
    (book_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    paths.digests_dir(resolved_book_id)  # created empty; Phase 1 fills it

    return IngestResult(
        book_id=resolved_book_id,
        title=resolved_title,
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
