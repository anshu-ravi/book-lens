"""Unified retriever: orchestrates graph and vector retrieval based on query routing."""

import logging
from typing import Any

from pydantic import BaseModel

from backend.knowledge.neo4j_client import get_driver
from backend.knowledge.query import KnowledgeQueryEngine
from backend.knowledge.router import route_query
from backend.rag import NodeStore, retrieve as rag_retrieve
from backend.supabase_client import get_supabase_client

logger = logging.getLogger(__name__)


class RetrievalResult(BaseModel):
    """Combined context from graph and/or vector retrieval."""

    graph_context: str
    vector_context: str
    strategy_used: str


class Retriever:
    """Route a question to graph, vector, or both, then format the retrieved context."""

    def __init__(self, series_id: str) -> None:
        """Initialize retriever.

        Args:
            series_id: Series identifier.
        """
        self.series_id = series_id
        self.query_engine = KnowledgeQueryEngine(series_id)
        self.supabase = get_supabase_client()

    def retrieve(
        self,
        question: str,
        user_id: str,
        up_to_chapter: int,
        conversation_history: list[dict],
        top_k: int = 5,
    ) -> RetrievalResult:
        """Retrieve context for a question using the appropriate strategy.

        Args:
            question: User's question.
            user_id: User identifier (needed for vector store scoping).
            up_to_chapter: Spoiler cutoff chapter index.
            conversation_history: Prior conversation turns (role/content dicts).
            top_k: Number of results to retrieve per source.

        Returns:
            RetrievalResult with graph_context, vector_context, and strategy_used.
        """
        decision = route_query(question, conversation_history)
        logger.info(f"Routing '{question[:60]}' → {decision.strategy}: {decision.reasoning}")

        graph_context = ""
        vector_context = ""

        if decision.strategy in ("graph", "hybrid"):
            graph_context = self._fetch_graph_context(question, up_to_chapter, top_k)

        if decision.strategy in ("vector", "hybrid"):
            vector_context = self._fetch_vector_context(
                question, user_id, up_to_chapter, top_k
            )

        return RetrievalResult(
            graph_context=graph_context,
            vector_context=vector_context,
            strategy_used=decision.strategy,
        )

    def _fetch_graph_context(self, question: str, up_to_chapter: int, top_k: int) -> str:
        """Build formatted context from the knowledge graph.

        Args:
            question: Used for semantic character search.
            up_to_chapter: Spoiler cutoff.
            top_k: Number of characters to retrieve.

        Returns:
            Markdown-formatted context string.
        """
        lines: list[str] = []

        # Find relevant characters via semantic search on character embeddings
        search_results = self.query_engine.semantic_search(question, up_to_chapter, top_k=top_k)
        char_names = [r["name"] for r in search_results]

        if char_names:
            lines.append("## Characters")
            for name in char_names:
                profile = self.query_engine.get_character(name, up_to_chapter)
                if not profile:
                    continue
                aliases = profile.get("aliases", [])
                alias_str = f" ({', '.join(aliases)})" if aliases else ""
                faction = profile.get("faction", "")
                lines.append(f"### {name}{alias_str}{f' ({faction})' if faction else ''}")
                lines.append(f"- {profile.get('description', '')}")

                rels = self.query_engine.get_relationships(name, up_to_chapter)
                if rels:
                    rel_strs = [f"{r['to']} ({r['rel_type']})" for r in rels]
                    lines.append(f"- Relationships: {', '.join(rel_strs)}")
                lines.append("")

        world_facts = self._get_world_facts(up_to_chapter)
        if world_facts:
            lines.append("## World Facts")
            for fact in world_facts:
                lines.append(
                    f"- **{fact['name']}** ({fact['category']}): {fact['description']}"
                )
            lines.append("")

        summaries = self._get_chapter_summaries(up_to_chapter)
        if summaries:
            lines.append("## Chapter Summaries")
            # Only include the last 5 summaries to keep the context window manageable
            for idx, summary in summaries[-5:]:
                lines.append(f"- Chapter {idx}: {summary[:150]}...")
            lines.append("")

        return "\n".join(lines)

    def _fetch_vector_context(
        self, question: str, user_id: str, up_to_chapter: int, top_k: int
    ) -> str:
        """Build formatted context from relevant prose passages via RAG retrieval.

        Searches across all books the user has in this series. Each book's
        hierarchical nodes are searched independently; results are merged.

        Args:
            question: Query to embed and search.
            user_id: User identifier — scopes which books to search.
            up_to_chapter: Spoiler cutoff (chapter_index gate).
            top_k: Number of passages to retrieve per book.

        Returns:
            Markdown-formatted passage context string.
        """
        resp = (
            self.supabase.table("books")
            .select("id")
            .eq("series_id", self.series_id)
            .eq("user_id", user_id)
            .execute()
        )
        book_ids = [row["id"] for row in (resp.data or [])]
        if not book_ids:
            return ""

        all_nodes = []
        for book_id in book_ids:
            store = NodeStore(self.supabase, series_id=self.series_id, book_id=book_id)
            nodes = rag_retrieve(
                query=question,
                node_store=store,
                reader_chapter=up_to_chapter,
                top_k=top_k,
            )
            all_nodes.extend(nodes)

        if not all_nodes:
            return ""

        lines = ["## Relevant Passages from the Book"]
        for i, node in enumerate(all_nodes[:top_k], 1):
            label = node.metadata.get(
                "chapter_label",
                f"Chapter {node.metadata.get('chapter_index', '?')}",
            )
            lines.append(f"### Passage {i} (from {label})")
            lines.append(node.text)
            lines.append("")

        return "\n".join(lines)

    def _get_world_facts(self, up_to_chapter: int) -> list[dict[str, Any]]:
        driver = get_driver()
        with driver.session() as session:
            result = session.run(
                """
                MATCH (wf:WorldFact {series_id: $series_id})
                WHERE wf.first_chapter_index <= $up_to_chapter
                RETURN wf.name as name, wf.category as category, wf.description as description
                ORDER BY wf.first_chapter_index
                """,
                series_id=self.series_id,
                up_to_chapter=up_to_chapter,
            )
            return [dict(r) for r in result]

    def _get_chapter_summaries(self, up_to_chapter: int) -> list[tuple[int, str]]:
        driver = get_driver()
        with driver.session() as session:
            result = session.run(
                """
                MATCH (ch:Chapter {series_id: $series_id})
                WHERE ch.chapter_index <= $up_to_chapter
                RETURN ch.chapter_index as idx, ch.summary as summary
                ORDER BY ch.chapter_index
                """,
                series_id=self.series_id,
                up_to_chapter=up_to_chapter,
            )
            return [(r["idx"], r["summary"]) for r in result]
