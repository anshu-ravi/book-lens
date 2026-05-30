"""GOLD stage: Ingest deduplicated knowledge into Neo4j."""

import json
import logging
from typing import Any, Optional

from backend.knowledge.embedder import Embedder
from backend.knowledge.neo4j_client import get_driver
from backend.supabase_client import get_supabase_client

logger = logging.getLogger(__name__)


def _series_label(series_id: str) -> str:
    """Convert a series slug to a valid Neo4j label (PascalCase, no hyphens).

    "the-red-rising-saga" → "TheRedRisingSaga"
    """
    return "".join(
        w.capitalize() for w in series_id.replace("-", " ").replace("_", " ").split()
    )


class IngestionService:
    """Ingest deduplicated knowledge into Neo4j."""

    def __init__(self, user_id: str, book_id: str, series_id: str) -> None:
        """Initialize ingestion service.

        Args:
            user_id: User identifier.
            book_id: Book identifier.
            series_id: Series identifier.
        """
        self.user_id = user_id
        self.book_id = book_id
        self.series_id = series_id
        self.client = get_supabase_client()
        self.driver = get_driver()
        self.embedder = Embedder()

    async def ingest_book(self) -> None:
        """Ingest deduped chapters into Neo4j.

        Creates character nodes, relationships, and links to chapters.
        """
        try:
            logger.info(f"Starting ingestion for book {self.book_id}")

            # Load deduped extractions
            deduped_extractions = await self._load_deduped_extractions()
            if not deduped_extractions:
                logger.warning("No deduped extractions found")
                return

            # Ingest chapters
            for chapter_idx, chapter_data in sorted(
                deduped_extractions.items(), key=lambda x: int(x[0])
            ):
                await self._ingest_chapter(chapter_data, int(chapter_idx))

            # Process pending reveals (identity links)
            await self._process_pending_reveals()

            # Update database status
            await self._update_status("completed")
            logger.info("Ingestion complete")

        except Exception as e:
            logger.error(f"Ingestion failed: {e}", exc_info=True)
            await self._update_status("failed", error_message=str(e))
            raise

    async def _ingest_chapter(self, chapter_data: dict[str, Any], chapter_index: int) -> None:
        """Ingest a single chapter into Neo4j.

        Args:
            chapter_data: Chapter extraction data.
            chapter_index: Chapter index.
        """
        extraction = chapter_data.get("extraction", {})
        chapter_label = chapter_data.get("chapter_label", f"Chapter {chapter_index}")

        label = _series_label(self.series_id)

        with self.driver.session() as session:
            # Check if chapter already exists
            result = session.run(
                f"MATCH (ch:Chapter:{label} {{name: $name, book_id: $book_id}}) RETURN ch",
                name=chapter_label,
                book_id=self.book_id,
            )
            if result.single():
                logger.info(f"Chapter {chapter_index} already ingested, skipping")
                return

            # Create Chapter node with series label for structural isolation
            session.run(
                f"""
                CREATE (ch:Chapter:{label} {{
                    name: $name,
                    series_id: $series_id,
                    book_id: $book_id,
                    chapter_index: $index,
                    summary: $summary
                }})
                """,
                name=chapter_label,
                series_id=self.series_id,
                book_id=self.book_id,
                index=chapter_index,
                summary=extraction.get("summary", ""),
            )

            # Ingest characters
            for char in extraction.get("characters", []):
                self._ingest_character(session, char, chapter_index)

            # Ingest relationships
            for rel in extraction.get("relationships", []):
                self._ingest_relationship(session, rel, chapter_index)

            logger.info(f"Ingested chapter {chapter_index}")

    def _ingest_character(
        self, session: Any, char: dict[str, Any], chapter_index: int
    ) -> None:
        """Ingest a character into Neo4j.

        Args:
            session: Neo4j session.
            char: Character data.
            chapter_index: Chapter index.
        """
        name = char.get("canonical_name", char.get("name", "Unknown"))
        label = _series_label(self.series_id)

        # Check if character exists (scoped by series label)
        result = session.run(
            f"MATCH (c:Character:{label} {{name: $name}}) RETURN c",
            name=name,
        )

        if result.single():
            return  # Character already exists

        # Create character node with series label for structural isolation
        description = char.get("description", "")
        embedding = self.embedder.embed(description) if description else None

        session.run(
            f"""
            CREATE (c:Character:{label} {{
                name: $name,
                series_id: $series_id,
                aliases: $aliases,
                role: $role,
                description: $description,
                embedding: $embedding,
                first_chapter_index: $first_chapter
            }})
            """,
            name=name,
            series_id=self.series_id,
            aliases=char.get("aliases", []),
            role=char.get("role"),
            description=description,
            embedding=embedding,
            first_chapter=chapter_index,
        )

    def _ingest_relationship(
        self, session: Any, rel: dict[str, Any], chapter_index: int
    ) -> None:
        """Ingest a relationship into Neo4j.

        Args:
            session: Neo4j session.
            rel: Relationship data.
            chapter_index: Chapter index.
        """
        char_a = rel.get("character_a", "Unknown")
        char_b = rel.get("character_b", "Unknown")
        rel_type = rel.get("type", "UNKNOWN")
        description = rel.get("description", "")
        moments = rel.get("moments", [])
        label = _series_label(self.series_id)

        # MERGE relationship — safe to re-run; appends unique moments on match
        cypher = f"""
        MATCH (a:Character:{label} {{name: $char_a}})
        MATCH (b:Character:{label} {{name: $char_b}})
        MERGE (a)-[r:{rel_type}]->(b)
        ON CREATE SET r.description = $description,
                      r.introduced_in = $introduced_in,
                      r.moments = $moments
        ON MATCH SET  r.introduced_in = CASE
                          WHEN $introduced_in < r.introduced_in
                          THEN $introduced_in ELSE r.introduced_in END,
                      r.moments = [x IN r.moments + $moments WHERE NOT x IN r.moments]
        """

        try:
            session.run(
                cypher,
                char_a=char_a,
                char_b=char_b,
                description=description,
                introduced_in=chapter_index,
                moments=moments,
            )
        except Exception as e:
            logger.warning(f"Failed to merge relationship {char_a}-{rel_type}-{char_b}: {e}")

    async def _process_pending_reveals(self) -> None:
        """Process identity reveals (same character under different names)."""
        logger.info("Processing identity reveals")

        # Load pending reveals from canonical registry
        # For now, reveals are stored in deduped extractions
        # This would be expanded to handle cross-book reveals

    async def _load_deduped_extractions(self) -> dict[str, Any]:
        """Load deduped extractions from storage.

        Returns:
            Dict of deduped chapter extractions.
        """
        try:
            deduped_path = (
                f"extractions/{self.user_id}/{self.series_id}/{self.book_id}/deduped_chapters.json"
            )
            content = self.client.storage.from_("extractions").download(deduped_path)
            return json.loads(content)
        except Exception as e:
            logger.error(f"Failed to load deduped extractions: {e}")
            return {}

    async def _update_status(self, status: str, error_message: Optional[str] = None) -> None:
        """Update ingestion status in database.

        Args:
            status: "completed" or "failed".
            error_message: Optional error message.
        """
        try:
            data = {"ingestion_status": status}
            if error_message:
                data["error_message"] = error_message

            self.client.table("book_extractions").update(data).filter(
                "book_id", "eq", self.book_id
            ).filter("user_id", "eq", self.user_id).execute()
        except Exception as e:
            logger.warning(f"Failed to update ingestion status: {e}")
