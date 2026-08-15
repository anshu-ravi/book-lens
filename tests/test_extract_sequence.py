"""Unit tests for booklens.extract.sequence: the S-ladder, against synthetic inputs."""

import pytest

from booklens.extract.sequence import (
    TierNotApplicable,
    resolve_href,
    resolve_sequence,
    sequence_s1,
    sequence_s2,
    sequence_s3,
)
from booklens.extract.types import MalformedEpubError


# --- resolve_href -----------------------------------------------------------


def test_resolve_href_relative_to_opf_dir():
    assert resolve_href("OEBPS", "text/ch01.xhtml") == "OEBPS/text/ch01.xhtml"


def test_resolve_href_guards_no_separator_opf_at_root():
    # Regression: content.opf at the zip root means opf_dir == "". A naive
    # rsplit('/', 1)[0] on the OPF path itself would return "content.opf"
    # (the filename) instead of "", breaking every subsequent resolution.
    assert resolve_href("", "text/part0000.html") == "text/part0000.html"


def test_resolve_href_strips_fragment_and_unquotes():
    assert resolve_href("OEBPS", "text/ch%2001.xhtml#frag") == "OEBPS/text/ch 01.xhtml"


def test_resolve_href_handles_dot_dot():
    assert resolve_href("OEBPS/text", "../images/cover.jpg") == "OEBPS/images/cover.jpg"


# --- S1: OPF spine itemref order --------------------------------------------


def test_s1_uses_spine_order():
    manifest = {"a": ("OEBPS/a.xhtml", "application/xhtml+xml"), "b": ("OEBPS/b.xhtml", "application/xhtml+xml")}
    result = sequence_s1(["b", "a"], manifest, "OEBPS")
    assert result == ("OEBPS/b.xhtml", "OEBPS/a.xhtml")


def test_s1_keeps_linear_no_items():
    # The contract says S1 must not drop linear="no" -- the caller passes
    # every idref through regardless of a linear attribute, so this is
    # really testing that sequence_s1 does no filtering of its own.
    manifest = {"a": ("OEBPS/a.xhtml", "application/xhtml+xml"), "b": ("OEBPS/b.xhtml", "application/xhtml+xml")}
    result = sequence_s1(["a", "b"], manifest, "OEBPS")
    assert result == ("OEBPS/a.xhtml", "OEBPS/b.xhtml")


def test_s1_raises_on_empty_spine():
    with pytest.raises(TierNotApplicable):
        sequence_s1([], {"a": ("OEBPS/a.xhtml", "application/xhtml+xml")}, "OEBPS")


def test_s1_raises_when_no_idref_resolves():
    manifest = {"a": ("OEBPS/a.xhtml", "application/xhtml+xml")}
    with pytest.raises(TierNotApplicable):
        sequence_s1(["missing1", "missing2"], manifest, "OEBPS")


# --- S2: OPF manifest order, filtered to content documents ------------------


def test_s2_filters_to_content_media_types():
    manifest = {
        "cover": ("OEBPS/cover.jpg", "image/jpeg"),
        "a": ("OEBPS/a.xhtml", "application/xhtml+xml"),
        "css": ("OEBPS/style.css", "text/css"),
        "b": ("OEBPS/b.xhtml", "application/xhtml+xml"),
    }
    result = sequence_s2(manifest)
    assert result == ("OEBPS/a.xhtml", "OEBPS/b.xhtml")


def test_s2_raises_when_no_content_documents():
    manifest = {"cover": ("OEBPS/cover.jpg", "image/jpeg")}
    with pytest.raises(TierNotApplicable):
        sequence_s2(manifest)


# --- S3: natural sort of zip entry names ------------------------------------


def test_s3_natural_sorts_numeric_filenames():
    names = ["META-INF/container.xml", "OEBPS/ch10.html", "OEBPS/ch2.html", "OEBPS/ch1.html"]
    result = sequence_s3(names)
    assert result == ("OEBPS/ch1.html", "OEBPS/ch2.html", "OEBPS/ch10.html")


def test_s3_excludes_meta_inf():
    names = ["META-INF/container.xml", "OEBPS/ch1.html"]
    result = sequence_s3(names)
    assert result == ("OEBPS/ch1.html",)


def test_s3_raises_when_nothing_looks_like_content():
    names = ["META-INF/container.xml", "OEBPS/cover.jpg", "OEBPS/style.css"]
    with pytest.raises(TierNotApplicable):
        sequence_s3(names)


# --- resolve_sequence: the ladder driver ------------------------------------


def test_ladder_falls_back_to_s2_when_spine_empty():
    manifest = {"a": ("OEBPS/a.xhtml", "application/xhtml+xml")}
    hrefs, tier = resolve_sequence(["OEBPS/a.xhtml"], "OEBPS", manifest, [])
    assert tier == "S2"
    assert hrefs == ("OEBPS/a.xhtml",)


def test_ladder_falls_back_to_s3_when_spine_and_manifest_empty():
    names = ["OEBPS/ch1.html"]
    hrefs, tier = resolve_sequence(names, "OEBPS", {}, [])
    assert tier == "S3"
    assert hrefs == ("OEBPS/ch1.html",)


def test_ladder_raises_when_every_tier_fails():
    with pytest.raises(MalformedEpubError):
        resolve_sequence(["META-INF/container.xml"], "OEBPS", {}, [])
