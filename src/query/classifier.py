"""Question type classification and entity mention extraction.

classify_question() uses heuristic regex patterns first (instant, free).
The heuristics handle the common cases clearly; ambiguous short questions
fall back to QuestionType.DETAIL without an LLM call.

extract_entity_mentions() does a longest-match-first scan of the question
against the alias_registry to identify which known characters/entities are
referenced, returning their canonical names.
"""

import re
from enum import Enum


class QuestionType(str, Enum):
    """Categories of questions the reading companion can receive."""

    CHARACTER = "character"
    CHARACTER_ARC = "character_arc"
    RELATIONSHIP = "relationship"
    RECAP = "recap"
    WORLD_BUILDING = "world"
    CAUSAL = "causal"
    DETAIL = "detail"


# ---------------------------------------------------------------------------
# Heuristic patterns — ordered from most to least specific
# ---------------------------------------------------------------------------

_PATTERNS: list[tuple[re.Pattern, QuestionType]] = [
    # CAUSAL: why / what caused — check before CHARACTER to avoid "why is X" → CHARACTER
    (re.compile(r"\bwhy\b|\bwhat\s+caused\b|\breason\s+for\b", re.IGNORECASE), QuestionType.CAUSAL),
    # RECAP: explicit recap/summarise/what happened/what happens
    (
        re.compile(
            r"\brecap\b|\bsummar(?:y|ize|ise)\b|\bwhat\s+happen(?:s|ed|s\s+in)?\b",
            re.IGNORECASE,
        ),
        QuestionType.RECAP,
    ),
    # RELATIONSHIP: between two characters / relationship / history between
    (
        re.compile(
            r"\brelationship\b|\bhistory\s+between\b|\bbetween\b.+\band\b",
            re.IGNORECASE,
        ),
        QuestionType.RELATIONSHIP,
    ),
    # CHARACTER_ARC: journey / arc / development / changed / evolution
    (
        re.compile(
            r"\bjourney\b|\b(?:character\s+)?arc\b|\bdevelopment\b|\bchanged?\b|\bevolv(?:e|ed|tion)\b"
            r"|\btrace\b",
            re.IGNORECASE,
        ),
        QuestionType.CHARACTER_ARC,
    ),
    # WORLD_BUILDING: how does/do X work, explain X, what is/are (non-person nouns)
    (
        re.compile(
            r"\bhow\s+does\b|\bhow\s+do\b|\bexplain\b|\bwhat\s+is\s+the\b|\bwhat\s+are\s+the\b",
            re.IGNORECASE,
        ),
        QuestionType.WORLD_BUILDING,
    ),
    # CHARACTER: who is / tell me about / describe
    (
        re.compile(r"\bwho\s+is\b|\btell\s+me\s+about\b|\bdescribe\b", re.IGNORECASE),
        QuestionType.CHARACTER,
    ),
]


def classify_question(question: str) -> QuestionType:
    """Classify a question into a QuestionType using heuristic patterns.

    Patterns are checked in priority order. The first match wins.
    If nothing matches, returns QuestionType.DETAIL.

    Args:
        question: The user's natural-language question.

    Returns:
        The best-matching QuestionType.
    """
    for pattern, question_type in _PATTERNS:
        if pattern.search(question):
            return question_type
    return QuestionType.DETAIL


def extract_entity_mentions(question: str, alias_registry: dict[str, str]) -> list[str]:
    """Find all known entity aliases in the question and return canonical names.

    Uses longest-match-first so "Darrow of Lykos" is matched as one entity
    rather than "Darrow" alone. The question is lowercased for comparison.

    Args:
        question: The user's question.
        alias_registry: Mapping of lowercased alias → canonical name,
            from KnowledgeBase.alias_registry.

    Returns:
        List of canonical names, deduplicated, in order of first appearance.
    """
    lowered = question.lower()

    # Sort aliases longest-first to ensure greedy/longest-match behaviour.
    sorted_aliases = sorted(alias_registry.keys(), key=len, reverse=True)

    found: list[str] = []
    seen_canonical: set[str] = set()
    # Track consumed spans to avoid double-counting sub-aliases.
    consumed: list[tuple[int, int]] = []

    for alias in sorted_aliases:
        start = 0
        while True:
            pos = lowered.find(alias, start)
            if pos == -1:
                break
            end = pos + len(alias)

            # Skip if this span overlaps an already-consumed longer match.
            overlaps = any(s <= pos < e or s < end <= e for s, e in consumed)
            if not overlaps:
                canonical = alias_registry[alias]
                consumed.append((pos, end))
                if canonical not in seen_canonical:
                    seen_canonical.add(canonical)
                    found.append(canonical)
            start = pos + 1

    # Return in order of first appearance in the question.
    found.sort(key=lambda name: min(
        lowered.find(a) for a in alias_registry if alias_registry[a] == name and a in lowered
    ))
    return found
