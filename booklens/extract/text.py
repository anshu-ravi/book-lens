"""Flattens XHTML into clean paragraphs.

Guards two parser traps recorded in the Ingestion section of `DECISIONS.md`.
"""

from __future__ import annotations

import re

from lxml import etree
from lxml import html as lxml_html

from .types import MalformedEpubError

# Consume the ENTIRE opening <body ...> tag, not just the literal "<body".
_BODY_RE = re.compile(r"<body\b[^>]*>(.*)</body\s*>", re.IGNORECASE | re.DOTALL)

# Block-level tags are paragraph/line separators.
_BLOCK_TAGS = {"p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "br", "li", "blockquote"}

# Tags whose text content must never surface (scripts/styles aren't prose).
_SKIP_TAGS = {"script", "style"}

_WS_RE = re.compile(r"\s+")


def _extract_body(html_doc: str) -> str:
    """Slice out the body, consuming the whole opening tag with its attributes."""
    match = _BODY_RE.search(html_doc)
    if match:
        return match.group(1)
    # No <body> tag at all -- treat the whole thing as a bare fragment
    # (used directly by unit tests, and tolerant of odd/partial documents).
    return html_doc


def _normalise(text: str) -> str:
    """Collapse whitespace runs and strip the ends."""
    return _WS_RE.sub(" ", text).strip()


def paragraphs_from_html(html_doc: str) -> tuple[str, ...]:
    """Flatten markup into paragraph strings, dropping empty ones.

    Inline tags collapse so emphasis never splits a sentence, and wording is
    otherwise untouched because citations quote it verbatim.
    """
    body_html = _extract_body(html_doc)
    wrapper = f"<div>{body_html}</div>"
    try:
        root = lxml_html.fromstring(wrapper)
    except etree.XMLSyntaxError as exc:
        raise MalformedEpubError(f"could not parse XHTML content: {exc}") from exc
    except Exception as exc:  # pragma: no cover - lxml.html is very tolerant
        raise MalformedEpubError(f"could not parse XHTML content: {exc}") from exc

    paragraphs: list[str] = []
    buf: list[str] = []

    def flush() -> None:
        """Close off the paragraph being accumulated."""
        text = _normalise("".join(buf))
        buf.clear()
        if text:
            paragraphs.append(text)

    def walk(el) -> None:
        """Recurse the tree, breaking paragraphs only on block tags."""
        tag = el.tag.lower() if isinstance(el.tag, str) else None
        if tag in _SKIP_TAGS:
            return
        is_block = tag in _BLOCK_TAGS
        if is_block:
            flush()
        if el.text:
            buf.append(el.text)
        for child in el:
            if not isinstance(child.tag, str):
                continue  # comments, processing instructions
            walk(child)
            if child.tail:
                buf.append(child.tail)
        if is_block:
            flush()

    walk(root)
    flush()
    return tuple(paragraphs)
