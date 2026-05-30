"""Surface-form entity deduplication via normalization and fuzzy matching."""

import re
from difflib import SequenceMatcher
from typing import Optional


class CanonicalRegistry:
    """Case- and surface-form-aware entity name registry.

    Merges names that are the same entity expressed differently:
    - Leading articles: "The Society" → "Society"
    - Plural forms: "Lambdas" → "Lambda"
    - Near-spelling variants via fuzzy match (edit distance)

    Does NOT merge identity reveals (Stranger → Brian). Those remain as
    separate nodes linked by REVEALED_AS edges, gated by chapter index.
    """

    def __init__(self) -> None:
        self._registry: dict[str, str] = {}  # normalized_key → canonical pretty name

    def _normalize(self, name: str) -> str:
        """Reduce a name to a stable lookup key."""
        name = name.lower().strip()
        name = re.sub(r"^the\s+", "", name)  # "the society" → "society"
        if len(name) > 4:
            name = re.sub(r"s$", "", name)   # "lambdas" → "lambda" (guard: > 4 chars)
        return name

    def _find_fuzzy_match(self, normalized: str) -> Optional[str]:
        """Return an existing canonical if edit-distance is close enough.

        Minimum 4-char length on both sides avoids collapsing short proper
        nouns like "Eo" or "Io" into each other.
        """
        if len(normalized) < 4:
            return None
        for key, canonical in self._registry.items():
            if len(key) < 4:
                continue
            ratio = SequenceMatcher(None, normalized, key).ratio()
            if ratio >= 0.88:
                return canonical
        return None

    def register(self, name: str) -> str:
        """Register a name and return its canonical form.

        The first pretty-printed form seen for a normalized key wins.
        Subsequent registrations of the same surface form return the stored
        canonical without overwriting it.
        """
        if not name or not name.strip():
            return name
        norm = self._normalize(name)
        if norm in self._registry:
            return self._registry[norm]
        fuzzy = self._find_fuzzy_match(norm)
        if fuzzy is not None:
            self._registry[norm] = fuzzy
            return fuzzy
        # First time we see this normalized key — store pretty name as canonical
        self._registry[norm] = name
        return name

    def resolve(self, name: str) -> str:
        """Resolve a name to its canonical form, or return it unchanged."""
        if not name:
            return name
        return self._registry.get(self._normalize(name), name)

    def to_dict(self) -> dict[str, str]:
        """Serialize registry for storage (JSON-safe)."""
        return dict(self._registry)

    @classmethod
    def from_dict(cls, data: dict[str, str]) -> "CanonicalRegistry":
        """Restore a registry from a serialized dict."""
        obj = cls()
        obj._registry = data
        return obj
