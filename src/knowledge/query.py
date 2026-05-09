"""QUERY: Spoiler-safe query interface for knowledge graph."""

from typing import Any, Optional

from neo4j import Driver

from src.knowledge.embedder import Embedder
from src.knowledge.neo4j_client import get_driver


class KnowledgeQueryEngine:
    """Query the Neo4j knowledge graph with spoiler safety."""

    def __init__(self, series_id: str, driver: Optional[Driver] = None) -> None:
        """Initialize query engine.

        Args:
            series_id: Series identifier.
            driver: Neo4j driver. If None, uses singleton.
        """
        self.series_id = series_id
        self.driver = driver or get_driver()
        self.embedder = Embedder()

    def get_character(
        self, name: str, up_to_chapter: int
    ) -> Optional[dict[str, Any]]:
        """Get full character profile up to a given chapter.

        Args:
            name: Character name (or alias).
            up_to_chapter: Only include information up to this chapter.

        Returns:
            Character profile dict or None if not found.
        """
        with self.driver.session() as session:
            # Find character by name or alias
            result = session.run(
                """
                MATCH (c:Character {series_id: $series_id})
                WHERE c.name = $name OR $name IN c.aliases
                RETURN c
                LIMIT 1
                """,
                series_id=self.series_id,
                name=name,
            )

            char_record = result.single()
            if not char_record:
                return None

            char_node = char_record["c"]
            profile = dict(char_node)
            return profile

    def list_characters(self, up_to_chapter: int) -> list[dict[str, Any]]:
        """List all characters visible up to a chapter.

        Args:
            up_to_chapter: Only include characters first introduced by this chapter.

        Returns:
            List of character profiles.
        """
        with self.driver.session() as session:
            result = session.run(
                """
                MATCH (c:Character {series_id: $series_id})
                WHERE c.first_chapter_index <= $up_to_chapter
                RETURN c
                ORDER BY c.first_chapter_index
                """,
                series_id=self.series_id,
                up_to_chapter=up_to_chapter,
            )

            return [dict(record["c"]) for record in result]

    def get_relationships(
        self, char_name: str, up_to_chapter: int
    ) -> list[dict[str, Any]]:
        """Get all relationships for a character.

        Args:
            char_name: Character name.
            up_to_chapter: Only include relationships introduced by this chapter.

        Returns:
            List of relationship dicts.
        """
        with self.driver.session() as session:
            result = session.run(
                """
                MATCH (c:Character {series_id: $series_id})
                WHERE c.name = $char_name OR $char_name IN c.aliases
                MATCH (c)-[r]->(target:Character)
                WHERE r.introduced_in <= $up_to_chapter
                  AND TYPE(r) IN ['ALLY', 'ENEMY', 'FAMILY', 'ROMANCE', 'MENTOR', 'RIVAL', 'OTHER']
                RETURN c.name as from,
                       target.name as to,
                       TYPE(r) as rel_type,
                       r.description as description,
                       r.moments as moments,
                       r.introduced_in as introduced_in
                ORDER BY r.introduced_in
                """,
                series_id=self.series_id,
                char_name=char_name,
                up_to_chapter=up_to_chapter,
            )

            return [dict(record) for record in result]

    def semantic_search(
        self, query_text: str, up_to_chapter: int, top_k: int = 10
    ) -> list[dict[str, Any]]:
        """Semantic search for characters using vector similarity.

        Filters by:
        - First chapter introduction must be <= up_to_chapter

        Args:
            query_text: Search query.
            up_to_chapter: Only include characters visible by this chapter.
            top_k: Number of results to return.

        Returns:
            List of (character_name, description, similarity_score) dicts.
        """
        # Embed query
        query_embedding = self.embedder.embed(query_text)

        with self.driver.session() as session:
            result = session.run(
                """
                CALL db.index.vector.queryNodes('character_embeddings', $top_k, $query_embedding)
                YIELD node, score
                WHERE node.series_id = $series_id
                  AND node.first_chapter_index <= $up_to_chapter
                RETURN node.name as name,
                       node.description as description,
                       score
                ORDER BY score DESC
                LIMIT $top_k
                """,
                series_id=self.series_id,
                query_embedding=query_embedding,
                up_to_chapter=up_to_chapter,
                top_k=top_k,
            )

            return [dict(record) for record in result]

    def get_chapter_summary(self, chapter_index: int) -> Optional[str]:
        """Get summary for a specific chapter.

        Args:
            chapter_index: Chapter number.

        Returns:
            Chapter summary or None.
        """
        with self.driver.session() as session:
            result = session.run(
                """
                MATCH (ch:Chapter {series_id: $series_id, chapter_index: $index})
                RETURN ch.summary
                """,
                series_id=self.series_id,
                index=chapter_index,
            )

            record = result.single()
            return record[0] if record else None
