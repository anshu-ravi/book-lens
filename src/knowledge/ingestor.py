"""GOLD stage: Ingest deduplicated knowledge into Neo4j."""

import json
from pathlib import Path
from typing import Any, Optional

from neo4j import Driver, Session

from src.knowledge.embedder import Embedder
from src.knowledge.neo4j_client import get_driver


class Ingestor:
    """Ingest deduplicated knowledge into Neo4j."""

    def __init__(self, series_id: str, driver: Optional[Driver] = None) -> None:
        """Initialize ingestor.

        Args:
            series_id: Series identifier.
            driver: Neo4j driver. If None, uses singleton.
        """
        self.series_id = series_id
        self.driver = driver or get_driver()
        self.extraction_dir = Path("data/extractions") / series_id
        self.embedder = Embedder()

    def run(self, limit: Optional[int] = None) -> None:
        """Run ingestion of all deduplicated chapters.

        Args:
            limit: If set, only ingest first N chapters.
        """
        # Find all extraction files sorted by chapter index
        extraction_files = sorted(
            self.extraction_dir.glob("*_*.json"),
            key=lambda f: int(f.stem.split("_")[0]),
        )

        if limit:
            extraction_files = extraction_files[:limit]

        for file_path in extraction_files:
            chapter_index = int(file_path.stem.split("_")[0])
            chapter_label = "_".join(file_path.stem.split("_")[1:])
            self._ingest_chapter(file_path, chapter_index, chapter_label)

        # Load and process pending reveals
        self._process_pending_reveals()

    def _ingest_chapter(
        self, file_path: Path, chapter_index: int, chapter_label: str
    ) -> None:
        """Ingest a single chapter.

        Args:
            file_path: Path to extraction JSON.
            chapter_index: Chapter number.
            chapter_label: Chapter title.
        """
        with open(file_path) as f:
            extraction = json.load(f)

        # Check if chapter already ingested
        with self.driver.session() as session:
            result = session.run(
                "MATCH (ch:Chapter {name: $name, series_id: $series_id}) RETURN ch",
                name=chapter_label.replace("_", " "),
                series_id=self.series_id,
            )
            if result.single():
                return  # Skip if chapter exists

        with self.driver.session() as session:
            # Create Chapter node
            session.run(
                """
                CREATE (ch:Chapter {
                    name: $name,
                    series_id: $series_id,
                    chapter_index: $index,
                    summary: $summary
                })
                """,
                name=chapter_label.replace("_", " "),
                series_id=self.series_id,
                index=chapter_index,
                summary=extraction.get("summary", ""),
            )

            # Ingest characters
            for char in extraction.get("characters", []):
                self._ingest_character(session, char, chapter_index)

            # Ingest relationships
            for rel in extraction.get("relationships", []):
                self._ingest_relationship(session, rel, chapter_index)

            # Ingest world facts
            for fact in extraction.get("world_facts", []):
                self._ingest_world_fact(session, fact, chapter_index)

    def _ingest_character(self, session: Session, char: dict[str, Any], chapter_index: int) -> None:
        """Ingest a character with non-destructive MERGE.

        Args:
            session: Neo4j session.
            char: Character dict from extraction.
            chapter_index: Chapter number.
        """
        name = char["name"]
        description = char.get("description", "")
        aliases = char.get("aliases", [])
        faction = char.get("faction")
        first_chapter = char.get("first_chapter_index", chapter_index)

        # Embed description for vector search
        embedding = self.embedder.embed(description) if description else None

        # Ingest character using session.run directly
        session.run(
            """
            MERGE (c:Character {name: $name, series_id: $series_id})
            ON CREATE SET
                c.description = $description,
                c.first_chapter_index = $first_chapter,
                c.aliases = $aliases,
                c.faction = $faction,
                c.embedding = $embedding
            ON MATCH SET
                c.aliases = [x IN c.aliases + $new_aliases
                              WHERE NOT x IN c.aliases],
                c.faction = CASE
                             WHEN $faction IS NOT NULL THEN $faction
                             ELSE c.faction
                             END
            """,
            name=name,
            series_id=self.series_id,
            description=description,
            first_chapter=first_chapter,
            aliases=aliases,
            faction=faction,
            embedding=embedding,
            new_aliases=aliases,
        )

    def _ingest_relationship(self, session: Session, rel: dict[str, Any], chapter_index: int) -> None:
        """Ingest a relationship between characters.

        Args:
            session: Neo4j session.
            rel: Relationship dict from extraction.
            chapter_index: Chapter number.
        """
        char_a = rel["character_a"]
        char_b = rel["character_b"]
        rel_type = rel["type"]  # ALLY, ENEMY, FAMILY, etc.
        description = rel.get("description", "")
        moments = rel.get("moments", [])

        session.run(
            f"""
            MATCH (a:Character {{name: $char_a, series_id: $series_id}})
            MATCH (b:Character {{name: $char_b, series_id: $series_id}})
            MERGE (a)-[r:{rel_type}]->(b)
            ON CREATE SET
                r.description = $description,
                r.moments = $moments,
                r.chapter_index = $chapter_index,
                r.introduced_in = $chapter_index
            ON MATCH SET
                r.moments = r.moments + $moments
            """,
            char_a=char_a,
            char_b=char_b,
            series_id=self.series_id,
            description=description,
            moments=moments,
            chapter_index=chapter_index,
        )

    def _ingest_world_fact(self, session: Session, fact: dict[str, Any], chapter_index: int) -> None:
        """Ingest a world fact.

        Args:
            session: Neo4j session.
            fact: World fact dict from extraction.
            chapter_index: Chapter number.
        """
        category = fact.get("category", "")
        name = fact.get("name", "")
        description = fact.get("description", "")

        session.run(
            """
            MERGE (wf:WorldFact {
                name: $name,
                series_id: $series_id,
                category: $category
            })
            ON CREATE SET wf.description = $description,
                          wf.first_chapter_index = $chapter_index
            """,
            name=name,
            series_id=self.series_id,
            category=category,
            description=description,
            chapter_index=chapter_index,
        )

    def _process_pending_reveals(self) -> None:
        """Process pending identity reveals from deduplication.

        Loads pending_reveals.json and creates REVEALED_AS edges.
        """
        reveals_file = self.extraction_dir / "pending_reveals.json"
        if not reveals_file.exists():
            return

        with open(reveals_file) as f:
            reveals = json.load(f)

        with self.driver.session() as session:
            for reveal in reveals:
                session.run(
                    """
                    MATCH (a:Character {name: $char_a, series_id: $series_id})
                    MATCH (b:Character {name: $char_b, series_id: $series_id})
                    MERGE (a)-[r:REVEALED_AS]->(b)
                    SET r.reveal_chapter_index = $reveal_chapter,
                        r.context = $context
                    """,
                    char_a=reveal["character_a"],
                    char_b=reveal["character_b"],
                    series_id=self.series_id,
                    reveal_chapter=reveal["reveal_chapter_index"],
                    context=reveal["context"],
                )
