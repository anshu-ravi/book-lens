"""The SC-ladder: read a series/collection hint out of an EPUB's OPF metadata, if present."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .epub import OPF_NS, _find_opf_path, _parse_opf, _read_zip


@dataclass(frozen=True)
class SeriesHint:
    """A series name, and its position within it if the EPUB says so."""

    name: str
    position: int | None
    tier: str


def _sc1_epub3_collection(metadata_el) -> SeriesHint | None:
    """EPUB3 `belongs-to-collection`, with a `refines`d `group-position` giving the order."""
    for meta in metadata_el.findall(f"{{{OPF_NS}}}meta"):
        if meta.get("property") != "belongs-to-collection":
            continue
        name = (meta.text or "").strip()
        if not name:
            continue
        meta_id = meta.get("id")
        position = None
        if meta_id:
            for refine in metadata_el.findall(f"{{{OPF_NS}}}meta"):
                if refine.get("refines") == f"#{meta_id}" and refine.get("property") == "group-position":
                    try:
                        position = int((refine.text or "").strip())
                    except ValueError:
                        position = None
        return SeriesHint(name=name, position=position, tier="SC1")
    return None


def _sc2_calibre_series(metadata_el) -> SeriesHint | None:
    """Calibre's `calibre:series` / `calibre:series_index` extension metadata."""
    name = None
    position = None
    for meta in metadata_el.findall(f"{{{OPF_NS}}}meta"):
        if meta.get("name") == "calibre:series":
            content = (meta.get("content") or "").strip()
            name = content or None
        elif meta.get("name") == "calibre:series_index":
            try:
                position = int(float(meta.get("content")))
            except (TypeError, ValueError):
                position = None
    if name:
        return SeriesHint(name=name, position=position, tier="SC2")
    return None


def read_series_hint(path: str | Path) -> SeriesHint | None:
    """Run the series-collection ladder against an EPUB, returning None if no tier matches."""
    path = Path(path)
    _data, zf = _read_zip(path)
    opf_path = _find_opf_path(zf)
    opf_root = _parse_opf(zf, opf_path)
    metadata_el = opf_root.find(f"{{{OPF_NS}}}metadata")
    if metadata_el is None:
        return None

    hint = _sc1_epub3_collection(metadata_el)
    if hint is not None:
        return hint
    return _sc2_calibre_series(metadata_el)
