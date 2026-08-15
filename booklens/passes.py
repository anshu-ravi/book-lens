"""The progressive digest and entity pass: one batch job, front to back, per book.

See DECISIONS.md section 11 for the overall shape and `docs/implementation-notes.md`
for how causality is enforced and tested.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from booklens import causal, db, paths, prompts
from booklens.llm.base import LLM

_SLUG_RE = re.compile(r"[^a-z0-9]+")


@dataclass
class PassResult:
    """What one pass run produced, so a caller can tell progress from a no-op."""

    book_id: str
    chapters_processed: int = 0
    chapters_skipped: int = 0
    digests_written: int = 0
    entities_created: int = 0
    edges_created: int = 0
    attrs_created: int = 0
    calls_made: int = 0


def _now() -> str:
    """Current UTC time, as stored in the timestamp columns."""
    return datetime.now(timezone.utc).isoformat()


def _slugify_part(label: str) -> str:
    """Turn a part label into a filesystem-safe basename."""
    slug = _SLUG_RE.sub("-", label.lower()).strip("-")
    return slug or "part"


def _book_sha256(iconn: sqlite3.Connection, book_id: str) -> str:
    """The hash that keys this book's on-disk digest directory."""
    row = iconn.execute("SELECT sha256 FROM book WHERE id = ?", (book_id,)).fetchone()
    if row is None:
        raise ValueError(f"unknown book_id {book_id!r}")
    return row["sha256"]


def _existing_digest(
    iconn: sqlite3.Connection, book_id: str, level: str, chapter_idx: int | None, part_label: str | None
) -> sqlite3.Row | None:
    """Look up a digest row by its true target key, comparing NULLs correctly.

    SQLite's UNIQUE index treats NULLs as distinct from each other, so the
    schema's unique index alone cannot stop a caller from inserting a second
    NULL-part_label row for the same chapter. This lookup (and the delete
    that precedes every insert below) is what actually enforces "one digest
    per target" -- the index exists as a second line of defense, not the
    only one.
    """
    query = (
        "SELECT id, prompt_hash, schema_version, path, source_start_seq, source_end_seq FROM digest "
        "WHERE book_id = ? AND level = ? AND chapter_idx IS ? AND part_label IS ?"
    )
    return iconn.execute(query, (book_id, level, chapter_idx, part_label)).fetchone()


def _delete_digest(
    iconn: sqlite3.Connection, book_id: str, level: str, chapter_idx: int | None, part_label: str | None
) -> None:
    query = "DELETE FROM digest WHERE book_id = ? AND level = ? AND chapter_idx IS ? AND part_label IS ?"
    iconn.execute(query, (book_id, level, chapter_idx, part_label))


def _delete_chapter_entities(iconn: sqlite3.Connection, book_id: str, para_ids: list[int]) -> None:
    """Remove a stale chapter's entity rows before it is reprocessed.

    Deleting `entity_node` rows anchored in this chapter cascades to any
    edge or attribute that referenced them, by the FK's ON DELETE CASCADE.
    """
    for para_id in para_ids:
        iconn.execute(
            "DELETE FROM entity_node WHERE book_id = ? AND cite_para_id = ?", (book_id, para_id)
        )


def _write_digest_file(path: Path, markdown: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(markdown, encoding="utf-8")


def _read_digest_file(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def _insert_digest_row(
    iconn: sqlite3.Connection,
    *,
    book_id: str,
    level: str,
    chapter_idx: int | None,
    part_label: str | None,
    source_start_seq: int,
    source_end_seq: int,
    path: str,
    generator: str,
    prompt_hash: str,
) -> None:
    iconn.execute(
        """
        INSERT INTO digest(
            book_id, level, chapter_idx, part_label, source_start_seq, source_end_seq,
            path, generator, prompt_hash, schema_version, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            book_id,
            level,
            chapter_idx,
            part_label,
            source_start_seq,
            source_end_seq,
            path,
            generator,
            prompt_hash,
            db.SCHEMA_VERSION,
            _now(),
        ),
    )


def _insert_entities(
    iconn: sqlite3.Connection, book_id: str, chapter_end_seq: int, entities: list[prompts.EntityRecord]
) -> tuple[int, int, int]:
    """Write a chapter's freshly extracted entities, stamped at this chapter's seq.

    Aliases resolve `other_designator` against nodes already written by THIS
    same call plus the registry passed into the prompt -- a reveal can only
    ever point backward or to something introduced in the same breath.
    """
    designator_to_node_id: dict[str, int] = {}
    for r in iconn.execute("SELECT id, designator FROM entity_node WHERE book_id = ?", (book_id,)):
        designator_to_node_id[r["designator"]] = r["id"]

    nodes_created = 0
    edges_created = 0
    attrs_created = 0

    for entity in entities:
        node_id = designator_to_node_id.get(entity.designator)
        if node_id is None:
            cur = iconn.execute(
                """
                INSERT INTO entity_node(book_id, designator, node_kind, first_seq, cite_para_id)
                VALUES (?, ?, ?, ?, ?)
                """,
                (book_id, entity.designator, entity.node_kind, chapter_end_seq, entity.cite_para_id),
            )
            node_id = cur.lastrowid
            designator_to_node_id[entity.designator] = node_id
            nodes_created += 1

        for attr in entity.attributes:
            iconn.execute(
                """
                INSERT INTO entity_attr(node_id, attr_kind, value, first_seq, cite_para_id)
                VALUES (?, ?, ?, ?, ?)
                """,
                (node_id, attr.attr_kind, attr.value, chapter_end_seq, attr.cite_para_id),
            )
            attrs_created += 1

        for alias in entity.aliases:
            other_id = designator_to_node_id.get(alias.other_designator)
            if other_id is None:
                # The model asserted a coreference to a designator it never
                # introduced this chapter or earlier -- reject rather than
                # inventing a node for it, same principle as citations.
                raise ValueError(
                    f"alias for {entity.designator!r} refers to unknown designator "
                    f"{alias.other_designator!r} -- not in the registry or this chapter's new entities"
                )
            iconn.execute(
                """
                INSERT INTO entity_edge(src_node_id, dst_node_id, edge_type, revealed_at_seq, cite_para_id)
                VALUES (?, ?, ?, ?, ?)
                """,
                (node_id, other_id, alias.edge_type, chapter_end_seq, alias.cite_para_id),
            )
            edges_created += 1

    return nodes_created, edges_created, attrs_created


def run_chapter_pass(
    iconn: sqlite3.Connection, llm: LLM, book_id: str, *, resume: bool = True
) -> PassResult:
    """Walk every non-excerpt chapter front to back, producing one digest + entity set each.

    Front matter (kind='front') is processed exactly like a body chapter --
    it is seed data (e.g. a Dramatis Personae), not a hazard, per
    DECISIONS.md section 3. Committed per chapter so an interrupted run can
    resume without redoing completed work.
    """
    sha256 = _book_sha256(iconn, book_id)
    result = PassResult(book_id=book_id)

    all_chapters = iconn.execute(
        "SELECT chapter_idx, label, part_label, start_seq, end_seq, kind FROM chapter "
        "WHERE book_id = ? AND kind != 'excerpt' ORDER BY start_seq",
        (book_id,),
    ).fetchall()

    for ch in all_chapters:
        chapter_idx = ch["chapter_idx"]
        existing = _existing_digest(iconn, book_id, "chapter", chapter_idx, None)
        if (
            resume
            and existing is not None
            and existing["prompt_hash"] == prompts.CHAPTER_PROMPT_HASH
            and existing["schema_version"] == db.SCHEMA_VERSION
        ):
            result.chapters_skipped += 1
            continue

        window = causal.CausalWindow(iconn, max_seq=ch["end_seq"])
        registry = window.registry_state(book_id)
        paragraphs = window.chapter_paragraphs(book_id, chapter_idx)
        para_ids = {p["id"] for p in paragraphs}

        bundle = prompts.build_chapter_prompt(
            book_id=book_id,
            chapter_idx=chapter_idx,
            chapter_label=ch["label"],
            part_label=ch["part_label"],
            registry=registry,
            paragraphs=paragraphs,
        )
        response = llm.complete(bundle.messages, system=bundle.system)
        result.calls_made += 1

        # Parse before touching disk or the DB -- a malformed response must
        # leave nothing behind, not a half-written chapter.
        extraction = prompts.parse_chapter_response(response.text, valid_para_ids=para_ids)

        digest_path = paths.digests_dir(sha256) / "ch" / f"{chapter_idx:04d}.md"

        if existing is not None:
            _delete_digest(iconn, book_id, "chapter", chapter_idx, None)
            _delete_chapter_entities(iconn, book_id, sorted(para_ids))

        try:
            nodes, edges, attrs = _insert_entities(iconn, book_id, ch["end_seq"], extraction.entities)
            _insert_digest_row(
                iconn,
                book_id=book_id,
                level="chapter",
                chapter_idx=chapter_idx,
                part_label=None,
                source_start_seq=ch["start_seq"],
                source_end_seq=ch["end_seq"],
                path=str(digest_path),
                generator=getattr(llm, "model", "unknown"),
                prompt_hash=bundle.prompt_hash,
            )
            _write_digest_file(digest_path, extraction.digest_markdown)
        except Exception:
            iconn.rollback()
            raise
        iconn.commit()

        result.chapters_processed += 1
        result.digests_written += 1
        result.entities_created += nodes
        result.edges_created += edges
        result.attrs_created += attrs

    return result


def _rollup_one(
    iconn: sqlite3.Connection,
    llm: LLM,
    *,
    book_id: str,
    level: str,
    chapter_idx: None,
    part_label: str | None,
    target_label: str,
    source_rows: list[sqlite3.Row],
    digest_path: Path,
) -> None:
    """Build one part or book digest from its source digests' markdown, never raw text."""
    source_digests = [_read_digest_file(r["path"]) for r in source_rows]
    source_start_seq = min(r["source_start_seq"] for r in source_rows)
    source_end_seq = max(r["source_end_seq"] for r in source_rows)

    bundle = prompts.build_rollup_prompt(
        book_id=book_id, level=level, target_label=target_label, source_digests=source_digests
    )
    response = llm.complete(bundle.messages, system=bundle.system)
    digest_markdown = prompts.parse_rollup_response(response.text)

    _delete_digest(iconn, book_id, level, chapter_idx, part_label)
    try:
        _insert_digest_row(
            iconn,
            book_id=book_id,
            level=level,
            chapter_idx=chapter_idx,
            part_label=part_label,
            source_start_seq=source_start_seq,
            source_end_seq=source_end_seq,
            path=str(digest_path),
            generator=getattr(llm, "model", "unknown"),
            prompt_hash=bundle.prompt_hash,
        )
        _write_digest_file(digest_path, digest_markdown)
    except Exception:
        iconn.rollback()
        raise
    iconn.commit()


def run_rollups(iconn: sqlite3.Connection, llm: LLM, book_id: str) -> PassResult:
    """Build part digests from chapter digests, then a book digest from part digests.

    Always regenerates -- rollups only read already-written digest files, so
    rerunning is cheap and there is no separate staleness state to track for
    them; a chapter pass rerun is what invalidates a rollup, and this
    function has no way to know that short of always refreshing.
    """
    sha256 = _book_sha256(iconn, book_id)
    result = PassResult(book_id=book_id)

    chapter_digests = iconn.execute(
        """
        SELECT d.id, d.path, d.source_start_seq, d.source_end_seq, c.part_label, c.chapter_idx
        FROM digest d
        JOIN chapter c ON c.book_id = d.book_id AND c.chapter_idx = d.chapter_idx
        WHERE d.book_id = ? AND d.level = 'chapter'
        ORDER BY d.source_start_seq
        """,
        (book_id,),
    ).fetchall()

    part_labels = sorted({r["part_label"] for r in chapter_digests if r["part_label"] is not None})

    part_digest_rows: list[sqlite3.Row] = []
    for part_label in part_labels:
        rows = [r for r in chapter_digests if r["part_label"] == part_label]
        digest_path = paths.digests_dir(sha256) / "part" / f"{_slugify_part(part_label)}.md"
        _rollup_one(
            iconn,
            llm,
            book_id=book_id,
            level="part",
            chapter_idx=None,
            part_label=part_label,
            target_label=part_label,
            source_rows=rows,
            digest_path=digest_path,
        )
        result.calls_made += 1
        result.digests_written += 1
        row = _existing_digest(iconn, book_id, "part", None, part_label)
        part_digest_rows.append(row)

    book_source_rows = part_digest_rows if part_digest_rows else chapter_digests
    if book_source_rows:
        digest_path = paths.digests_dir(sha256) / "book.md"
        _rollup_one(
            iconn,
            llm,
            book_id=book_id,
            level="book",
            chapter_idx=None,
            part_label=None,
            target_label=book_id,
            source_rows=book_source_rows,
            digest_path=digest_path,
        )
        result.calls_made += 1
        result.digests_written += 1

    return result


def run_book(iconn: sqlite3.Connection, llm: LLM, book_id: str, *, resume: bool = True) -> PassResult:
    """Run the chapter pass, then rollups, over one book."""
    chapter_result = run_chapter_pass(iconn, llm, book_id, resume=resume)
    rollup_result = run_rollups(iconn, llm, book_id)

    return PassResult(
        book_id=book_id,
        chapters_processed=chapter_result.chapters_processed,
        chapters_skipped=chapter_result.chapters_skipped,
        digests_written=chapter_result.digests_written + rollup_result.digests_written,
        entities_created=chapter_result.entities_created,
        edges_created=chapter_result.edges_created,
        attrs_created=chapter_result.attrs_created,
        calls_made=chapter_result.calls_made + rollup_result.calls_made,
    )
