"""SILVER stage: Deduplicate characters and normalize references."""

import json
import logging
from typing import Any, Optional

from src.knowledge.entity_normalizer import CanonicalRegistry
from src.supabase_client import get_supabase_client

logger = logging.getLogger(__name__)


class DeduplicationService:
    """Deduplicate characters across chapters and build canonical registry."""

    def __init__(self, user_id: str, book_id: str, series_id: str) -> None:
        """Initialize deduplication service.

        Args:
            user_id: User identifier.
            book_id: Book identifier.
            series_id: Series identifier.
        """
        self.user_id = user_id
        self.book_id = book_id
        self.series_id = series_id
        self.client = get_supabase_client()
        self.registry = CanonicalRegistry()
        self.pending_reveals: list[dict[str, Any]] = []

    async def deduplicate_book(self) -> None:
        """Deduplicate characters for a book and update canonical registry.

        Loads raw extractions, builds character canonical names, saves deduped data.
        """
        try:
            logger.info(f"Starting deduplication for book {self.book_id}")

            # Load canonical registry for series
            await self._load_canonical_registry()
            logger.info(f"Loaded canonical registry with {len(self.registry.to_dict())} entries")

            # Load raw extractions
            raw_extractions = await self._load_raw_extractions()
            if not raw_extractions:
                logger.warning("No raw extractions found")
                return

            # Dedupe chapters
            deduped_extractions = {}
            for chapter_idx, chapter_data in sorted(raw_extractions.items(), key=lambda x: int(x[0])):
                deduped = self._dedupe_chapter(
                    json.loads(json.dumps(chapter_data)), int(chapter_idx)
                )
                deduped_extractions[chapter_idx] = deduped

            # Save deduped extractions
            await self._save_deduped_extractions(deduped_extractions)

            # Save updated canonical registry
            await self._save_canonical_registry()

            # Update database status
            await self._update_status("completed")
            logger.info("Deduplication complete")

        except Exception as e:
            logger.error(f"Deduplication failed: {e}", exc_info=True)
            await self._update_status("failed", error_message=str(e))
            raise

    def _dedupe_chapter(self, chapter_data: dict[str, Any], chapter_index: int) -> dict[str, Any]:
        """Deduplicate a single chapter.

        Args:
            chapter_data: Chapter extraction data.
            chapter_index: Chapter index.

        Returns:
            Deduped chapter data.
        """
        extraction = chapter_data.get("extraction", {})

        # Dedupe characters and build registry
        deduped_characters = []
        for char in extraction.get("characters", []):
            deduped_char = self._dedupe_character(char, chapter_index)
            deduped_characters.append(deduped_char)

        extraction["characters"] = deduped_characters

        # Normalize relationships to canonical names
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

        extraction["identity_reveals"] = []  # Clear raw reveals, use canonical

        chapter_data["extraction"] = extraction
        return chapter_data

    def _dedupe_character(self, char: dict[str, Any], chapter_index: int) -> dict[str, Any]:
        """Deduplicate a character and register in canonical registry.

        Args:
            char: Character dict.
            chapter_index: Chapter index.

        Returns:
            Updated character dict with canonical name.
        """
        primary_name = char.get("name", "Unknown")
        canonical_name = self.registry.register(primary_name)

        # Register aliases so they resolve to the same canonical
        for alias in char.get("aliases", []):
            self.registry.register(alias)

        char["canonical_name"] = canonical_name
        return char

    def _resolve_to_canonical(self, name: str) -> str:
        """Resolve a name to its canonical form.

        Args:
            name: Character name to resolve.

        Returns:
            Canonical name, or original if not found.
        """
        return self.registry.resolve(name)

    async def _load_canonical_registry(self) -> None:
        """Load canonical registry from storage (if exists)."""
        try:
            registry_path = (
                f"extractions/{self.user_id}/{self.series_id}/canonical_registry.json"
            )
            content = self.client.storage.from_("extractions").download(registry_path)
            self.registry = CanonicalRegistry.from_dict(json.loads(content))
        except Exception:
            self.registry = CanonicalRegistry()

    async def _load_raw_extractions(self) -> dict[str, Any]:
        """Load raw extractions for this book from storage.

        Returns:
            Dict of chapter extractions.
        """
        try:
            raw_path = (
                f"extractions/{self.user_id}/{self.series_id}/{self.book_id}/chapters.json"
            )
            content = self.client.storage.from_("extractions").download(raw_path)
            return json.loads(content)
        except Exception as e:
            logger.error(f"Failed to load raw extractions: {e}")
            return {}

    async def _save_deduped_extractions(self, extractions: dict[str, Any]) -> None:
        """Save deduped extractions to storage.

        Args:
            extractions: Deduped chapter data.
        """
        deduped_path = (
            f"extractions/{self.user_id}/{self.series_id}/{self.book_id}/deduped_chapters.json"
        )

        try:
            # Delete existing if present
            try:
                self.client.storage.from_("extractions").remove([deduped_path])
            except Exception:
                pass

            # Upload deduped data
            json_bytes = json.dumps(extractions, indent=2).encode("utf-8")
            self.client.storage.from_("extractions").upload(
                path=deduped_path,
                file=json_bytes,
                file_options={"content-type": "application/json"},
            )
            logger.info(f"Saved deduped extractions to {deduped_path}")
        except Exception as e:
            logger.error(f"Failed to save deduped extractions: {e}", exc_info=True)
            raise

    async def _save_canonical_registry(self) -> None:
        """Save updated canonical registry to storage."""
        registry_path = (
            f"extractions/{self.user_id}/{self.series_id}/canonical_registry.json"
        )

        try:
            # Delete existing
            try:
                self.client.storage.from_("extractions").remove([registry_path])
            except Exception:
                pass

            # Upload registry
            json_bytes = json.dumps(self.registry.to_dict(), indent=2).encode("utf-8")
            self.client.storage.from_("extractions").upload(
                path=registry_path,
                file=json_bytes,
                file_options={"content-type": "application/json"},
            )
            logger.info("Saved canonical registry")
        except Exception as e:
            logger.error(f"Failed to save canonical registry: {e}", exc_info=True)
            raise

    async def _update_status(self, status: str, error_message: Optional[str] = None) -> None:
        """Update deduplication status in database.

        Args:
            status: "completed" or "failed".
            error_message: Optional error message.
        """
        try:
            data = {"deduplication_status": status}
            if error_message:
                data["error_message"] = error_message

            self.client.table("book_extractions").update(data).filter(
                "book_id", "eq", self.book_id
            ).filter("user_id", "eq", self.user_id).execute()
        except Exception as e:
            logger.warning(f"Failed to update deduplication status: {e}")
