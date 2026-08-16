"""Tests for booklens.extract.cover: the C-ladder for locating cover art."""

from __future__ import annotations

import zipfile
from pathlib import Path

from booklens.extract.cover import _extension_for, extract_cover

CONTAINER_XML = """<?xml version="1.0"?>
<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>"""

JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"x" * 200  # well over the 100-byte floor
TINY_BYTES = b"tiny"  # under the 100-byte floor


def _build_epub(
    tmp_path: Path,
    *,
    name: str = "book.epub",
    manifest_items: str,
    metadata_extra: str = "",
    spine_body: str = "<p>Chapter text.</p>",
    files: dict[str, bytes] = {},
) -> Path:
    """A minimal single-chapter EPUB with caller-controlled manifest/metadata."""
    path = tmp_path / name
    opf = f"""<?xml version="1.0"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>Cover Test Book</dc:title>
    {metadata_extra}
  </metadata>
  <manifest>
    <item id="ch0" href="text/ch0.xhtml" media-type="application/xhtml+xml"/>
    {manifest_items}
  </manifest>
  <spine>
    <itemref idref="ch0"/>
  </spine>
</package>"""

    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("META-INF/container.xml", CONTAINER_XML)
        zf.writestr("OEBPS/content.opf", opf)
        zf.writestr("OEBPS/text/ch0.xhtml", f"<html><body>{spine_body}</body></html>")
        for zip_path, data in files.items():
            zf.writestr(f"OEBPS/{zip_path}", data)
    return path


# -- C1: EPUB3 properties="cover-image" --------------------------------------


def test_c1_epub3_properties_cover_image(tmp_path):
    epub = _build_epub(
        tmp_path,
        manifest_items=(
            '<item id="cover-img" href="images/cover.jpg" media-type="image/jpeg" '
            'properties="cover-image"/>'
        ),
        files={"images/cover.jpg": JPEG_BYTES},
    )
    cover = extract_cover(epub)
    assert cover is not None
    assert cover.tier == "C1"
    assert cover.media_type == "image/jpeg"
    assert cover.data == JPEG_BYTES


# -- C2: EPUB2 <meta name="cover" content="id"/> ------------------------------


def test_c2_epub2_meta_cover(tmp_path):
    epub = _build_epub(
        tmp_path,
        manifest_items='<item id="myimg" href="art/front.png" media-type="image/png"/>',
        metadata_extra='<meta name="cover" content="myimg"/>',
        files={"art/front.png": JPEG_BYTES},
    )
    cover = extract_cover(epub)
    assert cover is not None
    assert cover.tier == "C2"
    assert cover.media_type == "image/png"


# -- C3: id/path contains "cover" ---------------------------------------------


def test_c3_id_or_path_contains_cover(tmp_path):
    epub = _build_epub(
        tmp_path,
        manifest_items='<item id="cover-thumb" href="images/thumb.jpg" media-type="image/jpeg"/>',
        files={"images/thumb.jpg": JPEG_BYTES},
    )
    cover = extract_cover(epub)
    assert cover is not None
    assert cover.tier == "C3"


def test_c3_prefers_id_match_over_path_match(tmp_path):
    epub = _build_epub(
        tmp_path,
        manifest_items=(
            '<item id="notmatch" href="images/cover-thumb.jpg" media-type="image/jpeg"/>'
            '<item id="cover" href="images/other.jpg" media-type="image/jpeg"/>'
        ),
        files={"images/cover-thumb.jpg": JPEG_BYTES, "images/other.jpg": JPEG_BYTES + b"y"},
    )
    cover = extract_cover(epub)
    assert cover is not None
    assert cover.tier == "C3"
    assert cover.zip_path == "OEBPS/images/other.jpg"


def test_c3_prefers_shortest_path_among_path_matches(tmp_path):
    epub = _build_epub(
        tmp_path,
        manifest_items=(
            '<item id="i1" href="images/cover-thumb-small.jpg" media-type="image/jpeg"/>'
            '<item id="i2" href="cover.jpg" media-type="image/jpeg"/>'
        ),
        files={"images/cover-thumb-small.jpg": JPEG_BYTES, "cover.jpg": JPEG_BYTES + b"y"},
    )
    cover = extract_cover(epub)
    assert cover is not None
    assert cover.tier == "C3"
    assert cover.zip_path == "OEBPS/cover.jpg"


# -- C4: first image in the first spine document -------------------------------


def test_c4_first_spine_image(tmp_path):
    epub = _build_epub(
        tmp_path,
        manifest_items='<item id="pic" href="images/pic.jpg" media-type="image/jpeg"/>',
        spine_body='<img src="../images/pic.jpg"/>',
        files={"images/pic.jpg": JPEG_BYTES},
    )
    cover = extract_cover(epub)
    assert cover is not None
    assert cover.tier == "C4"
    assert cover.zip_path == "OEBPS/images/pic.jpg"


# -- no cover at all -----------------------------------------------------------


def test_no_cover_returns_none_without_raising(tmp_path):
    epub = _build_epub(tmp_path, manifest_items="")
    assert extract_cover(epub) is None


# -- resilience ------------------------------------------------------------


def test_missing_zip_entry_falls_through_to_next_tier(tmp_path):
    # C1 candidate points at a zip entry that doesn't exist; C3 should still
    # find the real cover via the id match.
    epub = _build_epub(
        tmp_path,
        manifest_items=(
            '<item id="ghost" href="images/ghost.jpg" media-type="image/jpeg" '
            'properties="cover-image"/>'
            '<item id="cover" href="images/real.jpg" media-type="image/jpeg"/>'
        ),
        files={"images/real.jpg": JPEG_BYTES},
    )
    cover = extract_cover(epub)
    assert cover is not None
    assert cover.tier == "C3"
    assert cover.zip_path == "OEBPS/images/real.jpg"


def test_tiny_candidate_rejected_ladder_continues(tmp_path):
    epub = _build_epub(
        tmp_path,
        manifest_items=(
            '<item id="broken" href="images/broken.jpg" media-type="image/jpeg" '
            'properties="cover-image"/>'
            '<item id="cover" href="images/real.jpg" media-type="image/jpeg"/>'
        ),
        files={"images/broken.jpg": TINY_BYTES, "images/real.jpg": JPEG_BYTES},
    )
    cover = extract_cover(epub)
    assert cover is not None
    assert cover.tier == "C3"
    assert cover.zip_path == "OEBPS/images/real.jpg"


# -- _extension_for -------------------------------------------------------------


def test_extension_for_maps_known_media_types():
    assert _extension_for("image/jpeg", "x/y.bin") == ".jpg"
    assert _extension_for("image/png", "x/y.bin") == ".png"
    assert _extension_for("image/gif", "x/y.bin") == ".gif"
    assert _extension_for("image/svg+xml", "x/y.bin") == ".svg"
    assert _extension_for("image/webp", "x/y.bin") == ".webp"


def test_extension_for_falls_back_to_path_suffix():
    assert _extension_for("application/octet-stream", "images/cover.jpeg") == ".jpeg"


def test_extension_for_falls_back_to_jpg_when_nothing_known():
    assert _extension_for("application/octet-stream", "images/cover") == ".jpg"
