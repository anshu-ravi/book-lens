"""Unit tests for booklens.extract.labels: the L-ladder, against synthetic inputs."""

import pytest

from booklens.extract.labels import (
    TierNotApplicable,
    l1_chapters,
    l1_part_map,
    l2_chapters,
    l3_chapters,
    l4_chapters,
    parse_marker,
    parse_toc_entries,
)


# --- marker parsing -----------------------------------------------------


@pytest.mark.parametrize(
    "text,expected",
    [
        ("CHAPTER 12", ("chapter", "Chapter 12")),
        ("Chapter 3", ("chapter", "Chapter 3")),
        ("42", ("chapter", "Chapter 42")),
        ("PROLOGUE", ("prologue", "Prologue")),
        ("prologue", ("prologue", "Prologue")),
        ("EPILOGUE", ("epilogue", "Epilogue")),
        ("PART III", ("part", "Part III")),
        ("PART 3", ("part", "Part 3")),
        ("PART THREE", ("part", "Part 3")),
        ("not a marker at all", None),
    ],
)
def test_parse_marker(text, expected):
    assert parse_marker(text) == expected


def test_parse_marker_word_boundary_rejects_concatenated_text():
    # Real-file gotcha: some NCX labels concatenate without a separator
    # ("PART ONELEGACY OF THE SURVIVOR"). That must NOT match as "Part 1".
    assert parse_marker("PART ONELEGACY OF THE SURVIVOR") is None
    assert parse_marker("PART ONE: Legacy of the Survivor") == ("part", "Part 1")


# --- L1: NCX / nav -----------------------------------------------------


def test_l1_accepts_high_coverage_monotonic_toc():
    entries = [(0, "Title"), (1, "Prologue"), (2, "Chapter 1"), (3, "Chapter 2")]
    chapters = l1_chapters(entries, n_docs=4)
    assert chapters[0].start_spine_idx == 0
    assert chapters[-1].end_spine_idx == 3
    # every doc covered
    covered = set()
    for c in chapters:
        covered.update(range(c.start_spine_idx, c.end_spine_idx + 1))
    assert covered == set(range(4))


def test_l1_rejects_low_coverage_toc():
    entries = [(0, "Title"), (50, "Somewhere")]
    with pytest.raises(TierNotApplicable):
        l1_chapters(entries, n_docs=100)


def test_l1_rejects_non_monotonic_toc():
    # Hero of the Ages shape: parts listed before the prologue, i.e. TOC
    # entries are not in ascending spine order. Coverage alone would pass
    # here, so this specifically exercises the monotonicity check.
    entries = [(idx, f"entry{idx}") for idx in range(10)]
    entries[3], entries[7] = entries[7], entries[3]  # break monotonicity
    with pytest.raises(TierNotApplicable):
        l1_chapters(entries, n_docs=10)


def test_l1_raises_on_zero_entries():
    with pytest.raises(TierNotApplicable):
        l1_chapters([], n_docs=10)


def test_l1_part_map_requires_monotonic_parts():
    entries = [(0, "PART ONE"), (5, "Chapter 1"), (10, "PART TWO")]
    assert l1_part_map(entries) == {0: "Part 1", 10: "Part 2"}


def test_l1_part_map_empty_when_non_monotonic():
    entries = [(10, "PART TWO"), (0, "PART ONE")]
    assert l1_part_map(entries) == {}


def test_l1_part_map_empty_when_fewer_than_two_parts():
    entries = [(0, "PART ONE"), (5, "Chapter 1")]
    assert l1_part_map(entries) == {}


# --- L2: headings --------------------------------------------------------


def test_l2_accepts_high_coverage_headings():
    headings = {i: f"Chapter {i}" for i in range(8)}
    chapters = l2_chapters(headings, n_docs=10)
    covered = set()
    for c in chapters:
        covered.update(range(c.start_spine_idx, c.end_spine_idx + 1))
    assert covered == set(range(10))


def test_l2_rejects_low_coverage():
    with pytest.raises(TierNotApplicable):
        l2_chapters({0: "Chapter 1"}, n_docs=20)


def test_l2_raises_on_zero_headings():
    with pytest.raises(TierNotApplicable):
        l2_chapters({}, n_docs=10)


# --- L3: first-block marker ------------------------------------------------


def test_l3_accepts_high_coverage_markers():
    markers = {i: f"Chapter {i}" for i in range(0, 10, 2)}
    chapters = l3_chapters(markers, n_docs=10)
    covered = set()
    for c in chapters:
        covered.update(range(c.start_spine_idx, c.end_spine_idx + 1))
    assert covered == set(range(10))


def test_l3_rejects_low_coverage():
    with pytest.raises(TierNotApplicable):
        l3_chapters({0: "Chapter 1"}, n_docs=20)


def test_l3_raises_on_zero_markers():
    with pytest.raises(TierNotApplicable):
        l3_chapters({}, n_docs=10)


def test_l3_groups_documents_between_markers():
    # Well of Ascension shape: multiple documents per chapter.
    markers = {0: "Chapter 1", 3: "Chapter 2"}
    chapters = l3_chapters(markers, n_docs=6)
    ch1 = [c for c in chapters if c.label == "Chapter 1"][0]
    ch2 = [c for c in chapters if c.label == "Chapter 2"][0]
    assert (ch1.start_spine_idx, ch1.end_spine_idx) == (0, 2)
    assert (ch2.start_spine_idx, ch2.end_spine_idx) == (3, 5)


# --- L4: synthetic, always succeeds -----------------------------------------


def test_l4_one_chapter_per_document():
    chapters = l4_chapters(5)
    assert len(chapters) == 5
    assert [c.label for c in chapters] == [f"Document {i}" for i in range(5)]
    assert all(c.start_spine_idx == c.end_spine_idx for c in chapters)


def test_l4_raises_on_zero_documents():
    with pytest.raises(TierNotApplicable):
        l4_chapters(0)


# --- parse_toc_entries: NCX and nav parsing ----------------------------


NCX_SAMPLE = b"""<?xml version="1.0"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">
  <navMap>
    <navPoint id="n1"><navLabel><text>Prologue</text></navLabel>
      <content src="text/ch0.xhtml"/></navPoint>
    <navPoint id="n2"><navLabel><text>Chapter 1</text></navLabel>
      <content src="text/ch1.xhtml#frag"/></navPoint>
    <navPoint id="n3"><navLabel><text>Unknown</text></navLabel>
      <content src="text/missing.xhtml"/></navPoint>
  </navMap>
</ncx>
"""


def test_parse_toc_entries_ncx():
    href_to_spine_idx = {"OEBPS/text/ch0.xhtml": 0, "OEBPS/text/ch1.xhtml": 1}
    entries = parse_toc_entries(NCX_SAMPLE, is_ncx=True, opf_dir="OEBPS", href_to_spine_idx=href_to_spine_idx)
    assert entries == [(0, "Prologue"), (1, "Chapter 1")]


NAV_SAMPLE = b"""<?xml version="1.0"?>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
  <body>
    <nav epub:type="toc">
      <ol>
        <li><a href="text/ch0.xhtml">Prologue</a></li>
        <li><a href="text/ch1.xhtml">Chapter 1</a></li>
      </ol>
    </nav>
  </body>
</html>
"""


def test_parse_toc_entries_nav():
    href_to_spine_idx = {"OEBPS/text/ch0.xhtml": 0, "OEBPS/text/ch1.xhtml": 1}
    entries = parse_toc_entries(NAV_SAMPLE, is_ncx=False, opf_dir="OEBPS", href_to_spine_idx=href_to_spine_idx)
    assert entries == [(0, "Prologue"), (1, "Chapter 1")]
