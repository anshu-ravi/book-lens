"""Q&A engine: Query Neo4j knowledge graph and get LLM answers."""

import os
from typing import Any

from google import genai
from google.genai import types

from src.config import ModelConfig
from src.knowledge.neo4j_client import get_driver
from src.knowledge.query import KnowledgeQueryEngine


class KnowledgeQA:
    """Answer questions about a book series using its knowledge graph."""

    def __init__(self, series_id: str) -> None:
        """Initialize Q&A engine.

        Args:
            series_id: Series identifier (e.g., 'red-rising').
        """
        self.series_id = series_id
        self.query_engine = KnowledgeQueryEngine(series_id)

        # Initialize Gemini client for generation
        api_key = os.environ.get("GOOGLE_API_KEY", "")
        self.gemini_client = genai.Client(api_key=api_key)

    async def ask(
        self,
        question: str,
        up_to_chapter: int,
        top_k: int = 5,
    ) -> str:
        """Answer a question using knowledge graph context.

        Args:
            question: The question to answer.
            up_to_chapter: Spoiler cutoff — only use info up to this chapter.
            top_k: Number of top characters to include in context.

        Returns:
            Answer string from Gemini.
        """
        # Step 1: Semantic search for relevant characters
        search_results = self.query_engine.semantic_search(
            question, up_to_chapter, top_k=top_k
        )
        char_names = [result["name"] for result in search_results]

        # Step 2: Fetch full profiles and relationships
        characters: dict[str, dict[str, Any]] = {}
        relationships: dict[str, list[dict[str, Any]]] = {}

        for char_name in char_names:
            profile = self.query_engine.get_character(char_name, up_to_chapter)
            if profile:
                characters[char_name] = profile
                rels = self.query_engine.get_relationships(char_name, up_to_chapter)
                relationships[char_name] = rels

        # Step 3: Fetch world facts
        world_facts = self._get_world_facts(up_to_chapter)

        # Step 4: Fetch chapter summaries
        summaries = self._get_chapter_summaries(up_to_chapter)

        # Step 5: Build context
        context = self._build_context(
            list(characters.values()),
            relationships,
            world_facts,
            summaries,
        )

        # Step 6: Call Gemini
        system_prompt = (
            f"You are a knowledgeable reading companion for the book series {self.series_id}.\n"
            f"Answer questions based ONLY on the provided context from the story.\n"
            f"Only include information from chapters the reader has reached (up to chapter {up_to_chapter}).\n"
            f"If you don't know the answer from the context, say so — do not speculate.\n\n"
            f"{context}"
        )

        full_prompt = f"{system_prompt}\n\nQuestion: {question}"

        qa_model = ModelConfig.get_model("qa")
        response = await self.gemini_client.aio.models.generate_content(
            model=qa_model,
            contents=full_prompt,
            config=types.GenerateContentConfig(max_output_tokens=1024),
        )

        answer_text = response.text if response.text else "No answer generated"
        return answer_text

    def _build_context(
        self,
        characters: list[dict[str, Any]],
        relationships: dict[str, list[dict[str, Any]]],
        world_facts: list[dict[str, Any]],
        summaries: list[tuple[int, str]],
    ) -> str:
        """Format retrieved data into context block.

        Args:
            characters: List of character dicts.
            relationships: Dict mapping character names to their relationships.
            world_facts: List of world fact dicts.
            summaries: List of (chapter_index, summary_text) tuples.

        Returns:
            Formatted context string.
        """
        lines = []

        # Characters section
        if characters:
            lines.append("## Characters")
            for char in characters:
                name = char.get("name", "Unknown")
                aliases = char.get("aliases", [])
                faction = char.get("faction", "Unknown faction")
                description = char.get("description", "")

                alias_str = f" ({', '.join(aliases)})" if aliases else ""
                lines.append(f"### {name}{alias_str} ({faction})")
                lines.append(f"- {description}")

                # Add relationships for this character
                char_rels = relationships.get(name, [])
                if char_rels:
                    rel_strs = []
                    for rel in char_rels:
                        to_char = rel.get("to", "Unknown")
                        rel_type = rel.get("rel_type", "OTHER")
                        rel_strs.append(f"{to_char} ({rel_type})")

                    lines.append(f"- Relationships: {', '.join(rel_strs)}")
                lines.append("")

        # World facts section
        if world_facts:
            lines.append("## World Facts")
            for fact in world_facts:
                category = fact.get("category", "Unknown")
                name = fact.get("name", "Unknown")
                description = fact.get("description", "")
                lines.append(f"- **{name}** ({category}): {description}")
            lines.append("")

        # Chapter summaries section
        if summaries:
            lines.append("## Chapter Summaries")
            for chapter_index, summary_text in summaries:
                lines.append(f"- Chapter {chapter_index}: {summary_text[:150]}...")
            lines.append("")

        return "\n".join(lines)

    def _get_world_facts(self, up_to_chapter: int) -> list[dict[str, Any]]:
        """Query Neo4j for world facts up to chapter.

        Args:
            up_to_chapter: Chapter cutoff.

        Returns:
            List of world fact dicts.
        """
        driver = get_driver()
        with driver.session() as session:
            result = session.run(
                """
                MATCH (wf:WorldFact {series_id: $series_id})
                WHERE wf.first_chapter_index <= $up_to_chapter
                RETURN wf.name as name,
                       wf.category as category,
                       wf.description as description
                ORDER BY wf.first_chapter_index
                """,
                series_id=self.series_id,
                up_to_chapter=up_to_chapter,
            )
            return [dict(record) for record in result]

    def _get_chapter_summaries(self, up_to_chapter: int) -> list[tuple[int, str]]:
        """Get chapter summaries up to chapter.

        Args:
            up_to_chapter: Chapter cutoff.

        Returns:
            List of (chapter_index, summary) tuples.
        """
        driver = get_driver()
        with driver.session() as session:
            result = session.run(
                """
                MATCH (ch:Chapter {series_id: $series_id})
                WHERE ch.chapter_index <= $up_to_chapter
                RETURN ch.chapter_index as idx,
                       ch.summary as summary
                ORDER BY ch.chapter_index
                """,
                series_id=self.series_id,
                up_to_chapter=up_to_chapter,
            )
            return [(record["idx"], record["summary"]) for record in result]
