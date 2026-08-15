"""EPUB container/OPF handling, DRM detection, and the public `extract_book` entry point."""

from __future__ import annotations

import hashlib
import io
import zipfile
from pathlib import Path
from urllib.parse import unquote

from lxml import etree

from .labels import resolve_labels
from .sequence import resolve_href, resolve_sequence
from .text import paragraphs_from_html
from .types import BookExtraction, Document, DrmProtectedError, MalformedEpubError, Paragraph

CONTAINER_NS = "urn:oasis:names:tc:opendocument:xmlns:container"
OPF_NS = "http://www.idpf.org/2007/opf"
DC_NS = "http://purl.org/dc/elements/1.1/"
ENC_NS = "http://www.w3.org/2001/04/xmlenc#"

# global_seq packs these into fixed digit ranges, so an overflow would
# collide with the neighbouring document rather than just look wrong.
MAX_SPINE_IDX = 1000
MAX_PARA_IDX = 1000


def _dirname(zip_path: str) -> str:
    """Directory of a zip entry path. Guards the no-separator case: when the
    OPF sits at the zip root, `path.rsplit('/', 1)[0]` would otherwise
    return the filename rather than ''."""
    if "/" in zip_path:
        return zip_path.rsplit("/", 1)[0]
    return ""


def _read_zip(path: Path) -> tuple[bytes, zipfile.ZipFile]:
    """Open the EPUB and hash its bytes, which content-addresses the edition."""
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise MalformedEpubError(f"cannot read EPUB file {path}: {exc}") from exc
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise MalformedEpubError(f"{path} is not a valid zip/EPUB archive: {exc}") from exc
    return data, zf


def _find_opf_path(zf: zipfile.ZipFile) -> str:
    """Locate the package document the container points at."""
    try:
        container_bytes = zf.read("META-INF/container.xml")
    except KeyError as exc:
        raise MalformedEpubError("EPUB is missing META-INF/container.xml") from exc
    try:
        root = etree.fromstring(container_bytes)
    except etree.XMLSyntaxError as exc:
        raise MalformedEpubError(f"unreadable META-INF/container.xml: {exc}") from exc
    rootfile = root.find(f".//{{{CONTAINER_NS}}}rootfile")
    if rootfile is None:
        raise MalformedEpubError("META-INF/container.xml has no <rootfile> entry")
    full_path = rootfile.get("full-path")
    if not full_path:
        raise MalformedEpubError("META-INF/container.xml <rootfile> is missing full-path")
    return full_path


def _parse_opf(zf: zipfile.ZipFile, opf_path: str):
    """Parse the package document with a real XML parser, never regex."""
    try:
        opf_bytes = zf.read(opf_path)
    except KeyError as exc:
        raise MalformedEpubError(f"OPF file {opf_path} referenced but not present in zip") from exc
    try:
        return etree.fromstring(opf_bytes)
    except etree.XMLSyntaxError as exc:
        raise MalformedEpubError(f"unreadable OPF document {opf_path}: {exc}") from exc


def _read_metadata(opf_root) -> tuple[str, str | None]:
    """Pull title and author out of the package metadata."""
    title_el = opf_root.find(f".//{{{DC_NS}}}title")
    title = (title_el.text or "").strip() if title_el is not None and title_el.text else "Untitled"
    author_el = opf_root.find(f".//{{{DC_NS}}}creator")
    author = (author_el.text or "").strip() if author_el is not None and author_el.text else None
    return title, (author or None)


def _read_manifest(opf_root, opf_dir: str) -> dict[str, tuple[str, str]]:
    """Map each manifest id to its resolved zip path and media type."""
    manifest: dict[str, tuple[str, str]] = {}
    manifest_el = opf_root.find(f"{{{OPF_NS}}}manifest")
    if manifest_el is None:
        return manifest
    for item in manifest_el.findall(f"{{{OPF_NS}}}item"):
        item_id = item.get("id")
        href = item.get("href")
        media_type = item.get("media-type") or ""
        if not item_id or not href:
            continue
        manifest[item_id] = (resolve_href(opf_dir, href), media_type)
    return manifest


def _read_spine(opf_root) -> list[str]:
    """Read the spine's itemref ids in document order."""
    spine_el = opf_root.find(f"{{{OPF_NS}}}spine")
    if spine_el is None:
        return []
    idrefs = []
    for itemref in spine_el.findall(f"{{{OPF_NS}}}itemref"):
        idref = itemref.get("idref")
        if idref:
            idrefs.append(idref)
    return idrefs


def _check_drm(zf: zipfile.ZipFile, hrefs: tuple[str, ...]) -> None:
    """Raise DrmProtectedError only if a spine (content) document is
    encrypted. A font-only encryption.xml (Golden Son) must extract fine."""
    if "META-INF/encryption.xml" not in zf.namelist():
        return
    try:
        root = etree.fromstring(zf.read("META-INF/encryption.xml"))
    except etree.XMLSyntaxError as exc:
        raise MalformedEpubError(f"unreadable META-INF/encryption.xml: {exc}") from exc
    encrypted_paths: set[str] = set()
    for ref in root.findall(f".//{{{ENC_NS}}}CipherReference"):
        uri = ref.get("URI")
        if uri:
            encrypted_paths.add(unquote(uri.split("#", 1)[0]))
    content_set = set(hrefs)
    encrypted_content = encrypted_paths & content_set
    if encrypted_content:
        raise DrmProtectedError(
            "EPUB has DRM-encrypted content document(s), cannot extract: "
            f"{sorted(encrypted_content)}"
        )


def _build_documents(zf: zipfile.ZipFile, hrefs: tuple[str, ...]) -> tuple[Document, ...]:
    """Extract paragraphs from every spine document, in order."""
    documents = []
    for spine_idx, href in enumerate(hrefs):
        if spine_idx >= MAX_SPINE_IDX:
            raise MalformedEpubError(
                f"spine_idx {spine_idx} exceeds the supported bound (<{MAX_SPINE_IDX}); "
                "global_seq computation would collide"
            )
        try:
            raw = zf.read(href)
        except KeyError as exc:
            raise MalformedEpubError(f"spine document {href} referenced but not present in zip") from exc
        html_doc = raw.decode("utf-8", errors="replace")
        texts = paragraphs_from_html(html_doc)
        paragraphs = []
        for para_idx, text in enumerate(texts):
            if para_idx >= MAX_PARA_IDX:
                raise MalformedEpubError(
                    f"para_idx {para_idx} in spine document {spine_idx} ({href}) exceeds the "
                    f"supported bound (<{MAX_PARA_IDX}); global_seq computation would collide"
                )
            paragraphs.append(Paragraph(spine_idx=spine_idx, para_idx=para_idx, text=text))
        documents.append(Document(spine_idx=spine_idx, href=href, paragraphs=tuple(paragraphs)))
    return tuple(documents)


def extract_book(path: str | Path) -> BookExtraction:
    """Extract a `BookExtraction` from an EPUB file. Pure function: does not
    modify, move, or write next to the source file."""
    path = Path(path)
    data, zf = _read_zip(path)
    sha256 = hashlib.sha256(data).hexdigest()

    opf_path = _find_opf_path(zf)
    opf_dir = _dirname(opf_path)
    opf_root = _parse_opf(zf, opf_path)

    title, author = _read_metadata(opf_root)
    manifest = _read_manifest(opf_root, opf_dir)
    spine_idrefs = _read_spine(opf_root)

    hrefs, sequence_tier = resolve_sequence(zf.namelist(), opf_dir, manifest, spine_idrefs)

    _check_drm(zf, hrefs)

    documents = _build_documents(zf, hrefs)
    empty_spine_idxs = frozenset(d.spine_idx for d in documents if not d.paragraphs)
    chapters, label_tier = resolve_labels(zf, opf_dir, manifest, hrefs, empty_spine_idxs)

    return BookExtraction(
        title=title,
        author=author,
        source_path=str(path),
        sha256=sha256,
        documents=documents,
        chapters=chapters,
        sequence_tier=sequence_tier,
        label_tier=label_tier,
    )
