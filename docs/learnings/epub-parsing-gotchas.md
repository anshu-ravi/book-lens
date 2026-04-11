# Epub Parsing Gotchas and Learnings

## Critical Finding: Image-Based Chapter Titles

**Problem**: Many epubs (including our test file "Project Hail Mary") use `<img>` tags with `alt` attributes for chapter titles instead of plain text in heading tags.

**Example**:
```html
<h1><img alt="Chapter 1" src="images/chapter1.png" /></h1>
```

**Impact**: 32 out of 35 chapters in our test epub use this pattern. Without checking image alt attributes, we would miss most chapter labels.

**Solution**: Enhanced label extraction to check for `img alt` attributes when heading text is empty:

```python
tag = soup.find('h1')
if tag:
    text = tag.get_text(strip=True)
    if text:
        return text

    # Check for image alt text
    img = tag.find('img')
    if img and img.get('alt'):
        return img.get('alt')
```

---

## Spine vs. Table of Contents

**Key Decision**: Use `book.spine` instead of `book.toc` for chapter ordering.

**Reasoning**:
- `spine` represents the actual reading order intended by the publisher
- `toc` may skip sections or reorganize content for navigation purposes
- Some epubs have incomplete or missing TOC metadata

**Implementation**:
```python
for item_id, _ in book.spine:
    item = book.get_item_with_id(item_id)
    # Process item...
```

---

## Filtering Short Sections

**Threshold**: Skip sections with < 100 characters of text.

**Why**: Epubs often include:
- Copyright pages
- Blank separator pages
- Publisher logos/metadata
- Navigation links

**Validation**: Testing with "Project Hail Mary" showed this threshold effectively filters out 5 non-content items while preserving all actual chapters.

**Edge Case**: Be aware that extremely short prologues or epilogues might be skipped. Consider logging filtered sections for manual review.

---

## HTML Parsing: BeautifulSoup + XML Parser

**Choice**: Use `xml` parser for epub content.

**Reasoning**:
- Epub files use XHTML/XML format, not HTML
- XML parser provides more reliable parsing for well-formed documents
- Avoids BeautifulSoup warnings about parsing XML as HTML
- Proper namespace handling for XHTML

**Usage**:
```python
soup = BeautifulSoup(html_content, "xml")
```

**Gotcha**: Requires `lxml` package to be installed (provides the XML parser). Already included in our Poetry dependencies.

---

## Text Extraction: get_text() Options

**Best Practice**:
```python
text = soup.get_text(separator=" ", strip=True)
```

**Parameters Explained**:
- `separator=" "`: Joins text from different tags with spaces (prevents words from concatenating)
- `strip=True`: Removes leading/trailing whitespace

**Without separator**:
```
"Hello"
"World"
→ "HelloWorld"  # BAD
```

**With separator=" "**:
```
"Hello"
"World"
→ "Hello World"  # GOOD
```

---

## Duplicate Label Handling

**Problem**: Some epubs have multiple sections with the same heading (e.g., multiple "Prologue" sections, or unlabeled sections all getting "Section 1" fallback).

**Solution**: Track label usage and append counters:
- First occurrence: "Prologue"
- Second occurrence: "Prologue (2)"
- Third occurrence: "Prologue (3)"

**Implementation**: See `_deduplicate_labels()` function in `epub_parser.py`.

---

## Error Handling

**Common Errors**:
1. **File not found**: Handled with explicit `FileNotFoundError`
2. **Invalid epub**: ebooklib raises `ebooklib.epub.EpubException`
3. **Malformed HTML**: BeautifulSoup is lenient, rarely raises errors

**Future Enhancement**: Add logging for:
- Skipped sections (< 100 chars)
- Sections with fallback labels
- Missing metadata

---

## Label Extraction Priority

**Hierarchy** (first match wins):
1. `<h1>`, `<h2>`, `<h3>` text content
2. `<h1>`, `<h2>`, `<h3>` image alt attribute
3. Elements with classes: "chapter", "title", "heading"
4. Fallback: "Section {index + 1}"

**Why this order**: Most reliable indicators of chapter boundaries listed first, with progressively more speculative approaches.

---

## Performance Notes

**Test epub stats** (Project Hail Mary):
- Total spine items: 42
- Filtered items (< 100 chars): 5
- Final chapter count: 35
- Parse time: ~1-2 seconds (informal measurement)

**Scalability**: For typical novels (30-50 chapters), performance is not a concern. Very large epubs (technical manuals, compilations) may take longer but still should be under 10 seconds.

---

## Future Improvements

1. **Logging**: Add structured logging for debugging and monitoring
2. **Progress callback**: For UI integration, allow passing a callback for parsing progress
3. **Metadata extraction**: Extract author, title, ISBN from epub metadata
4. **Chapter detection heuristics**: Improve label extraction with ML or better regex patterns
5. **Caching**: Cache parsed results to avoid re-parsing unchanged files

---

## Testing Recommendations

**For comprehensive validation**:
1. Test with multiple epub sources (different publishers, formats)
2. Test with non-English epubs (Unicode handling)
3. Test with EPUB2 vs EPUB3 formats
4. Test with epubs that have:
   - No chapter headings (all fallback labels)
   - Inconsistent heading hierarchy (mixing h1, h2, h3)
   - Image-based titles (already tested ✓)
   - Very short chapters (poetry, children's books)

---

## Known Limitations

1. **No support for fixed-layout epubs**: Designed for reflowable text only
2. **No image extraction**: We extract text only, images are ignored
3. **No formatting preservation**: Bold, italic, etc. are lost (intentional for chunking)
4. **No footnote handling**: Footnotes are included inline with body text
5. **No multi-file chapter handling**: Assumes one spine item = one chapter (mostly true)

---

## Resources

- [EPUB spec (IDPF)](https://www.w3.org/publishing/epub3/epub-spec.html)
- [ebooklib documentation](https://github.com/aerkalov/ebooklib)
- [BeautifulSoup documentation](https://www.crummy.com/software/BeautifulSoup/bs4/doc/)
