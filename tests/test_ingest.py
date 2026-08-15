"""Tests for booklens.ingest against small synthetic EPUBs (fast, deterministic)."""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from booklens import db, ingest, paths

CONTAINER_XML = """<?xml version="1.0"?>
<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>"""


def _make_epub(path: Path, title: str, docs: list[tuple[str, list[str]]], author: str = "Test Author") -> Path:
    """Build a tiny synthetic EPUB with one spine document per (label,
    paragraphs) entry and a full-coverage NCX TOC, so it resolves via the
    L1 label tier deterministically. paragraphs=[] yields an empty document
    (zero extracted paragraphs)."""
    manifest_items = []
    spine_items = []
    navpoints = []
    for i, (label, paras) in enumerate(docs):
        href = f"text/ch{i}.xhtml"
        body = "".join(f"<p>{p}</p>" for p in paras)
        with zipfile.ZipFile(path, "a") as zf:
            zf.writestr(f"OEBPS/{href}", f"<html><body>{body}</body></html>")
        manifest_items.append(f'<item id="ch{i}" href="{href}" media-type="application/xhtml+xml"/>')
        spine_items.append(f'<itemref idref="ch{i}"/>')
        navpoints.append(
            f'<navPoint id="np{i}"><navLabel><text>{label}</text></navLabel>'
            f'<content src="{href}"/></navPoint>'
        )

    opf = f"""<?xml version="1.0"?>
<package xmlns="http://www.idpf.org/2007/opf" version="2.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>{title}</dc:title>
    <dc:creator>{author}</dc:creator>
  </metadata>
  <manifest>
    {''.join(manifest_items)}
    <item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>
  </manifest>
  <spine toc="ncx">
    {''.join(spine_items)}
  </spine>
</package>"""

    ncx = f"""<?xml version="1.0"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">
  <navMap>
    {''.join(navpoints)}
  </navMap>
</ncx>"""

    with zipfile.ZipFile(path, "a") as zf:
        zf.writestr("META-INF/container.xml", CONTAINER_XML)
        zf.writestr("OEBPS/content.opf", opf)
        zf.writestr("OEBPS/toc.ncx", ncx)
    return path


def _simple_epub(tmp_path, name="book.epub", title="Sample Book") -> Path:
    return _make_epub(
        tmp_path / name,
        title,
        [
            ("Prologue", ["Once upon a time."]),
            ("Chapter 1", ["The story begins.", "It continues."]),
            ("Chapter 2", ["More happens.", "Then it ends."]),
        ],
    )


def _with_excerpt_epub(tmp_path, name="book2.epub", title="Book With Excerpt") -> Path:
    return _make_epub(
        tmp_path / name,
        title,
        [
            ("Chapter 1", ["Real content here."]),
            ("Chapter 2", ["More real content."]),
            ("Excerpt from Sequel", ["Spoiler paragraph one.", "Spoiler paragraph two."]),
        ],
    )


def _iconn(tmp_path):
    return db.connect_index(tmp_path / "index.db")


# -- basic ingest ------------------------------------------------------------


def test_ingest_basic_populates_book_chapter_para(tmp_path):
    epub = _simple_epub(tmp_path)
    iconn = _iconn(tmp_path)
    result = ingest.ingest_book(epub, series_id="s1", book_order=1, iconn=iconn)

    assert result.skipped is False
    assert result.book_id == "sample-book"
    assert result.documents == 3
    assert result.chapters == 3
    assert result.paragraphs == 5
    assert result.excerpt_paragraphs == 0
    assert result.sequence_tier == "S1"
    assert result.label_tier == "L1"

    book_row = iconn.execute("SELECT * FROM book WHERE id = ?", ("sample-book",)).fetchone()
    assert book_row is not None
    assert book_row["series_id"] == "s1"
    assert book_row["book_order"] == 1

    n_chapters = iconn.execute("SELECT COUNT(*) c FROM chapter WHERE book_id = ?", ("sample-book",)).fetchone()["c"]
    n_paras = iconn.execute("SELECT COUNT(*) c FROM para WHERE book_id = ?", ("sample-book",)).fetchone()["c"]
    assert n_chapters == 3
    assert n_paras == 5


def test_ingest_assigns_global_seq_correctly(tmp_path):
    epub = _simple_epub(tmp_path)
    iconn = _iconn(tmp_path)
    ingest.ingest_book(epub, series_id="s1", book_order=2, iconn=iconn)

    rows = iconn.execute(
        "SELECT spine_idx, para_idx, global_seq FROM para WHERE book_id = ? ORDER BY global_seq",
        ("sample-book",),
    ).fetchall()
    for r in rows:
        assert r["global_seq"] == db.global_seq(2, r["spine_idx"], r["para_idx"])


def test_ingest_never_writes_next_to_source_epub(tmp_path):
    epub_dir = tmp_path / "readonly_source"
    epub_dir.mkdir()
    epub = _simple_epub(epub_dir)
    sibling_files_before = set(epub_dir.iterdir())
    iconn = _iconn(tmp_path)  # index.db lives elsewhere
    ingest.ingest_book(epub, series_id="s1", book_order=1, iconn=iconn)
    sibling_files_after = set(epub_dir.iterdir())
    assert sibling_files_before == sibling_files_after


def test_ingest_does_not_modify_source_epub_bytes(tmp_path):
    epub = _simple_epub(tmp_path)
    before = hashlib.sha256(epub.read_bytes()).hexdigest()
    iconn = _iconn(tmp_path)
    ingest.ingest_book(epub, series_id="s1", book_order=1, iconn=iconn)
    after = hashlib.sha256(epub.read_bytes()).hexdigest()
    assert before == after


# -- book_id resolution --------------------------------------------------


def test_book_id_defaults_to_slug_of_title(tmp_path):
    epub = _make_epub(tmp_path / "x.epub", "My Great Book!", [("Chapter 1", ["Text."])])
    iconn = _iconn(tmp_path)
    result = ingest.ingest_book(epub, series_id="s1", book_order=1, iconn=iconn)
    assert result.book_id == "my-great-book"


def test_book_id_explicit_override(tmp_path):
    epub = _simple_epub(tmp_path)
    iconn = _iconn(tmp_path)
    result = ingest.ingest_book(epub, series_id="s1", book_order=1, book_id="custom-id", iconn=iconn)
    assert result.book_id == "custom-id"


def test_book_id_rejects_colon(tmp_path):
    epub = _simple_epub(tmp_path)
    iconn = _iconn(tmp_path)
    with pytest.raises(ValueError):
        ingest.ingest_book(epub, series_id="s1", book_order=1, book_id="bad:id", iconn=iconn)


def test_book_id_disambiguated_on_collision(tmp_path):
    epub1 = _make_epub(tmp_path / "a.epub", "Same Title", [("Chapter 1", ["A"])])
    epub2 = _make_epub(tmp_path / "b.epub", "Same Title", [("Chapter 1", ["B"])])
    iconn = _iconn(tmp_path)
    r1 = ingest.ingest_book(epub1, series_id="s1", book_order=1, iconn=iconn)
    r2 = ingest.ingest_book(epub2, series_id="s1", book_order=2, iconn=iconn)
    assert r1.book_id != r2.book_id
    assert r1.book_id == "same-title"
    assert r2.book_id == "same-title-2"


# -- idempotency / force -------------------------------------------------


def test_reingest_same_sha256_is_a_noop(tmp_path):
    epub = _simple_epub(tmp_path)
    iconn = _iconn(tmp_path)
    r1 = ingest.ingest_book(epub, series_id="s1", book_order=1, iconn=iconn)
    r2 = ingest.ingest_book(epub, series_id="s1", book_order=1, iconn=iconn)
    assert r1.skipped is False
    assert r2.skipped is True
    assert r1.book_id == r2.book_id

    n_paras = iconn.execute("SELECT COUNT(*) c FROM para WHERE book_id = ?", (r1.book_id,)).fetchone()["c"]
    assert n_paras == r1.paragraphs  # not duplicated

    n_books = iconn.execute("SELECT COUNT(*) c FROM book WHERE sha256 = ?", (r1.sha256,)).fetchone()["c"]
    assert n_books == 1


def test_force_reingest_replaces_rows_without_duplicating(tmp_path):
    epub = _simple_epub(tmp_path)
    iconn = _iconn(tmp_path)
    r1 = ingest.ingest_book(epub, series_id="s1", book_order=1, iconn=iconn)
    r2 = ingest.ingest_book(epub, series_id="s1", book_order=1, iconn=iconn, force=True)
    assert r2.skipped is False

    n_books = iconn.execute("SELECT COUNT(*) c FROM book WHERE sha256 = ?", (r1.sha256,)).fetchone()["c"]
    n_paras = iconn.execute("SELECT COUNT(*) c FROM para WHERE book_id = ?", (r2.book_id,)).fetchone()["c"]
    assert n_books == 1
    assert n_paras == r2.paragraphs


# -- excerpt classification flows through to storage -------------------------


def test_excerpt_chapter_is_tagged_kind_excerpt_in_db(tmp_path):
    epub = _with_excerpt_epub(tmp_path)
    iconn = _iconn(tmp_path)
    result = ingest.ingest_book(epub, series_id="s1", book_order=1, iconn=iconn)
    assert result.excerpt_paragraphs == 2

    ch_kinds = {
        r["label"]: r["kind"]
        for r in iconn.execute("SELECT label, kind FROM chapter WHERE book_id = ?", (result.book_id,))
    }
    assert ch_kinds["Excerpt from Sequel"] == "excerpt"
    assert ch_kinds["Chapter 1"] == "body"
    assert ch_kinds["Chapter 2"] == "body"

    para_kinds = {
        r["kind"] for r in iconn.execute(
            "SELECT kind FROM para WHERE book_id = ? AND chapter_label = ?",
            (result.book_id, "Excerpt from Sequel"),
        )
    }
    assert para_kinds == {"excerpt"}


# -- zero-paragraph chapters ------------------------------------------------


def test_chapter_with_zero_paragraphs_is_skipped_not_stored(tmp_path):
    epub = _make_epub(
        tmp_path / "empty.epub",
        "Empty Chapter Book",
        [
            ("Cover", []),
            ("Chapter 1", ["Real text."]),
        ],
    )
    iconn = _iconn(tmp_path)
    result = ingest.ingest_book(epub, series_id="s1", book_order=1, iconn=iconn)
    # Only the non-empty chapter should have been written.
    assert result.chapters == 1
    labels = {r["label"] for r in iconn.execute("SELECT label FROM chapter WHERE book_id = ?", (result.book_id,))}
    assert labels == {"Chapter 1"}

    manifest = json.loads((paths.book_dir(result.sha256) / "manifest.json").read_text())
    assert "Cover" in manifest["skipped_empty_chapters"]


# -- on-disk artifacts --------------------------------------------------


def test_meta_and_manifest_json_written(tmp_path):
    epub = _simple_epub(tmp_path)
    iconn = _iconn(tmp_path)
    result = ingest.ingest_book(epub, series_id="my-series", book_order=1, iconn=iconn)

    book_dir = paths.book_dir(result.sha256)
    meta = json.loads((book_dir / "meta.json").read_text())
    assert meta["title"] == "Sample Book"
    assert meta["sha256"] == result.sha256
    assert meta["series_id"] == "my-series"
    assert meta["book_order"] == 1

    manifest = json.loads((book_dir / "manifest.json").read_text())
    assert manifest["schema_version"] == db.SCHEMA_VERSION
    assert manifest["sequence_tier"] == "S1"
    assert manifest["label_tier"] == "L1"
    assert manifest["chapters"] == result.chapters
    assert manifest["paragraphs"] == result.paragraphs


def test_digests_dir_created_empty(tmp_path):
    epub = _simple_epub(tmp_path)
    iconn = _iconn(tmp_path)
    result = ingest.ingest_book(epub, series_id="s1", book_order=1, iconn=iconn)
    ddir = paths.digests_dir(result.sha256)
    assert ddir.is_dir()
    assert list(ddir.iterdir()) == []


# -- failure atomicity ---------------------------------------------------


def test_global_seq_overflow_propagates_and_rolls_back(tmp_path, monkeypatch):
    epub = _simple_epub(tmp_path)
    iconn = _iconn(tmp_path)

    call_count = {"n": 0}
    real_global_seq = db.global_seq

    def flaky(book_order, spine_idx, para_idx):
        call_count["n"] += 1
        if call_count["n"] == 3:
            raise ValueError("synthetic failure mid-ingest")
        return real_global_seq(book_order, spine_idx, para_idx)

    monkeypatch.setattr(db, "global_seq", flaky)

    with pytest.raises(ValueError):
        ingest.ingest_book(epub, series_id="s1", book_order=1, iconn=iconn)

    # Nothing from the failed ingest should have landed -- not the book row,
    # not any chapter/para rows.
    assert iconn.execute("SELECT COUNT(*) c FROM book").fetchone()["c"] == 0
    assert iconn.execute("SELECT COUNT(*) c FROM chapter").fetchone()["c"] == 0
    assert iconn.execute("SELECT COUNT(*) c FROM para").fetchone()["c"] == 0
