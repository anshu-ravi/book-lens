"""QUERY: Spoiler-safe query interface for knowledge graph."""

from typing import Any, Optional

from neo4j import Driver

from backend.knowledge.embedder import Embedder
from backend.knowledge.neo4j_client import get_driver


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
            # Find character by name or alias, gated by reader's chapter position
            result = session.run(
                """
                MATCH (c:Character {series_id: $series_id})
                WHERE (c.name = $name OR $name IN c.aliases)
                  AND c.first_chapter_index <= $up_to_chapter
                RETURN c
                LIMIT 1
                """,
                series_id=self.series_id,
                name=name,
                up_to_chapter=up_to_chapter,
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
                MATCH (c)-[r]-(target:Character)
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
        self, query_text: str, up_to_chapter: int, top_k: int = 10, min_score: float = 0.0
    ) -> list[dict[str, Any]]:
        """Semantic search for characters using vector similarity.

        Filters by:
        - First chapter introduction must be <= up_to_chapter
        - Similarity score must be >= min_score

        Args:
            query_text: Search query.
            up_to_chapter: Only include characters visible by this chapter.
            top_k: Number of results to return.
            min_score: Minimum cosine similarity score (0.0–1.0).

        Returns:
            List of (character_name, description, similarity_score) dicts.
        """
        query_embedding = self.embedder.embed(query_text)

        with self.driver.session() as session:
            # Fetch 10x candidates from the vector index before applying the
            # spoiler-gate WHERE filter — the index returns global top-k first,
            # so early chapters get silently dropped without this headroom.
            result = session.run(
                """
                CALL db.index.vector.queryNodes('character_embeddings', $fetch_k, $query_embedding)
                YIELD node, score
                WHERE node.series_id = $series_id
                  AND node.first_chapter_index <= $up_to_chapter
                  AND score >= $min_score
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
                fetch_k=top_k * 10,
                min_score=min_score,
            )

            return [dict(record) for record in result]

    def _get_known_names(self, up_to_chapter: int) -> list[str]:
        """Return all character names (and aliases) visible up to a chapter."""
        with self.driver.session() as session:
            result = session.run(
                """
                MATCH (c:Character {series_id: $series_id})
                WHERE c.first_chapter_index <= $up_to_chapter
                RETURN c.name as name, c.aliases as aliases
                """,
                series_id=self.series_id,
                up_to_chapter=up_to_chapter,
            )
            names: list[str] = []
            for record in result:
                names.append(record["name"])
                names.extend(record["aliases"] or [])
            return names

    def get_graph_context(
        self, query_text: str, up_to_chapter: int, top_k: int = 5
    ) -> str:
        """Build a rich graph context string for answer generation.

        Named characters found in the query are always included. Remaining
        slots are filled by semantic search. Relationship edges between all
        retrieved characters (both directions) are appended.

        Args:
            query_text: The user's question.
            up_to_chapter: Spoiler gate.
            top_k: Max total characters to include.

        Returns:
            Formatted context string ready to inject into a prompt.
        """
        query_lower = query_text.lower()

        # Direct name match — always include characters explicitly named in the query
        known_names = self._get_known_names(up_to_chapter)
        named: list[dict[str, Any]] = []
        named_set: set[str] = set()
        for name in known_names:
            if name.lower() in query_lower and name not in named_set:
                char = self.get_character(name, up_to_chapter)
                if char:
                    named.append({"name": char["name"], "description": char.get("description", "")})
                    named_set.add(char["name"])

        # Fill remaining slots with semantic search
        remaining = max(0, top_k - len(named))
        semantic: list[dict[str, Any]] = []
        if remaining > 0:
            candidates = self.semantic_search(query_text, up_to_chapter, top_k=top_k)
            for c in candidates:
                if c["name"] not in named_set:
                    semantic.append(c)
                    if len(semantic) >= remaining:
                        break

        characters = named + semantic
        if not characters:
            return "No relevant characters found."

        char_names = {c["name"] for c in characters}
        lines: list[str] = []
        for c in characters:
            lines.append(f"{c['name']}: {c['description']}")

        # Fetch relationships between retrieved characters in both directions
        rel_lines: list[str] = []
        seen: set[tuple[str, str, str]] = set()
        for c in characters:
            for rel in self.get_relationships(c["name"], up_to_chapter):
                key = (c["name"], rel["rel_type"], rel["to"])
                rev_key = (rel["to"], rel["rel_type"], c["name"])
                if key not in seen and rev_key not in seen and rel["to"] in char_names:
                    seen.add(key)
                    rel_lines.append(
                        f"{c['name']} —[{rel['rel_type']}]→ {rel['to']}: {rel['description']}"
                    )

        if rel_lines:
            lines.append("\nRelationships:")
            lines.extend(rel_lines)

        return "\n".join(lines)

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

    def get_timeline(self, to_chapter_index: int) -> dict[str, Any]:
        """Get chapter and reveal data for the story timeline visualization.

        Args:
            to_chapter_index: Only include data up to this chapter index.

        Returns:
            Dict with 'chapters' and 'reveals' lists.
        """
        with self.driver.session() as session:
            chapter_result = session.run(
                """
                MATCH (c:Chapter {series_id: $series_id})
                WHERE c.chapter_index <= $to_chapter_index
                RETURN c.chapter_index AS chapter_index,
                       c.name AS name,
                       c.summary AS summary,
                       c.book_id AS book_id
                ORDER BY c.chapter_index ASC
                """,
                series_id=self.series_id,
                to_chapter_index=to_chapter_index,
            )
            chapters = [dict(record) for record in chapter_result]

            reveals: list[dict[str, Any]] = []
            try:
                reveal_result = session.run(
                    """
                    MATCH (a:Character {series_id: $series_id})-[r:REVEALED_AS]->(b:Character {series_id: $series_id})
                    WHERE r.reveal_chapter_index <= $to_chapter_index
                    RETURN a.name AS from_name,
                           b.name AS to_name,
                           r.reveal_chapter_index AS chapter_index,
                           r.context AS context
                    """,
                    series_id=self.series_id,
                    to_chapter_index=to_chapter_index,
                )
                reveals = [dict(record) for record in reveal_result]
            except Exception:
                pass

        return {"chapters": chapters, "reveals": reveals}
