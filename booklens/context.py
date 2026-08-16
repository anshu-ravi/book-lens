"""Assembles a reader's entire readable set into one prompt-ready string.

Per `DECISIONS.md` section 7, the answering context is every paragraph at or
below the cutoff, raw, ascending `global_seq`, with no digest or retrieval
step in between.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from booklens import db
from booklens.tools import Tools, parse_citation_id

# Headroom under the ~1.05M-token window (DECISIONS.md section 7) for the
# system prompt, the conversation so far, and the model's answer.
DEFAULT_MAX_TOKENS = 800_000

_CHARS_PER_TOKEN = 4  # crude chars/4 estimate; good enough for a budget check, not a billing figure


class ContextOverflowError(Exception):
    """The readable set does not fit the token budget. Never truncated to fit."""


@dataclass(frozen=True)
class AssembledContext:
    """One reader's entire readable set, rendered ready to drop into a prompt."""

    text: str
    para_count: int
    max_global_seq: int | None
    token_estimate: int
    chapter_span: tuple[str, str] | None
    content_hash: str


def assemble(tools: Tools, *, max_tokens: int = DEFAULT_MAX_TOKENS) -> AssembledContext:
    """Render every readable paragraph, oldest first, as one byte-stable string.

    Walks `tools.list_books()` then `tools.list_chapters()` /
    `tools.read_raw()` per book -- the only place the cutoff is ever applied
    is inside those calls. Raises `ContextOverflowError` rather than
    truncating when the result exceeds `max_tokens` (chars // 4).
    """
    lines: list[str] = []
    para_count = 0
    max_global_seq: int | None = None
    first_label: str | None = None
    last_label: str | None = None

    for book in tools.list_books():
        book_id = book["id"]
        book_order = book["book_order"]
        chapters = tools.list_chapters(book_id)["chapters"]
        if not chapters:
            continue  # nothing readable in this book yet

        lines.append(f"# {book['title']}")

        for chapter in chapters:
            chapter_idx = chapter["chapter_idx"]
            raw = tools.read_raw(book_id, chapter_idx, chapter_idx)
            if raw.get("capped"):
                # A chapter alone exceeding Tools' per-request paragraph cap
                # is a capacity problem, not a case to silently drop from.
                raise ContextOverflowError(
                    f"{book_id} chapter {chapter_idx} exceeds "
                    "Tools.read_raw's per-request paragraph cap; the "
                    "assembler cannot retrieve it as a complete chapter"
                )
            paragraphs = raw["paragraphs"]
            if not paragraphs:
                continue

            label = f"{book_id}: {chapter['label']}"
            lines.append(f"## {label}")
            if first_label is None:
                first_label = label
            last_label = label

            for para in paragraphs:
                lines.append(f"[{para['citation_id']}] {para['text']}")
                para_count += 1
                _, spine_idx, para_idx = parse_citation_id(para["citation_id"])
                seq = db.global_seq(book_order, spine_idx, para_idx)
                if max_global_seq is None or seq > max_global_seq:
                    max_global_seq = seq

    text = "\n".join(lines)
    token_estimate = len(text) // _CHARS_PER_TOKEN
    if token_estimate > max_tokens:
        raise ContextOverflowError(
            f"assembled context is ~{token_estimate} tokens, "
            f"{token_estimate - max_tokens} over the {max_tokens}-token budget"
        )

    chapter_span = (first_label, last_label) if first_label is not None else None
    content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()

    return AssembledContext(
        text=text,
        para_count=para_count,
        max_global_seq=max_global_seq,
        token_estimate=token_estimate,
        chapter_span=chapter_span,
        content_hash=content_hash,
    )
