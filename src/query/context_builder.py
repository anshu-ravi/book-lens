"""Entity-aware context assembly for the enhanced query engine.

build_entity_context() assembles a structured-knowledge string from
the KnowledgeBase based on the question type and the entities mentioned.
This string is passed to build_prompt() alongside the RAG chunks.

Token budget: estimated as len(text.split()) * 1.4. If the assembled
context exceeds max_tokens, content is truncated in order:
  1. Drop minor world facts (description < 50 words)
  2. Truncate key_events to the most recent 10 per character
  3. Truncate moments to the most recent 5 per relationship
"""

from src.knowledge.models import (
    CharacterEntity,
    KnowledgeBase,
    Relationship,
)
from src.query.classifier import QuestionType


def _estimate_tokens(text: str) -> int:
    """Rough token count: words × 1.4."""
    return int(len(text.split()) * 1.4)


def _format_character(char: CharacterEntity) -> str:
    """Render a character profile as a compact text block."""
    lines: list[str] = [f"CHARACTER: {char.name}"]
    if char.aliases:
        lines.append(f"  Also known as: {', '.join(char.aliases)}")
    if char.faction:
        lines.append(f"  Faction: {char.faction}")
    if char.role:
        lines.append(f"  Role: {char.role}")
    if char.description:
        lines.append(f"  Description: {char.description}")
    if char.key_events:
        lines.append("  Key events:")
        for ev in char.key_events:
            lines.append(f"    - (Book {ev.book_index + 1}, Ch {ev.chapter_index + 1}) {ev.description}")
    return "\n".join(lines)


def _format_relationship(rel: Relationship) -> str:
    """Render a relationship as a compact text block."""
    lines: list[str] = [
        f"RELATIONSHIP: {rel.character_a} ↔ {rel.character_b} [{rel.type}]",
        f"  {rel.description}",
    ]
    if rel.moments:
        lines.append("  Key moments:")
        for m in rel.moments:
            lines.append(f"    - (Book {m.book_index + 1}, Ch {m.chapter_index + 1}) {m.description}")
    return "\n".join(lines)


def _get_characters(names: list[str], kb: KnowledgeBase) -> list[CharacterEntity]:
    """Return CharacterEntity objects for the given canonical names."""
    name_set = {n.lower() for n in names}
    return [c for c in kb.characters if c.name.lower() in name_set]


def _get_relationships(names: list[str], kb: KnowledgeBase) -> list[Relationship]:
    """Return relationships involving any of the given canonical names."""
    name_set = {n.lower() for n in names}
    return [
        r for r in kb.relationships
        if r.character_a.lower() in name_set or r.character_b.lower() in name_set
    ]


def _apply_token_budget(sections: list[str], max_tokens: int) -> str:
    """Join sections, truncating if the total exceeds max_tokens.

    Truncation strategy (applied to the joined text, not individual sections):
    the sections list is assembled in priority order; excess sections are
    dropped from the end until within budget.
    """
    result = "\n\n".join(sections)
    if _estimate_tokens(result) <= max_tokens:
        return result

    # Drop sections from the end until within budget.
    kept = list(sections)
    while kept and _estimate_tokens("\n\n".join(kept)) > max_tokens:
        kept.pop()
    return "\n\n".join(kept)


def build_entity_context(
    question_type: QuestionType,
    entity_mentions: list[str],
    kb: KnowledgeBase,
    max_tokens: int = 2500,
) -> str:
    """Assemble structured knowledge context for the given question type.

    Returns an empty string if the KB is empty or no relevant data exists
    for the mentioned entities.

    Args:
        question_type: Classifier output — determines what to include.
        entity_mentions: Canonical character names mentioned in the question.
        kb: Progress-filtered KnowledgeBase.
        max_tokens: Maximum token budget for the returned string.

    Returns:
        Formatted context string, or "" if nothing relevant exists.
    """
    if not kb.characters and not kb.summaries and not kb.world_facts:
        return ""

    sections: list[str] = []

    if question_type == QuestionType.CHARACTER:
        chars = _get_characters(entity_mentions, kb)
        if not chars:
            return ""
        for char in chars:
            sections.append(_format_character(char))
        # Include world facts for their faction as secondary context.
        factions = {c.faction for c in chars if c.faction}
        for wf in kb.world_facts:
            if wf.name in factions or any(f and f.lower() in wf.description.lower() for f in factions):
                sections.append(f"WORLD FACT [{wf.category}]: {wf.name}\n  {wf.description}")

    elif question_type == QuestionType.CHARACTER_ARC:
        chars = _get_characters(entity_mentions, kb)
        if not chars:
            return ""
        for char in chars:
            sections.append(_format_character(char))
        # Chapter summaries the character appears in.
        for summary in kb.summaries:
            if any(c.name in summary.characters_present for c in chars):
                sections.append(
                    f"CHAPTER SUMMARY (Book {summary.book_index + 1}, {summary.chapter_label}):\n"
                    f"  {summary.summary}"
                )

    elif question_type == QuestionType.RELATIONSHIP:
        rels = _get_relationships(entity_mentions, kb)
        if not rels:
            return ""
        for rel in rels:
            sections.append(_format_relationship(rel))
        # Both character profiles as secondary context.
        involved = {r.character_a for r in rels} | {r.character_b for r in rels}
        chars = _get_characters(list(involved), kb)
        for char in chars:
            sections.append(_format_character(char))

    elif question_type == QuestionType.RECAP:
        for summary in kb.summaries:
            if not summary.summary.strip():
                continue
            sections.append(
                f"CHAPTER SUMMARY (Book {summary.book_index + 1}, {summary.chapter_label}):\n"
                f"  {summary.summary}"
            )
        # Characters present as secondary context.
        present_names: set[str] = set()
        for s in kb.summaries:
            present_names.update(s.characters_present)
        chars = _get_characters(list(present_names), kb)
        for char in chars:
            sections.append(f"CHARACTER: {char.name} — {char.description}")

    elif question_type == QuestionType.WORLD_BUILDING:
        for wf in kb.world_facts:
            sections.append(f"WORLD FACT [{wf.category}]: {wf.name}\n  {wf.description}")
        # If specific entities mentioned, include their faction affiliations.
        if entity_mentions:
            chars = _get_characters(entity_mentions, kb)
            for char in chars:
                if char.faction:
                    sections.append(f"CHARACTER: {char.name} — Faction: {char.faction}")

    elif question_type in (QuestionType.CAUSAL, QuestionType.DETAIL):
        # Minimal: character profiles + relationships for involved parties.
        chars = _get_characters(entity_mentions, kb)
        for char in chars:
            sections.append(_format_character(char))
        rels = _get_relationships(entity_mentions, kb)
        for rel in rels:
            sections.append(_format_relationship(rel))

    if not sections:
        return ""

    return _apply_token_budget(sections, max_tokens)
