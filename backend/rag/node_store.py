"""Direct Supabase read/write for RAG nodes and embeddings.

Owns all Supabase I/O for the RAG pipeline. No LlamaIndex storage abstractions —
every write is explicit and controlled by the caller.

Tables:
  book_rag_nodes      — ALL nodes (leaves + parents), text + metadata JSONB
  book_rag_embeddings — leaf nodes only, vector(384) for ANN search
"""

from typing import Any

from llama_index.core.schema import BaseNode
from llama_index.core.storage.docstore.utils import doc_to_json
from supabase import Client

_NODES_TABLE = "book_rag_nodes"
_EMBEDDINGS_TABLE = "book_rag_embeddings"
_SEARCH_FN = "search_rag_nodes"

_BATCH = 256


class NodeStore:
    """Supabase-backed store for RAG nodes and embeddings.

    Args:
        client: Supabase client.
        series_id: Series slug — scopes all rows.
        book_id: Book slug — scopes all rows.
    """

    def __init__(self, client: Client, series_id: str, book_id: str) -> None:
        self._client = client
        self._series_id = series_id
        self._book_id = book_id

    # ── read ──────────────────────────────────────────────────────────────────

    def get_existing_node_ids(self) -> set[str]:
        """IDs of all nodes already stored for this series/book."""
        ids: set[str] = set()
        page = 0
        while True:
            result = (
                self._client.table(_NODES_TABLE)
                .select("node_id")
                .eq("series_id", self._series_id)
                .eq("book_id", self._book_id)
                .range(page * _BATCH, (page + 1) * _BATCH - 1)
                .execute()
            )
            ids.update(row["node_id"] for row in result.data)
            if len(result.data) < _BATCH:
                break
            page += 1
        return ids

    def get_nodes_by_ids(self, node_ids: list[str]) -> dict[str, dict[str, Any]]:
        """Fetch raw JSONB data for a list of node IDs.

        Used by the auto-merging retriever to walk parent nodes.

        Returns:
            Mapping of node_id → data dict (LlamaIndex serialization format).
        """
        if not node_ids:
            return {}
        result = (
            self._client.table(_NODES_TABLE)
            .select("node_id, data")
            .eq("series_id", self._series_id)
            .eq("book_id", self._book_id)
            .in_("node_id", node_ids)
            .execute()
        )
        return {row["node_id"]: row["data"] for row in result.data}

    def search_nodes(
        self,
        query_embedding: list[float],
        reader_chapter: int,
        top_k: int = 6,
    ) -> list[dict[str, Any]]:
        """pgvector cosine similarity search, spoiler-gated.

        Calls the search_rag_nodes Postgres function (defined in migration 03).

        Args:
            query_embedding: 384-dim query vector.
            reader_chapter: Only return chunks from chapters <= this value.
            top_k: Number of nearest neighbours to return.

        Returns:
            List of {node_id, chapter_index, distance} dicts, sorted by distance.
        """
        result = self._client.rpc(
            _SEARCH_FN,
            {
                "query_embedding": query_embedding,
                "p_series_id": self._series_id,
                "p_book_id": self._book_id,
                "p_reader_chapter": reader_chapter,
                "p_top_k": top_k,
            },
        ).execute()
        return result.data or []

    # ── write ─────────────────────────────────────────────────────────────────

    def upsert_nodes(self, nodes: list[BaseNode]) -> None:
        """Batch upsert nodes to book_rag_nodes.

        Serialises each node to JSONB using LlamaIndex's doc_to_json so
        parent/child relationships are preserved for auto-merging.
        """
        rows = [
            {
                "node_id": n.node_id,
                "series_id": self._series_id,
                "book_id": self._book_id,
                "data": doc_to_json(n),
            }
            for n in nodes
        ]
        self._batch_upsert(_NODES_TABLE, rows, "node_id,series_id,book_id")

    def upsert_embeddings(self, leaf_nodes: list[BaseNode]) -> None:
        """Batch upsert embeddings to book_rag_embeddings.

        Only leaf nodes carry embeddings. chapter_index is promoted to a
        real column here so pgvector queries can filter without touching JSONB.

        Args:
            leaf_nodes: Nodes that have had .embedding set by the embedder.
        """
        rows = [
            {
                "node_id": n.node_id,
                "series_id": self._series_id,
                "book_id": self._book_id,
                "chapter_index": n.metadata["chapter_index"],
                "embedding": n.embedding,
            }
            for n in leaf_nodes
            if n.embedding is not None
        ]
        self._batch_upsert(_EMBEDDINGS_TABLE, rows, "node_id,series_id,book_id")

    # ── internal ──────────────────────────────────────────────────────────────

    def _batch_upsert(self, table: str, rows: list[dict], conflict_cols: str) -> None:
        for i in range(0, len(rows), _BATCH):
            self._client.table(table).upsert(
                rows[i : i + _BATCH],
                on_conflict=conflict_cols,
            ).execute()
