"""Unit tests for booklens.extract.text: XHTML -> flattened paragraphs."""

from booklens.extract.text import paragraphs_from_html


def test_italics_do_not_split_a_sentence():
    # Regression: an early extractor produced "I\nain't\ntwelve" from this input.
    html = "<p>I <i>ain't</i> twelve</p>"
    assert paragraphs_from_html(html) == ("I ain't twelve",)


def test_bold_and_span_are_transparent():
    html = "<p>He said <b>no</b> and then <span>walked away</span>.</p>"
    assert paragraphs_from_html(html) == ("He said no and then walked away.",)


def test_link_inline_tag_is_transparent():
    html = "<p>See <a href='x'>this page</a> for more.</p>"
    assert paragraphs_from_html(html) == ("See this page for more.",)


def test_block_tags_separate_paragraphs():
    html = "<div><p>First.</p><p>Second.</p></div>"
    assert paragraphs_from_html(html) == ("First.", "Second.")


def test_br_splits_within_a_block():
    html = "<p>Line one.<br/>Line two.</p>"
    assert paragraphs_from_html(html) == ("Line one.", "Line two.")


def test_headings_are_their_own_paragraphs():
    html = "<h1>Chapter 1</h1><p>Body text.</p>"
    assert paragraphs_from_html(html) == ("Chapter 1", "Body text.")


def test_empty_paragraphs_are_dropped_and_para_idx_is_contiguous():
    html = "<p>One</p><p>   </p><p></p><p>Two</p>"
    result = paragraphs_from_html(html)
    assert result == ("One", "Two")


def test_whitespace_is_normalised():
    html = "<p>  Lots   of\n\n  whitespace   here.  </p>"
    assert paragraphs_from_html(html) == ("Lots of whitespace here.",)


def test_consumes_entire_body_opening_tag():
    # Regression: splitting on the literal "<body" left ' class="calibre">'
    # as leading text that survived tag-stripping.
    html = (
        "<html><body id='x' class=\"calibre\">"
        "<p>Real content.</p>"
        "</body></html>"
    )
    result = paragraphs_from_html(html)
    assert result == ("Real content.",)
    assert not any("calibre" in p for p in result)


def test_no_body_tag_falls_back_to_whole_fragment():
    html = "<p>Bare fragment, no body wrapper.</p>"
    assert paragraphs_from_html(html) == ("Bare fragment, no body wrapper.",)


def test_epigraph_style_blockquote_is_kept():
    html = "<blockquote><p>Some epigraph text.</p></blockquote><p>Chapter body.</p>"
    result = paragraphs_from_html(html)
    assert "Some epigraph text." in result
    assert "Chapter body." in result


def test_no_paragraph_ever_contains_a_newline():
    html = "<p>Multi<br/>line<br/>paragraph <i>with</i> emphasis.</p>"
    for p in paragraphs_from_html(html):
        assert "\n" not in p


def test_script_and_style_content_is_excluded():
    html = "<style>.x{color:red}</style><script>var x=1;</script><p>Only this.</p>"
    assert paragraphs_from_html(html) == ("Only this.",)
