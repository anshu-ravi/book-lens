"""The S-ladder: which spine documents, in what order.

Tiers are tried in turn and raise to fall through; see `DECISIONS.md`.
"""

from __future__ import annotations

import re
from urllib.parse import unquote

from .types import ExtractionError, MalformedEpubError

# Content-document media types recognised by S2/manifest filtering.
CONTENT_MEDIA_TYPES = {"application/xhtml+xml", "text/html", "text/x-oeb1-document"}

# Zip-entry extensions recognised by S3 (media type is unavailable at that tier).
_CONTENT_EXTENSIONS = (".xhtml", ".html", ".htm")


class TierNotApplicable(ExtractionError):
    """Signals that a tier does not apply, so the ladder should fall through.

    An ExtractionError so calling one tier directly still fails loudly rather
    than returning nothing.
    """


def resolve_href(opf_dir: str, raw_href: str) -> str:
    """Turn an href into a zip path, handling an OPF sitting at the root.

    That case is the one that silently broke every path in an early version.
    """
    href = unquote(raw_href.split("#", 1)[0])
    if not opf_dir:
        return href
    # Resolve "../" without posixpath's willingness to walk above the root.
    parts = (opf_dir + "/" + href).split("/")
    resolved: list[str] = []
    for part in parts:
        if part == "" or part == ".":
            continue
        if part == "..":
            if resolved:
                resolved.pop()
            continue
        resolved.append(part)
    return "/".join(resolved)


def sequence_s1(
    spine_idrefs: list[str],
    manifest: dict[str, tuple[str, str]],
    opf_dir: str,
) -> tuple[str, ...]:
    """Spine order, the authoritative answer when the file has one.

    Keeps `linear="no"` entries; dropping them would lose real content.
    """
    if not spine_idrefs:
        raise TierNotApplicable("S1: spine is empty or absent")
    hrefs: list[str] = []
    for idref in spine_idrefs:
        item = manifest.get(idref)
        if item is None:
            continue
        href, _media_type = item
        hrefs.append(href)
    if not hrefs:
        raise TierNotApplicable("S1: no spine itemref resolved against the manifest")
    return tuple(hrefs)


def sequence_s2(manifest: dict[str, tuple[str, str]]) -> tuple[str, ...]:
    """OPF manifest order, filtered to content documents.

    Used only when the spine is missing or empty. Applicability: at least
    one manifest item has a content media type.
    """
    hrefs = tuple(
        href for href, media_type in manifest.values() if media_type in CONTENT_MEDIA_TYPES
    )
    if not hrefs:
        raise TierNotApplicable("S2: manifest has no content-document items")
    return hrefs


_NUM_RE = re.compile(r"(\d+)")


def _natural_key(name: str):
    """Sort key that orders embedded digits numerically, not lexically."""
    return [int(tok) if tok.isdigit() else tok.lower() for tok in _NUM_RE.split(name)]


def sequence_s3(zip_names: list[str]) -> tuple[str, ...]:
    """Last resort: order by filename when the package tells us nothing."""
    candidates = [
        name
        for name in zip_names
        if not name.startswith("META-INF/")
        and name.lower().endswith(_CONTENT_EXTENSIONS)
    ]
    if not candidates:
        raise TierNotApplicable("S3: no content-like files found in the zip")
    return tuple(sorted(candidates, key=_natural_key))


def resolve_sequence(
    zip_names: list[str],
    opf_dir: str,
    manifest: dict[str, tuple[str, str]],
    spine_idrefs: list[str],
) -> tuple[tuple[str, ...], str]:
    """Run the S-ladder and return (ordered hrefs, tier used).

    Raises MalformedEpubError if every tier is inapplicable -- never guesses
    an ordering.
    """
    try:
        return sequence_s1(spine_idrefs, manifest, opf_dir), "S1"
    except TierNotApplicable:
        pass
    try:
        return sequence_s2(manifest), "S2"
    except TierNotApplicable:
        pass
    try:
        return sequence_s3(zip_names), "S3"
    except TierNotApplicable:
        pass
    raise MalformedEpubError(
        "could not resolve a document sequence: spine, manifest, and zip listing "
        "all failed their applicability checks"
    )
