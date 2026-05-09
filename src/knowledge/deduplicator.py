"""SILVER stage: Deduplicate characters and resolve aliases."""

import json
from pathlib import Path
from typing import Any, Optional


class Deduplicator:
    """Deduplicate characters across chapters using canonical registry."""

    def __init__(self, series_id: str) -> None:
        """Initialize deduplicator.

        Args:
            series_id: Series identifier.
        """
        self.series_id = series_id
        self.extraction_dir = Path("data/extractions") / series_id
        self.canonical_registry: dict[str, str] = {}  # alias_lower -> canonical_name
        self.pending_reveals: list[dict[str, Any]] = []  # {char_a, char_b, reveal_type, context, reveal_chapter}

    def run(self, limit: Optional[int] = None) -> None:
        """Run deduplication pass over all extracted chapters.

        Args:
            limit: If set, only process first N chapters.
        """
        # Find all extraction files and sort by chapter index
        extraction_files = sorted(
            self.extraction_dir.glob("*_*.json"),
            key=lambda f: int(f.stem.split("_")[0]),
        )

        if limit:
            extraction_files = extraction_files[:limit]

        for file_path in extraction_files:
            chapter_index = int(file_path.stem.split("_")[0])
            self._process_chapter(file_path, chapter_index)

        # Save canonical registry
        self._save_registry()

    def _process_chapter(self, file_path: Path, chapter_index: int) -> None:
        """Process a single chapter's extraction.

        Args:
            file_path: Path to extraction JSON.
            chapter_index: Chapter number.
        """
        with open(file_path) as f:
            extraction = json.load(f)

        # Process characters
        deduped_characters = []
        for char in extraction.get("characters", []):
            deduped_char = self._deduplicate_character(char, chapter_index)
            deduped_characters.append(deduped_char)

        extraction["characters"] = deduped_characters

        # Process relationships: update character names to canonical
        deduped_relationships = []
        for rel in extraction.get("relationships", []):
            rel["character_a"] = self._resolve_to_canonical(rel["character_a"])
            rel["character_b"] = self._resolve_to_canonical(rel["character_b"])
            deduped_relationships.append(rel)

        extraction["relationships"] = deduped_relationships

        # Process identity reveals
        for reveal in extraction.get("identity_reveals", []):
            char_a_canonical = self._resolve_to_canonical(reveal["character_a"])
            char_b_canonical = self._resolve_to_canonical(reveal["character_b"])

            self.pending_reveals.append(
                {
                    "character_a": char_a_canonical,
                    "character_b": char_b_canonical,
                    "reveal_type": reveal["reveal_type"],
                    "context": reveal["context"],
                    "reveal_chapter_index": chapter_index,
                }
            )

        # Save enriched JSON
        with open(file_path, "w") as f:
            json.dump(extraction, f, indent=2)

    def _deduplicate_character(self, char: dict[str, Any], chapter_index: int) -> dict[str, Any]:
        """Deduplicate a character entry.

        Register name and aliases in canonical registry.
        Return updated character with canonical name.

        Args:
            char: Character dict from extraction.
            chapter_index: Chapter number (for tracking first appearance).

        Returns:
            Updated character dict with canonical name.
        """
        name = char["name"]
        aliases = char.get("aliases", [])

        # Check if any name/alias already registered
        canonical_name = None
        for candidate in [name] + aliases:
            if candidate.lower() in self.canonical_registry:
                canonical_name = self.canonical_registry[candidate.lower()]
                break

        # If no existing entry, create new canonical entry
        if canonical_name is None:
            canonical_name = name
            self.canonical_registry[name.lower()] = canonical_name
            for alias in aliases:
                self.canonical_registry[alias.lower()] = canonical_name
        else:
            # Add any new aliases to registry
            for alias in aliases:
                if alias.lower() not in self.canonical_registry:
                    self.canonical_registry[alias.lower()] = canonical_name

        # Update character dict with canonical name
        char["name"] = canonical_name
        char["first_chapter_index"] = chapter_index

        return char

    def _resolve_to_canonical(self, name: str) -> str:
        """Resolve a name to its canonical form.

        Args:
            name: Name to resolve (may be alias).

        Returns:
            Canonical name.
        """
        return self.canonical_registry.get(name.lower(), name)

    def _save_registry(self) -> None:
        """Save canonical registry and pending reveals to disk."""
        # Save registry
        registry_file = self.extraction_dir / "canonical_registry.json"
        with open(registry_file, "w") as f:
            json.dump(self.canonical_registry, f, indent=2)

        # Save pending reveals
        reveals_file = self.extraction_dir / "pending_reveals.json"
        with open(reveals_file, "w") as f:
            json.dump(self.pending_reveals, f, indent=2)
