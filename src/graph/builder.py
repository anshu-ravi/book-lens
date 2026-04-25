"""Build Cytoscape-ready graph payload from a KnowledgeBase window.

Takes a KnowledgeBase (already filtered to the user's overall reading progress
by filter_to_progress) and a time window (from_book/from_chapter →
to_book/to_chapter) and returns the node/edge/marker data the frontend needs
to render the Reading Compass graph.

The window defines what the reader wants to explore, not what they're allowed
to see — spoiler filtering is always applied upstream by filter_to_progress
before this builder is called.
"""

from typing import Any

from src.knowledge.models import (
    CharacterEntity,
    KnowledgeBase,
    Relationship,
)


def _before_window_start(
    book_index: int, chapter_index: int, from_book: int, from_chapter: int
) -> bool:
    """Return True if this (book, chapter) is before the window start."""
    if book_index < from_book:
        return True
    if book_index == from_book and chapter_index < from_chapter:
        return True
    return False


def _within_window(
    book_index: int,
    chapter_index: int,
    from_book: int,
    from_chapter: int,
    to_book: int,
    to_chapter: int,
) -> bool:
    """Return True if (book, chapter) falls within [from, to] inclusive."""
    after_start = (book_index, chapter_index) >= (from_book, from_chapter)
    before_end = (book_index, chapter_index) <= (to_book, to_chapter)
    return after_start and before_end


def _build_node(char: CharacterEntity, ghost: bool, from_book: int, from_chapter: int, to_book: int, to_chapter: int) -> dict[str, Any]:
    """Build a single Cytoscape node dict for a character."""
    windowed_events = [
        {"book": e.book_index, "chapter": e.chapter_index, "description": e.description}
        for e in char.key_events
        if _within_window(e.book_index, e.chapter_index, from_book, from_chapter, to_book, to_chapter)
    ]
    return {
        "id": char.name,
        "label": char.name,
        "faction": char.faction or "",
        "role": char.role or "",
        "first_appearance": {
            "book": char.first_appearance.book_index,
            "chapter": char.first_appearance.chapter_index,
        } if char.first_appearance else None,
        "key_events": windowed_events,
        "ghost": ghost,
    }


def _build_edge(rel: Relationship, from_book: int, from_chapter: int, to_book: int, to_chapter: int) -> dict[str, Any]:
    """Build a single Cytoscape edge dict for a relationship."""
    windowed_moments = [
        {"book": m.book_index, "chapter": m.chapter_index, "description": m.description}
        for m in rel.moments
        if _within_window(m.book_index, m.chapter_index, from_book, from_chapter, to_book, to_chapter)
    ]

    # Determine the initial type at window start by looking at the first known moment.
    # We approximate: type at first moment vs current type.
    initial_type = rel.type  # fallback — same as current
    has_turning_point = False

    all_moments_sorted = sorted(rel.moments, key=lambda m: (m.book_index, m.chapter_index))
    # A turning point is signalled by the existence of multiple moments where
    # the relationship is noted as changing — we surface this as a flag since
    # the KB stores only the final type. Any relationship with 2+ moments is
    # considered potentially evolved.
    if len(all_moments_sorted) >= 2:
        has_turning_point = True
        # Treat the type at the first moment as the initial type (best approximation
        # without storing historical types in the current KB schema).
        initial_type = rel.type  # still same — actual type history not in KB yet

    return {
        "source": rel.character_a,
        "target": rel.character_b,
        "type": rel.type,
        "initial_type": initial_type,
        "has_turning_point": has_turning_point,
        "moments": windowed_moments,
    }


def build_graph_payload(
    kb: KnowledgeBase,
    from_book: int,
    from_chapter: int,
    to_book: int,
    to_chapter: int,
) -> dict[str, Any]:
    """Build the full graph payload for a given KB and time window.

    Args:
        kb: KnowledgeBase already filtered to user's reading progress.
        from_book: Start of the window (book index, 0-based).
        from_chapter: Start of the window (chapter index, 0-based).
        to_book: End of the window (book index, 0-based).
        to_chapter: End of the window (chapter index, 0-based).

    Returns:
        Dict with keys: nodes, edges, scrubber_markers.
    """
    nodes: list[dict[str, Any]] = []
    ghost_names: set[str] = set()

    for char in kb.characters:
        if char.first_appearance is None:
            continue

        fa_book = char.first_appearance.book_index
        fa_chapter = char.first_appearance.chapter_index

        # Characters who first appear after the window end are hidden (spoiler-safe
        # filtering already removed truly future chars; this handles window trimming).
        if not _within_window(fa_book, fa_chapter, 0, 0, to_book, to_chapter):
            continue

        # Characters who first appear before the window start are shown as ghosts.
        ghost = _before_window_start(fa_book, fa_chapter, from_book, from_chapter)
        if ghost:
            ghost_names.add(char.name)

        nodes.append(_build_node(char, ghost, from_book, from_chapter, to_book, to_chapter))

    # Active character names (non-ghost) for edge filtering.
    active_names = {n["id"] for n in nodes if not n["ghost"]}
    all_visible_names = {n["id"] for n in nodes}

    edges: list[dict[str, Any]] = []
    for rel in kb.relationships:
        # Both characters must be visible in the graph (ghost or active).
        if rel.character_a not in all_visible_names or rel.character_b not in all_visible_names:
            continue

        # At least one moment must fall within the window.
        windowed_moments = [
            m for m in rel.moments
            if _within_window(m.book_index, m.chapter_index, from_book, from_chapter, to_book, to_chapter)
        ]
        if not windowed_moments:
            continue

        edges.append(_build_edge(rel, from_book, from_chapter, to_book, to_chapter))

    scrubber_markers = _build_scrubber_markers(kb, from_book, from_chapter, to_book, to_chapter)

    return {
        "nodes": nodes,
        "edges": edges,
        "scrubber_markers": scrubber_markers,
    }


def _build_scrubber_markers(
    kb: KnowledgeBase,
    from_book: int,
    from_chapter: int,
    to_book: int,
    to_chapter: int,
) -> list[dict[str, Any]]:
    """Derive notable moment markers for the scrubber track."""
    markers: list[dict[str, Any]] = []
    seen: set[tuple[int, int, str]] = set()

    def add(book: int, chapter: int, label: str, marker_type: str) -> None:
        key = (book, chapter, label)
        if key in seen:
            return
        seen.add(key)
        markers.append({"book": book, "chapter": chapter, "label": label, "type": marker_type})

    # Character first appearances within window.
    for char in kb.characters:
        if char.first_appearance is None:
            continue
        fa = char.first_appearance
        if _within_window(fa.book_index, fa.chapter_index, from_book, from_chapter, to_book, to_chapter):
            add(fa.book_index, fa.chapter_index, f"{char.name} first appears", "first_appearance")

    # Relationship moments within window.
    for rel in kb.relationships:
        for moment in rel.moments:
            if _within_window(moment.book_index, moment.chapter_index, from_book, from_chapter, to_book, to_chapter):
                # Truncate long descriptions for the tooltip.
                label = moment.description[:60] + ("…" if len(moment.description) > 60 else "")
                marker_type = "turning_point" if len(rel.moments) >= 2 else "relationship"
                add(moment.book_index, moment.chapter_index, label, marker_type)

    # Sort chronologically.
    markers.sort(key=lambda m: (m["book"], m["chapter"]))
    return markers
