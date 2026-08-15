"""The L-ladder: chapter boundaries and names.

Tiers are tried in turn and may compose; see `DECISIONS.md` for the evidence
that no single parser works.
"""

from __future__ import annotations

import re
import zipfile

from lxml import etree

from .sequence import resolve_href
from .text import paragraphs_from_html
from .types import Chapter, ExtractionError

NCX_NS = "http://www.daisy.org/z3986/2005/ncx/"
XHTML_NS = "http://www.w3.org/1999/xhtml"
EPUB_OPS_NS = "http://www.idpf.org/2007/ops"

# Each threshold sits between the "tier works" and "tier collapses" clusters
# measured across the dev corpus; see docs/implementation-notes.md.
L1_MIN_COVERAGE = 0.5
L2_MIN_COVERAGE = 0.3
L3_MIN_COVERAGE = 0.2


class TierNotApplicable(ExtractionError):
    """Signals that a tier does not apply, so the ladder should fall through."""


# The Mistborn conversions spell parts as "PART ONE", not "PART 1" or
# "PART I", so word forms have to parse too.
_WORD_NUMBERS = {
    "ONE": "1", "TWO": "2", "THREE": "3", "FOUR": "4", "FIVE": "5",
    "SIX": "6", "SEVEN": "7", "EIGHT": "8", "NINE": "9", "TEN": "10",
    "ELEVEN": "11", "TWELVE": "12", "THIRTEEN": "13", "FOURTEEN": "14",
    "FIFTEEN": "15", "SIXTEEN": "16", "SEVENTEEN": "17", "EIGHTEEN": "18",
    "NINETEEN": "19", "TWENTY": "20",
}
_WORD_NUM_RE = "|".join(_WORD_NUMBERS)

_MARKER_PATTERNS = [
    ("chapter", re.compile(r"^\s*CHAPTER\s+(\d+)\b", re.IGNORECASE)),
    ("part", re.compile(rf"^\s*PART\s+([IVXLCDM]+|\d+|{_WORD_NUM_RE})\b", re.IGNORECASE)),
    ("prologue", re.compile(r"^\s*PROLOGUE\b", re.IGNORECASE)),
    ("epilogue", re.compile(r"^\s*EPILOGUE\b", re.IGNORECASE)),
    ("chapter", re.compile(r"^\s*(\d+)\s*$")),  # bare integer
]


def parse_marker(text: str) -> tuple[str, str] | None:
    """Match `text` against a chapter-marker pattern.

    Returns (kind, normalised_label) where kind is one of "chapter", "part",
    "prologue", "epilogue", or None if nothing matched.
    """
    for kind, pattern in _MARKER_PATTERNS:
        m = pattern.match(text)
        if not m:
            continue
        if kind == "chapter":
            return "chapter", f"Chapter {m.group(1)}"
        if kind == "part":
            number = m.group(1).upper()
            number = _WORD_NUMBERS.get(number, number)
            return "part", f"Part {number}"
        if kind == "prologue":
            return "prologue", "Prologue"
        if kind == "epilogue":
            return "epilogue", "Epilogue"
    return None


def _is_monotonic(values: list[int]) -> bool:
    """Whether a TOC runs in spine order, which a trustworthy one must."""
    return all(a <= b for a, b in zip(values, values[1:]))


def _group_by_markers(markers: dict[int, str], n_docs: int, leading_label: str) -> list[Chapter]:
    """Turn a sparse {spine_idx: label} map into contiguous chapters covering
    every document 0..n_docs-1. Documents before the first marker form a
    leading chapter."""
    sorted_idxs = sorted(markers)
    chapters: list[Chapter] = []
    first = sorted_idxs[0] if sorted_idxs else n_docs
    if first > 0:
        chapters.append(
            Chapter(
                chapter_idx=0,
                label=leading_label,
                part_label=None,
                start_spine_idx=0,
                end_spine_idx=first - 1,
            )
        )
    for i, idx in enumerate(sorted_idxs):
        end = sorted_idxs[i + 1] - 1 if i + 1 < len(sorted_idxs) else n_docs - 1
        chapters.append(
            Chapter(
                chapter_idx=len(chapters),
                label=markers[idx],
                part_label=None,
                start_spine_idx=idx,
                end_spine_idx=end,
            )
        )
    return chapters


def _assign_parts(chapters: list[Chapter], part_map: dict[int, str]) -> list[Chapter]:
    """Assign each chapter the label of the latest part boundary at or before
    its start_spine_idx."""
    if not part_map:
        return chapters
    sorted_idxs = sorted(part_map)
    out = []
    for ch in chapters:
        current = None
        for idx in sorted_idxs:
            if idx <= ch.start_spine_idx:
                current = part_map[idx]
            else:
                break
        out.append(
            Chapter(
                chapter_idx=ch.chapter_idx,
                label=ch.label,
                part_label=current,
                start_spine_idx=ch.start_spine_idx,
                end_spine_idx=ch.end_spine_idx,
            )
        )
    return out


def _compose_bare_part_markers(
    chapters: list[Chapter], empty_spine_idxs: frozenset[int]
) -> list[Chapter]:
    """Turn a chapter that is only a part heading into a boundary.

    Following chapters inherit the part until the next one. A title-only page
    is dropped as a chapter; one with real text stays.
    """
    annotated: list[tuple[Chapter, str | None, bool]] = []
    current_part: str | None = None
    for ch in chapters:
        marker = parse_marker(ch.label)
        is_part_marker = marker is not None and marker[0] == "part"
        if is_part_marker:
            current_part = marker[1]
        part_label = current_part if current_part is not None else ch.part_label
        span = range(ch.start_spine_idx, ch.end_spine_idx + 1)
        has_text = any(idx not in empty_spine_idxs for idx in span)
        drop = is_part_marker and not has_text
        annotated.append((ch, part_label, drop))

    result: list[Chapter] = []
    n = len(annotated)
    i = 0
    while i < n:
        ch, part_label, drop = annotated[i]
        if not drop:
            result.append(
                Chapter(
                    chapter_idx=ch.chapter_idx,
                    label=ch.label,
                    part_label=part_label,
                    start_spine_idx=ch.start_spine_idx,
                    end_spine_idx=ch.end_spine_idx,
                )
            )
            i += 1
            continue
        # Find the next surviving chapter and extend it backward to absorb
        # this (empty) chapter's spine range.
        j = i + 1
        while j < n and annotated[j][2]:
            j += 1
        if j < n:
            nxt_ch, nxt_part, _ = annotated[j]
            annotated[j] = (
                Chapter(
                    chapter_idx=nxt_ch.chapter_idx,
                    label=nxt_ch.label,
                    part_label=nxt_part,
                    start_spine_idx=ch.start_spine_idx,
                    end_spine_idx=nxt_ch.end_spine_idx,
                ),
                nxt_part,
                False,
            )
        elif result:
            # No surviving chapter follows -- extend the previous one forward.
            prev = result[-1]
            result[-1] = Chapter(
                chapter_idx=prev.chapter_idx,
                label=prev.label,
                part_label=prev.part_label,
                start_spine_idx=prev.start_spine_idx,
                end_spine_idx=ch.end_spine_idx,
            )
        else:
            # No neighbour at all (single-chapter book, itself empty) --
            # nothing to fold into; keep it rather than lose the range.
            result.append(
                Chapter(
                    chapter_idx=ch.chapter_idx,
                    label=ch.label,
                    part_label=part_label,
                    start_spine_idx=ch.start_spine_idx,
                    end_spine_idx=ch.end_spine_idx,
                )
            )
        i += 1
    return result


def _renumber(chapters: list[Chapter]) -> tuple[Chapter, ...]:
    """Reindex chapters so their numbering is contiguous from zero."""
    return tuple(
        Chapter(
            chapter_idx=i,
            label=ch.label,
            part_label=ch.part_label,
            start_spine_idx=ch.start_spine_idx,
            end_spine_idx=ch.end_spine_idx,
        )
        for i, ch in enumerate(chapters)
    )


# L1 -- NCX navMap / EPUB3 nav.xhtml


def parse_toc_entries(
    toc_xml_bytes: bytes,
    is_ncx: bool,
    opf_dir: str,
    href_to_spine_idx: dict[str, int],
) -> list[tuple[int, str]]:
    """Parse a NCX navMap or an EPUB3 nav "toc" list into
    [(spine_idx, label), ...] in document (navigation) order. Entries whose
    target href does not match a known spine document are dropped.
    """
    try:
        root = etree.fromstring(toc_xml_bytes)
    except etree.XMLSyntaxError as exc:
        raise TierNotApplicable(f"L1: unreadable TOC document: {exc}") from exc

    entries: list[tuple[int, str]] = []
    if is_ncx:
        ns = {"ncx": NCX_NS}
        for nav_point in root.findall(".//ncx:navPoint", ns):
            content = nav_point.find("ncx:content", ns)
            label_el = nav_point.find("ncx:navLabel/ncx:text", ns)
            if content is None or label_el is None:
                continue
            src = content.get("src")
            if not src:
                continue
            href = resolve_href(opf_dir, src)
            spine_idx = href_to_spine_idx.get(href)
            if spine_idx is None:
                continue
            label = (label_el.text or "").strip()
            if label:
                entries.append((spine_idx, label))
    else:
        ns = {"xhtml": XHTML_NS, "epub": EPUB_OPS_NS}
        toc_nav = None
        for nav in root.findall(".//xhtml:nav", ns):
            if nav.get(f"{{{EPUB_OPS_NS}}}type") == "toc":
                toc_nav = nav
                break
        if toc_nav is None:
            return []
        for a in toc_nav.findall(".//xhtml:a", ns):
            href = a.get("href")
            if not href:
                continue
            resolved = resolve_href(opf_dir, href)
            spine_idx = href_to_spine_idx.get(resolved)
            if spine_idx is None:
                continue
            label = "".join(a.itertext()).strip()
            if label:
                entries.append((spine_idx, label))
    return entries


def l1_chapters(entries: list[tuple[int, str]], n_docs: int) -> list[Chapter]:
    """Full L1 chapter tier. Applicability: coverage above threshold AND
    monotonic in spine order (both required -- Hero of the Ages lists its
    parts before its prologue, so a non-monotonic TOC must be rejected)."""
    if not entries:
        raise TierNotApplicable("L1: no TOC entries resolved to spine documents")
    spine_idxs = [idx for idx, _label in entries]
    coverage = len(set(spine_idxs)) / n_docs if n_docs else 0.0
    if coverage < L1_MIN_COVERAGE:
        raise TierNotApplicable(f"L1: coverage {coverage:.2f} below threshold {L1_MIN_COVERAGE}")
    if not _is_monotonic(spine_idxs):
        raise TierNotApplicable("L1: TOC entries are not monotonic in spine order")
    markers: dict[int, str] = {}
    for idx, label in entries:
        markers.setdefault(idx, label)
    chapters = _group_by_markers(markers, n_docs, leading_label="Front Matter")
    if not chapters:
        raise TierNotApplicable("L1: matched zero chapters")
    return chapters


def l1_part_map(entries: list[tuple[int, str]]) -> dict[int, str]:
    """Extract a sparse {spine_idx: part_label} map from raw TOC entries,
    independent of whether the full L1 chapter tier is applicable. Requires
    at least two part-like, monotonically-ordered entries."""
    part_entries = []
    for idx, label in entries:
        marker = parse_marker(label)
        if marker and marker[0] == "part":
            part_entries.append((idx, marker[1]))
    if len(part_entries) < 2:
        return {}
    spine_idxs = [idx for idx, _label in part_entries]
    if not _is_monotonic(spine_idxs):
        return {}
    part_map: dict[int, str] = {}
    for idx, label in part_entries:
        part_map.setdefault(idx, label)
    return part_map


# L2 -- heading elements


def l2_chapters(doc_headings: dict[int, str], n_docs: int) -> list[Chapter]:
    """doc_headings: spine_idx -> first heading text found in that document."""
    if not doc_headings:
        raise TierNotApplicable("L2: no documents contain heading elements")
    coverage = len(doc_headings) / n_docs if n_docs else 0.0
    if coverage < L2_MIN_COVERAGE:
        raise TierNotApplicable(f"L2: coverage {coverage:.2f} below threshold {L2_MIN_COVERAGE}")
    chapters = _group_by_markers(doc_headings, n_docs, leading_label="Front Matter")
    if not chapters:
        raise TierNotApplicable("L2: matched zero chapters")
    return chapters


def first_heading(html_doc: str) -> str | None:
    """Return the text of the first h1-h4 element in an XHTML document, or
    None. Uses the same body-slicing rules as text.py."""
    from lxml import html as lxml_html

    from .text import _extract_body

    body_html = _extract_body(html_doc)
    try:
        root = lxml_html.fromstring(f"<div>{body_html}</div>")
    except Exception:
        return None
    for el in root.iter():
        tag = el.tag.lower() if isinstance(el.tag, str) else None
        if tag in ("h1", "h2", "h3", "h4"):
            text = "".join(el.itertext()).strip()
            text = re.sub(r"\s+", " ", text)
            if text:
                return text
    return None


# L3 -- first-block marker


def l3_chapters(doc_markers: dict[int, str], n_docs: int) -> list[Chapter]:
    """doc_markers: spine_idx -> normalised marker label for documents whose
    first paragraph matched a chapter-marker pattern."""
    if not doc_markers:
        raise TierNotApplicable("L3: no documents have a first-block marker")
    coverage = len(doc_markers) / n_docs if n_docs else 0.0
    if coverage < L3_MIN_COVERAGE:
        raise TierNotApplicable(f"L3: coverage {coverage:.2f} below threshold {L3_MIN_COVERAGE}")
    chapters = _group_by_markers(doc_markers, n_docs, leading_label="Front Matter")
    if not chapters:
        raise TierNotApplicable("L3: matched zero chapters")
    return chapters


def first_block_marker(html_doc: str) -> str | None:
    """Return the normalised marker label for a document's first paragraph,
    or None if it doesn't match a chapter-marker pattern."""
    paragraphs = paragraphs_from_html(html_doc)
    if not paragraphs:
        return None
    marker = parse_marker(paragraphs[0])
    if marker is None:
        return None
    return marker[1]


# L4 -- synthetic, always succeeds


def l4_chapters(n_docs: int) -> list[Chapter]:
    """Synthesise one chapter per document, the tier that always succeeds."""
    if n_docs <= 0:
        raise TierNotApplicable("L4: zero documents to label")
    return [
        Chapter(
            chapter_idx=i,
            label=f"Document {i}",
            part_label=None,
            start_spine_idx=i,
            end_spine_idx=i,
        )
        for i in range(n_docs)
    ]


# Driver: run the ladder, compose parts, return (chapters, label_tier)


def _validate_full_coverage(chapters: tuple[Chapter, ...], n_docs: int) -> None:
    """Assert every document lands in exactly one chapter, loudly if not."""
    covered: set[int] = set()
    for ch in chapters:
        span = range(ch.start_spine_idx, ch.end_spine_idx + 1)
        overlap = covered & set(span)
        if overlap:
            raise ExtractionError(f"chapter boundaries overlap at spine_idx {sorted(overlap)}")
        covered.update(span)
    if covered != set(range(n_docs)):
        missing = sorted(set(range(n_docs)) - covered)
        raise ExtractionError(f"chapters do not cover every spine document: missing {missing}")


def _find_toc_source(
    zf: zipfile.ZipFile, manifest: dict[str, tuple[str, str]]
) -> tuple[bytes, bool] | None:
    """Locate an NCX or EPUB3 nav document in the manifest and return its
    (bytes, is_ncx) if present and readable, else None."""
    for href, media_type in manifest.values():
        if media_type == "application/x-dtbncx+xml" and href in zf.namelist():
            return zf.read(href), True
    # Best-effort EPUB3 nav detection: the manifest tuple doesn't carry
    # `properties`, so fall back to the conventional filename.
    for href, media_type in manifest.values():
        if media_type == "application/xhtml+xml" and href.lower().endswith("nav.xhtml"):
            if href in zf.namelist():
                return zf.read(href), False
    return None


def resolve_labels(
    zf: zipfile.ZipFile,
    opf_dir: str,
    manifest: dict[str, tuple[str, str]],
    hrefs: tuple[str, ...],
    empty_spine_idxs: frozenset[int] = frozenset(),
) -> tuple[tuple[Chapter, ...], str]:
    """Walk the ladder until a tier resolves, reporting which one won.

    A composed result like "L1+L3" means L1 supplied parts over another
    tier's chapters.
    """
    n_docs = len(hrefs)
    href_to_spine_idx = {href: i for i, href in enumerate(hrefs)}

    toc_entries: list[tuple[int, str]] = []
    toc_source = _find_toc_source(zf, manifest)
    if toc_source is not None:
        toc_bytes, is_ncx = toc_source
        try:
            toc_entries = parse_toc_entries(toc_bytes, is_ncx, opf_dir, href_to_spine_idx)
        except TierNotApplicable:
            toc_entries = []

    base_tier: str
    chapters: list[Chapter]
    try:
        chapters = l1_chapters(toc_entries, n_docs)
        base_tier = "L1"
    except TierNotApplicable:
        doc_headings: dict[int, str] = {}
        for spine_idx, href in enumerate(hrefs):
            heading = first_heading(zf.read(href).decode("utf-8", errors="replace"))
            if heading:
                doc_headings[spine_idx] = heading
        try:
            chapters = l2_chapters(doc_headings, n_docs)
            base_tier = "L2"
        except TierNotApplicable:
            doc_markers: dict[int, str] = {}
            for spine_idx, href in enumerate(hrefs):
                marker = first_block_marker(zf.read(href).decode("utf-8", errors="replace"))
                if marker:
                    doc_markers[spine_idx] = marker
            try:
                chapters = l3_chapters(doc_markers, n_docs)
                base_tier = "L3"
            except TierNotApplicable:
                chapters = l4_chapters(n_docs)
                base_tier = "L4"

    label_tier = base_tier
    if base_tier != "L1" and toc_entries:
        part_map = l1_part_map(toc_entries)
        if part_map:
            chapters = _assign_parts(chapters, part_map)
            label_tier = f"L1+{base_tier}"
    elif base_tier == "L1":
        # L1 chapters can include part-title pages of their own, which the
        # path above misses since it only runs when another tier wins.
        chapters = _compose_bare_part_markers(chapters, empty_spine_idxs)

    result = _renumber(chapters)
    _validate_full_coverage(result, n_docs)
    return result, label_tier
