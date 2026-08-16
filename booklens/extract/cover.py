"""The C-ladder: locate a book's cover image inside its EPUB, if it has one."""

from __future__ import annotations

import zipfile
from dataclasses import dataclass
from pathlib import Path

from lxml import html as lxml_html

from .epub import OPF_NS, _dirname, _find_opf_path, _parse_opf, _read_manifest, _read_zip
from .sequence import resolve_href
from .text import _extract_body

MIN_COVER_BYTES = 100

_MEDIA_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/svg+xml": ".svg",
    "image/webp": ".webp",
}


@dataclass(frozen=True)
class CoverImage:
    """A cover image resolved out of an EPUB, with the tier that found it."""

    data: bytes
    media_type: str
    zip_path: str
    tier: str


def _extension_for(media_type: str, zip_path: str) -> str:
    """Map a media type to a file extension, falling back to the zip path's suffix."""
    ext = _MEDIA_EXTENSIONS.get(media_type)
    if ext:
        return ext
    suffix = Path(zip_path).suffix
    return suffix if suffix else ".jpg"


def _read_manifest_properties(opf_root, opf_dir: str) -> dict[str, tuple[str, str, str]]:
    """Map each manifest id to (zip path, media type, properties), for C1/C4.

    A sibling of `epub._read_manifest`, which drops `properties` -- re-walking
    here avoids changing that function's return type and every caller.
    """
    out: dict[str, tuple[str, str, str]] = {}
    manifest_el = opf_root.find(f"{{{OPF_NS}}}manifest")
    if manifest_el is None:
        return out
    for item in manifest_el.findall(f"{{{OPF_NS}}}item"):
        item_id = item.get("id")
        href = item.get("href")
        if not item_id or not href:
            continue
        media_type = item.get("media-type") or ""
        properties = item.get("properties") or ""
        out[item_id] = (resolve_href(opf_dir, href), media_type, properties)
    return out


def _load_candidate(zf: zipfile.ZipFile, zip_path: str, media_type: str, tier: str) -> CoverImage | None:
    """Read the candidate's bytes, rejecting a too-small or missing entry."""
    try:
        data = zf.read(zip_path)
    except KeyError:
        return None
    if len(data) < MIN_COVER_BYTES:
        return None
    return CoverImage(data=data, media_type=media_type, zip_path=zip_path, tier=tier)


def _c1_epub3_properties(zf: zipfile.ZipFile, items: dict[str, tuple[str, str, str]]) -> CoverImage | None:
    """EPUB3: a manifest item whose `properties` contains the token `cover-image`."""
    for zip_path, media_type, properties in items.values():
        if "cover-image" in properties.split():
            candidate = _load_candidate(zf, zip_path, media_type, "C1")
            if candidate is not None:
                return candidate
    return None


def _c2_epub2_meta_cover(
    zf: zipfile.ZipFile, opf_root, manifest: dict[str, tuple[str, str]]
) -> CoverImage | None:
    """EPUB2: `<meta name="cover" content="{item-id}"/>` resolved through the manifest."""
    metadata_el = opf_root.find(f"{{{OPF_NS}}}metadata")
    if metadata_el is None:
        return None
    for meta in metadata_el.findall(f"{{{OPF_NS}}}meta"):
        if meta.get("name") != "cover":
            continue
        content_id = meta.get("content")
        if not content_id:
            continue
        item = manifest.get(content_id)
        if item is None:
            continue
        zip_path, media_type = item
        if not media_type.startswith("image/"):
            continue
        candidate = _load_candidate(zf, zip_path, media_type, "C2")
        if candidate is not None:
            return candidate
    return None


def _c3_id_or_path_contains_cover(
    zf: zipfile.ZipFile, manifest: dict[str, tuple[str, str]]
) -> CoverImage | None:
    """A manifest image item whose id or path contains "cover" (case-insensitive).

    Prefers an id match over a path match; among path matches prefers the
    shortest path.
    """
    for item_id, (zip_path, media_type) in manifest.items():
        if not media_type.startswith("image/"):
            continue
        if "cover" in item_id.lower():
            candidate = _load_candidate(zf, zip_path, media_type, "C3")
            if candidate is not None:
                return candidate

    path_candidates = [
        (zip_path, media_type)
        for zip_path, media_type in manifest.values()
        if media_type.startswith("image/") and "cover" in zip_path.lower()
    ]
    for zip_path, media_type in sorted(path_candidates, key=lambda pair: len(pair[0])):
        candidate = _load_candidate(zf, zip_path, media_type, "C3")
        if candidate is not None:
            return candidate
    return None


def _first_image_href(html_doc: str, doc_dir: str) -> str | None:
    """First `<img src>` or SVG `<image xlink:href>` in a document's body, resolved to a zip path."""
    body_html = _extract_body(html_doc)
    try:
        root = lxml_html.fromstring(f"<div>{body_html}</div>")
    except Exception:
        return None
    xlink_ns = "{http://www.w3.org/1999/xlink}href"
    for el in root.iter():
        tag = el.tag.lower() if isinstance(el.tag, str) else None
        if tag == "img" and el.get("src"):
            return resolve_href(doc_dir, el.get("src"))
        if tag == "image":
            href = el.get(xlink_ns) or el.get("href")
            if href:
                return resolve_href(doc_dir, href)
    return None


def _c4_first_spine_image(
    zf: zipfile.ZipFile, opf_dir: str, manifest: dict[str, tuple[str, str]], spine_href: str
) -> CoverImage | None:
    """The first image referenced by the first spine document, if it's a manifest image item."""
    try:
        raw = zf.read(spine_href)
    except KeyError:
        return None
    html_doc = raw.decode("utf-8", errors="replace")
    doc_dir = _dirname(spine_href)
    image_href = _first_image_href(html_doc, doc_dir)
    if image_href is None:
        return None

    for zip_path, media_type in manifest.values():
        if zip_path == image_href and media_type.startswith("image/"):
            return _load_candidate(zf, zip_path, media_type, "C4")
    return None


def extract_cover(path: str | Path) -> CoverImage | None:
    """Run the cover ladder against an EPUB, returning None if no tier matches.

    A book with no cover art is a legitimate absence, not a parser bug -- the
    one deliberate exception to "extractors fail loudly" in this codebase.
    """
    path = Path(path)
    _data, zf = _read_zip(path)

    opf_path = _find_opf_path(zf)
    opf_dir = _dirname(opf_path)
    opf_root = _parse_opf(zf, opf_path)

    manifest = _read_manifest(opf_root, opf_dir)
    manifest_props = _read_manifest_properties(opf_root, opf_dir)

    candidate = _c1_epub3_properties(zf, manifest_props)
    if candidate is not None:
        return candidate

    candidate = _c2_epub2_meta_cover(zf, opf_root, manifest)
    if candidate is not None:
        return candidate

    candidate = _c3_id_or_path_contains_cover(zf, manifest)
    if candidate is not None:
        return candidate

    spine_el = opf_root.find(f"{{{OPF_NS}}}spine")
    if spine_el is not None:
        for itemref in spine_el.findall(f"{{{OPF_NS}}}itemref"):
            idref = itemref.get("idref")
            item = manifest.get(idref) if idref else None
            if item is None:
                continue
            spine_href, _media_type = item
            candidate = _c4_first_spine_image(zf, opf_dir, manifest, spine_href)
            if candidate is not None:
                return candidate
            break

    return None
