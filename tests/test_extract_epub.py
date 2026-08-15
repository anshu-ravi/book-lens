"""Integration tests for booklens.extract.epub / extract_book, against the real
dev-corpus EPUBs and synthetic DRM fixtures."""

import zipfile

import pytest

from booklens.extract import BookExtraction, DrmProtectedError, extract_book

# Measured spine-document counts (DECISIONS.md section 3), used as a
# regression check: a future change that silently drops or duplicates
# documents should fail this suite.
EXPECTED_SPINE_COUNTS = {
    "red-rising": 63,
    "golden-son": 71,
    "final-empire": 59,
    "well-of-ascension": 149,
    "hero-of-ages": 103,
    "morning-star": 97,
}

# Label tier each book actually resolves to. A future parser change that
# silently downgrades a book (e.g. to L4) must fail this suite.
EXPECTED_LABEL_TIERS = {
    "red-rising": "L1",
    "golden-son": "L1",
    "final-empire": "L1",
    "well-of-ascension": "L1+L3",
    "hero-of-ages": "L1+L4",
    "morning-star": "L1",
}


def _assert_well_formed(book: BookExtraction) -> None:
    assert book.documents, "extract_book must never return zero documents"
    assert book.chapters, "extract_book must never return zero chapters"

    covered: set[int] = set()
    for ch in book.chapters:
        span = range(ch.start_spine_idx, ch.end_spine_idx + 1)
        overlap = covered & set(span)
        assert not overlap, f"chapters overlap at spine_idx {sorted(overlap)}"
        covered.update(span)
    assert covered == set(range(len(book.documents))), (
        "every spine document must belong to exactly one chapter"
    )

    for doc in book.documents:
        idxs = [p.para_idx for p in doc.paragraphs]
        assert idxs == list(range(len(idxs))), f"para_idx not contiguous in {doc.href}"
        assert doc.spine_idx < 1000
        for p in doc.paragraphs:
            assert p.para_idx < 1000
            assert p.text != "", "paragraphs must never be empty"
            assert "\n" not in p.text, "flattening must not leave stray newlines"


@pytest.mark.parametrize("slug", list(EXPECTED_SPINE_COUNTS))
def test_extract_book_succeeds_on_full_corpus(corpus, slug):
    if slug not in corpus:
        pytest.skip(f"{slug} not present in uploads/")
    book = extract_book(corpus[slug])
    _assert_well_formed(book)


@pytest.mark.parametrize("slug,expected_count", list(EXPECTED_SPINE_COUNTS.items()))
def test_measured_spine_counts(corpus, slug, expected_count):
    if slug not in corpus:
        pytest.skip(f"{slug} not present in uploads/")
    book = extract_book(corpus[slug])
    assert len(book.documents) == expected_count


@pytest.mark.parametrize("slug,expected_tier", list(EXPECTED_LABEL_TIERS.items()))
def test_label_tier_per_book(corpus, slug, expected_tier):
    if slug not in corpus:
        pytest.skip(f"{slug} not present in uploads/")
    book = extract_book(corpus[slug])
    assert book.label_tier == expected_tier


def test_all_corpus_books_use_s1_spine_sequence(corpus):
    for slug, path in corpus.items():
        book = extract_book(path)
        assert book.sequence_tier == "S1", f"{slug} unexpectedly fell off the spine tier"


def test_golden_son_font_only_encryption_does_not_raise(corpus):
    if "golden-son" not in corpus:
        pytest.skip("golden-son not present in uploads/")
    # Golden Son ships a real encryption.xml whose CipherReferences are all
    # fonts/*.ttf. This must extract cleanly, not be rejected as DRM.
    book = extract_book(corpus["golden-son"])
    _assert_well_formed(book)


def test_golden_son_opf_at_zip_root_resolves_documents(corpus):
    # Regression test for the rsplit('/', 1)[0] path bug: content.opf sits
    # at the zip root in Golden Son, so opf_dir must resolve to "".
    if "golden-son" not in corpus:
        pytest.skip("golden-son not present in uploads/")
    book = extract_book(corpus["golden-son"])
    assert len(book.documents) > 0


def test_drm_encrypted_content_document_raises(tmp_path):
    epub_path = tmp_path / "synthetic-drm.epub"
    with zipfile.ZipFile(epub_path, "w") as zf:
        zf.writestr(
            "META-INF/container.xml",
            """<?xml version="1.0"?>
<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>""",
        )
        zf.writestr(
            "META-INF/encryption.xml",
            """<?xml version="1.0"?>
<encryption xmlns="urn:oasis:names:tc:opendocument:xmlns:container"
            xmlns:enc="http://www.w3.org/2001/04/xmlenc#">
  <enc:EncryptedData>
    <enc:EncryptionMethod Algorithm="http://www.w3.org/2001/04/xmlenc#aes256-cbc"/>
    <enc:CipherData><enc:CipherReference URI="OEBPS/text/ch1.xhtml"/></enc:CipherData>
  </enc:EncryptedData>
</encryption>""",
        )
        zf.writestr(
            "OEBPS/content.opf",
            """<?xml version="1.0"?>
<package xmlns="http://www.idpf.org/2007/opf" version="2.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>Synthetic DRM Book</dc:title>
  </metadata>
  <manifest>
    <item id="ch1" href="text/ch1.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine>
    <itemref idref="ch1"/>
  </spine>
</package>""",
        )
        zf.writestr("OEBPS/text/ch1.xhtml", "<html><body><p>Encrypted gibberish.</p></body></html>")

    with pytest.raises(DrmProtectedError):
        extract_book(epub_path)


def test_drm_font_only_encryption_synthetic_does_not_raise(tmp_path):
    epub_path = tmp_path / "synthetic-font-drm.epub"
    with zipfile.ZipFile(epub_path, "w") as zf:
        zf.writestr(
            "META-INF/container.xml",
            """<?xml version="1.0"?>
<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>""",
        )
        zf.writestr(
            "META-INF/encryption.xml",
            """<?xml version="1.0"?>
<encryption xmlns="urn:oasis:names:tc:opendocument:xmlns:container"
            xmlns:enc="http://www.w3.org/2001/04/xmlenc#">
  <enc:EncryptedData>
    <enc:EncryptionMethod Algorithm="http://ns.adobe.com/pdf/enc#RC"/>
    <enc:CipherData><enc:CipherReference URI="OEBPS/fonts/font1.ttf"/></enc:CipherData>
  </enc:EncryptedData>
</encryption>""",
        )
        zf.writestr(
            "OEBPS/content.opf",
            """<?xml version="1.0"?>
<package xmlns="http://www.idpf.org/2007/opf" version="2.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>Synthetic Font-Only-DRM Book</dc:title>
  </metadata>
  <manifest>
    <item id="ch1" href="text/ch1.xhtml" media-type="application/xhtml+xml"/>
    <item id="font1" href="fonts/font1.ttf" media-type="application/x-font-truetype"/>
  </manifest>
  <spine>
    <itemref idref="ch1"/>
  </spine>
</package>""",
        )
        zf.writestr("OEBPS/text/ch1.xhtml", "<html><body><p>Perfectly readable text.</p></body></html>")

    book = extract_book(epub_path)
    assert len(book.documents) == 1
    assert book.documents[0].paragraphs[0].text == "Perfectly readable text."
